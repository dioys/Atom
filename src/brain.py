"""brain.py - Atom's thinking. No window code in here.

Atom can think with Google Gemini (free tier), Groq (free plan), Ollama
(runs on your own computer) or Claude. You pick one in Settings; the choices
live in config.PROVIDERS. If none is set up, Atom falls back to a few
built-in replies so the interface still works.

Step 2: before asking the AI, Atom searches the file library and injects
the most relevant excerpts into the system prompt.

Speed: answers are streamed, so words appear in the bubble as soon as the AI
starts writing instead of after the whole answer is finished.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import atomlog
import config
import personality
from memory import Memory
from tools import FileStore, ToolBox

try:
    import anthropic
except ImportError:  # the app still opens; Atom just explains what is missing
    anthropic = None

_OPENAI_ERROR = ""
try:
    import openai  # used for Gemini, Groq and Ollama (they all speak the same language)
except ImportError as _error:
    openai = None
    _OPENAI_ERROR = str(_error)


def running_from() -> str:
    """Which Atom and which Python is this? (so a 'package missing' message can say whose packages it looked in)"""
    import sys
    if getattr(sys, "frozen", False):
        return f"the packaged Atom.exe ({sys.executable})"
    return f"{sys.executable} (Atom files in {Path(__file__).resolve().parent})"

KEY_HELP = (
    "I'm running without my AI brain right now. Click Settings, choose an AI "
    "provider and paste its key. Google Gemini has a free tier."
)


class Brain:
    def __init__(self, store: FileStore):
        self.store = store
        # Step 5: memory. If the memory file can't be opened, Atom still works without it.
        self.memory: Memory | None = None
        if config.MEMORY:
            try:
                self.memory = Memory()
            except Exception as error:
                print(f"[atom] memory turned off: {error}")
        self.daily = self._open_daily()
        self.profile = self._open_profile(store)   # Step 13: your skills and the files that describe you
        self.calls = self._open_calls()            # Step 13: calls, what was said and what was asked of you
        self.tools = ToolBox(store, memory=self.memory, daily=self.daily, profile=self.profile, calls=self.calls)  # Step 3: what the AI may do
        if self.profile is not None:
            self.profile.ask = self.ask_once
        self.history: list[dict] = []
        self._last_talked: float | None = None
        if self.memory:  # pick up where yesterday's conversation stopped
            self.history = self.memory.recent_messages(config.RESTORE_MESSAGES)
            while self.history and self.history[0]["role"] != "user":
                self.history.pop(0)
            self._last_talked = self.memory.last_message_time()
        self._client = None
        self._client_id = None
        self._active_model: dict[str, str] = {}  # last model that worked, per provider
        self._no_tools: set[str] = set()  # providers whose model refused tools
        self._on_status = None
        self._tool_names: list[str] | None = None  # tools sent with the current question
        self._used_tools: list[str] = []  # tools used for this question (sent again with the next one)

    @property
    def last_talked(self) -> float | None:
        """When the previous session's last message was sent (None = first run)."""
        return self._last_talked

    def user_name(self) -> str | None:
        """The user's name, if a saved note says it."""
        if not self.memory:
            return None
        try:
            return personality.find_name(self.memory.notes())
        except Exception:
            return None

    def reset_client(self) -> None:
        """Call after Settings change so the next reply uses the new provider/key."""
        self._client = None
        self._client_id = None
        self._active_model = {}
        self._no_tools = set()

    # ----------------------------------------------------------- status
    @staticmethod
    def _missing_package(provider: str) -> str:
        if provider == "claude" and anthropic is None:
            return "The 'anthropic' package is not installed (python -m pip install anthropic)."
        if provider != "claude" and openai is None:
            return (
                f"This Atom can't load the 'openai' package ({_OPENAI_ERROR or 'not found'}). It is running from {running_from()}. "
                "If you already installed it, you are most likely running an OLD copy of Atom (an old Atom.exe or another folder): "
                "start Atom with  python main.py  in the Atom folder, or run  python make_shortcut.py  and use that shortcut. "
                "If this is the right copy, run  python -m pip install openai  with the SAME python."
            )
        return ""

    @property
    def available(self) -> bool:
        provider = config.get_provider()
        if self._missing_package(provider):
            return False
        return bool(config.get_api_key(provider)) or not config.PROVIDERS[provider]["needs_key"]

    @property
    def status_text(self) -> str:
        provider = config.get_provider()
        missing = self._missing_package(provider)
        if missing:
            return missing
        if config.PROVIDERS[provider]["needs_key"] and not config.get_api_key(provider):
            return KEY_HELP
        return ""

    # ------------------------------------------------------------ reply
    def reply(self, text: str, on_text=None, confirm=None, on_status=None) -> str:
        """Return Atom's answer to `text`. Safe to call from a background thread.

        on_text(answer_so_far)  - called as words arrive, so the window can show them live.
        confirm(question)->bool - asks you Yes/No before Atom opens a file or an app.
        on_status(message)      - called when Atom starts using a tool ("Searching...").
        """
        if not self.available:
            return self._offline_reply(text)

        self.tools.confirm = confirm
        self._on_status = on_status
        self._tool_names = self.tools.pick(text)  # only the tools this message needs
        for name in self._used_tools:  # a follow-up like "the 2025 one" may need the tool just used
            if name not in self._tool_names:
                self._tool_names.append(name)
        self._used_tools = []
        provider = config.get_provider()
        self.history.append({"role": "user", "content": text})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES :]
        # the conversation sent to the API must start with a user message
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

        # Step 2: pull relevant file excerpts for this question
        system = self._system(text)

        try:
            answer = self._ask(provider, system, on_text)
            answer = self.plain_code(answer).strip() or "(I had nothing to say - try asking again.)"
        except Exception as error:  # network, bad key, rate limit, ...
            self.history.pop()  # forget the message that failed
            atomlog.exception(f"asking {provider}", error)
            return f"Sorry, I couldn't reach my brain: {self._explain(error, provider)}"

        self.history.append({"role": "assistant", "content": answer})
        if self.memory:  # saved only after a successful answer
            try:
                self.memory.add_message("user", text)
                self.memory.add_message("assistant", answer)
            except Exception as error:
                print(f"[atom] couldn't save the chat: {error}")
        return answer

    @staticmethod
    def plain_code(answer: str) -> str:
        """The chat box shows plain text, so the ``` lines around code are dropped (the code itself stays as it is)."""
        lines = str(answer).splitlines()
        if not any(line.lstrip().startswith("```") for line in lines):
            return answer
        return "\n".join(line for line in lines if not line.lstrip().startswith("```")).strip("\n")

    @staticmethod
    def _open_daily():
        """Reminders and the to-do list. If their file can't be opened, Atom still works without them."""
        if not getattr(config, "DAILY", True):
            return None
        try:
            import daily
            return daily.Daily()
        except Exception as error:
            print(f"[atom] reminders and to-do list turned off: {error}")
            return None

    @staticmethod
    def _open_profile(store):
        """Your skills memory. If its file can't be opened, Atom still works without it."""
        if not getattr(config, "PROFILE", True):
            return None
        try:
            import userprofile
            return userprofile.Profile(store)
        except Exception as error:
            print(f"[atom] skills profile turned off: {error}")
            return None

    @staticmethod
    def _open_calls():
        """The call log. If its file can't be opened, Atom still works without it."""
        if not getattr(config, "CALL_HELPER", True):
            return None
        try:
            import callmode
            return callmode.CallLog()
        except Exception as error:
            print(f"[atom] call helper turned off: {error}")
            return None

    def ask_once(self, system: str, user: str, on_text=None) -> str:
        """One question with no chat history and no tools (call answers, summaries, reading your CV).
        Safe to call from any thread while a normal chat answer is running. Raises if it fails."""
        if not self.available:
            raise RuntimeError("No AI is available. Add a key in Settings.")
        provider = config.get_provider()
        return self._ask(provider, system, on_text, history=[{"role": "user", "content": user}], tools=False).strip()

    def _system(self, text: str) -> str:
        """The instructions sent with every question: who Atom is, today's date,
        what he remembers, and the file excerpts that match the question."""
        parts = [config.SYSTEM_PROMPT, "Now: " + datetime.now().strftime("%A %d %B %Y, %H:%M") + "."]
        if self.memory:
            try:
                notes = self.memory.notes_text(config.MAX_MEMORY_CHARS)
            except Exception:
                notes = ""
            if notes:
                parts.append("Saved notes about the user:\n" + notes)
            if self._last_talked:
                stamp = datetime.fromtimestamp(self._last_talked).strftime("%A %d %B, %H:%M")
                parts.append(f"Your previous message in an earlier session was on {stamp}.")
        if self.profile is not None:
            try:
                about_user = self.profile.relevant(text, 700)
            except Exception:
                about_user = ""
            if about_user:
                parts.append("The user's skills profile (their own facts, use them when they ask about themselves):\n" + about_user)
        parts.append("Excerpts found automatically for this question:\n" + self.store.context_for(text))
        return "\n\n".join(parts)

    # errors that usually mean "the server is busy right now", worth trying again
    RETRY_STATUSES = (500, 502, 503, 504, 529)
    RETRY_DELAYS = (2, 5)  # seconds to wait before the 2nd and 3rd try

    def _models_for(self, provider: str) -> list[str]:
        """Models to try, in order: the one that worked last, your choice, then backups."""
        chosen = config.get_model(provider)
        models = [self._active_model.get(provider) or chosen]
        for name in [chosen, *config.PROVIDERS[provider].get("fallback_models", [])]:
            if name not in models:
                models.append(name)
        return models

    def _ask(self, provider: str, system: str, on_text, **opts) -> str:
        """Ask the AI. If a model's free allowance is used up (or it doesn't exist),
        quietly move on to the next model in the list."""
        models = self._models_for(provider)
        for i, model in enumerate(models):
            try:
                answer = self._ask_model(provider, model, system, on_text, **opts)
                self._active_model[provider] = model  # start here next time
                return answer
            except Exception as error:
                status = getattr(error, "status_code", None)
                if i < len(models) - 1 and status in (429, 404):
                    continue
                raise
        return ""  # not reached; keeps type checkers happy

    def _ask_model(self, provider: str, model: str, system: str, on_text, **opts) -> str:
        """Ask one model, retrying a couple of times if the provider is briefly overloaded."""
        for delay in (*self.RETRY_DELAYS, None):
            try:
                return self._call_model(provider, model, system, on_text, **opts)
            except Exception as error:
                busy = getattr(error, "status_code", None) in self.RETRY_STATUSES
                if delay is None or not busy:
                    raise
                time.sleep(delay)
        return ""  # not reached; keeps type checkers happy

    def _call_model(self, provider: str, model: str, system: str, on_text, **opts) -> str:
        """One request. If the AI tries a tool that wasn't sent with this question (it knows every tool from
        its instructions), send that tool too and ask again."""
        for _attempt in range(4):
            try:
                if provider == "claude":
                    return self._ask_claude(model, system, on_text, **opts)
                return self._ask_compatible(provider, model, system, on_text, **opts)
            except Exception as error:
                if not self._allow_tool(error):
                    raise
        return ""  # not reached

    def _allow_tool(self, error: Exception) -> bool:
        """True if `error` says the AI called a tool that wasn't in the request, and that is now fixed."""
        text = str(error)
        if "request.tools" not in text and "not in request" not in text:
            return False
        if self._tool_names is None:
            return False  # every tool was already sent: nothing more to add
        found = re.search(r"tool ['\"`]?([\w-]+)['\"`]? which was not", text) or re.search(r"call tool ['\"`]?([\w-]+)", text)
        known = {s["name"] for s in self.tools.SPECS}
        name = found.group(1) if found else ""
        if name in known and name not in self._tool_names:
            self._tool_names.append(name)
        else:
            self._tool_names = None  # unknown name: send every tool this time
        print(f"[atom] the AI asked for a tool I hadn't sent ({name or '?'}); sending it and asking again", flush=True)
        return True

    def _client_for(self, provider: str, build):
        """Reuse one client until the provider or key changes."""
        key = config.get_api_key(provider)
        signature = (provider, key, config.PROVIDERS[provider]["base_url"])
        if self._client is None or self._client_id != signature:
            self._client = build(key)
            self._client_id = signature
        return self._client

    def _ask_claude(self, model: str, system: str, on_text, history=None, tools=True) -> str:
        client = self._client_for("claude", lambda key: anthropic.Anthropic(api_key=key))
        messages = list(self.history if history is None else history)  # this turn's tool steps are added here, not to history
        text = ""
        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            # the last round has no tools, so Atom must give an answer
            extra = {"tools": self.tools.claude_tools(self._tool_names)} if round_number < config.MAX_TOOL_ROUNDS and tools else {}
            text = ""
            with client.messages.stream(
                model=model,
                max_tokens=config.MAX_TOKENS,
                system=system,
                messages=messages,
                **extra,
            ) as stream:
                for piece in stream.text_stream:
                    text += piece
                    if on_text:
                        on_text(text)
                final = stream.get_final_message()

            calls = [block for block in final.content if block.type == "tool_use"]
            if not calls:
                break
            messages.append(
                {"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in final.content]}
            )
            results = [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": self._run_tool(call.name, call.input),
                }
                for call in calls
            ]
            messages.append({"role": "user", "content": results})
        return text

    def _run_tool(self, name: str, args: dict) -> str:
        """Run one tool the AI asked for, telling the window what is happening."""
        if self._on_status:
            self._on_status(self.tools.status_for(name, args))
        if name not in self._used_tools:
            self._used_tools.append(name)
        result = self.tools.run(name, args)
        # shown in the terminal where you ran main.py, to see what Atom really did
        print(f"[atom] tool {name} {args} -> {str(result)[:300]}", flush=True)
        return result

    def _ask_compatible(self, provider: str, model: str, system: str, on_text, history=None, tools=True) -> str:
        """Gemini, Groq and Ollama all accept the same request format."""
        info = config.PROVIDERS[provider]
        client = self._client_for(
            provider,
            lambda key: openai.OpenAI(
                api_key=key or "not-needed", base_url=info["base_url"], timeout=60
            ),
        )
        messages = [{"role": "system", "content": system}] + list(self.history if history is None else history)
        text = ""
        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            use_tools = round_number < config.MAX_TOOL_ROUNDS and provider not in self._no_tools and tools
            stream = self._open_stream(client, provider, model, messages, use_tools)
            text = ""
            calls: dict[int, dict] = {}  # tool calls arrive in small pieces; glue them together
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = delta.content or ""
                if piece:
                    text += piece
                    if on_text:
                        on_text(text)
                for part in getattr(delta, "tool_calls", None) or []:
                    function = part.function
                    if part.index is not None:
                        slot_id = part.index
                    elif function is not None and function.name:
                        slot_id = len(calls)  # some providers send whole calls without an index
                    else:
                        slot_id = max(calls, default=0)
                    slot = calls.setdefault(slot_id, {"id": "", "name": "", "arguments": ""})
                    if part.id:
                        slot["id"] = part.id
                    if function is not None:
                        slot["name"] = function.name or slot["name"]
                        slot["arguments"] += function.arguments or ""
            calls_list = [calls[i] for i in sorted(calls) if calls[i]["name"]]
            if not calls_list:
                break

            for number, call in enumerate(calls_list):
                call["id"] = call["id"] or f"call_{round_number}_{number}"
            messages.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                        }
                        for c in calls_list
                    ],
                }
            )
            for call in calls_list:
                try:
                    args = json.loads(call["arguments"] or "{}")
                except ValueError:
                    args = {}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": self._run_tool(call["name"], args),
                    }
                )
        return text

    @staticmethod
    def _rate_limit_wait(error: Exception) -> float | None:
        """Seconds the provider asks us to wait (free plans allow only so many
        words per minute). None if it is a long wait, like a daily limit."""
        seconds = None
        headers = getattr(getattr(error, "response", None), "headers", None)
        try:
            value = headers.get("retry-after") if headers else None
            seconds = float(value) if value else None
        except (TypeError, ValueError, AttributeError):
            seconds = None
        if seconds is None:
            found = re.search(r"try again in\s*(?:(\d+)m)?([\d.]+)(ms|s)\b", str(error))
            if found:
                amount = float(found.group(2)) / (1000 if found.group(3) == "ms" else 1)
                seconds = int(found.group(1) or 0) * 60 + amount
        if seconds is None or seconds > 30:
            return None
        return seconds + 1

    def _wait_if_rate_limited(self, call):
        """Run `call`. If the provider says 'wait a few seconds', wait and try again
        (up to twice) so a long task carries on instead of failing half way."""
        for attempt in range(3):
            try:
                return call()
            except Exception as error:
                wait = self._rate_limit_wait(error) if getattr(error, "status_code", None) == 429 else None
                if wait is None or attempt == 2:
                    raise
                if self._on_status:
                    self._on_status(f"Waiting {wait:.0f} seconds for the free plan's per-minute limit...")
                time.sleep(wait)

    def _open_stream(self, client, provider: str, model: str, messages: list, use_tools: bool):
        """Start a streamed request. Some models don't accept every option, so on a
        400 error drop the options one by one (reasoning setting, then tools)."""
        effort = config.PROVIDERS[provider].get("reasoning")
        variants = []
        for with_tools in ((True, False) if use_tools else (False,)):
            for with_effort in ((True, False) if effort else (False,)):
                variants.append((with_effort, with_tools))
        # order: everything, then without reasoning setting, then without tools...
        last_error = None
        for with_effort, with_tools in variants:
            request = dict(
                model=model,
                max_tokens=config.MAX_TOKENS_COMPAT,
                messages=messages,
                stream=True,
            )
            if with_effort:
                request["reasoning_effort"] = effort
            if with_tools:
                request["tools"] = self.tools.openai_tools(self._tool_names)
            try:
                stream = self._wait_if_rate_limited(lambda: client.chat.completions.create(**request))
            except Exception as error:
                if "request.tools" in str(error):
                    raise  # not a model problem: _call_model sends the missing tool and asks again
                if getattr(error, "status_code", None) == 400:
                    last_error = error
                    continue
                raise
            if use_tools and not with_tools:
                self._no_tools.add(provider)  # this model can't use tools; stop trying
                print(f"[atom] {provider} refused the tools, chatting without them: {last_error}", flush=True)
            return stream
        raise last_error

    @staticmethod
    def _explain(error: Exception, provider: str) -> str:
        """Turn a technical error into something a person can act on."""
        label = config.PROVIDERS[provider]["label"]
        status = getattr(error, "status_code", None)
        if status in (401, 403):
            return f"{label} rejected the key. Check it in Settings."
        if status == 404:
            return (
                f"{label} doesn't know the model '{config.get_model(provider)}'. "
                "Change the model name in Settings."
            )
        if status == 413:
            return (
                f"That was too much text for {label} to take at once (free plans allow "
                "only a small amount per minute). This isn't your daily limit. Try again "
                "in a minute, ask about one file at a time, or ask a shorter question."
            )
        if status == 429:
            return (
                f"{label} says I've used up its limit for now. Wait a while "
                "(free plans reset daily) or switch provider in Settings."
            )
        if status in Brain.RETRY_STATUSES:
            return (
                f"{label} is overloaded or down right now (error {status}). I already "
                "tried three times. Try again in a minute, change the model in Settings "
                "(for Gemini try gemini-3.5-flash-lite), or switch provider."
            )
        if type(error).__name__ in ("APIConnectionError", "APITimeoutError", "ConnectError"):
            hint = " Is Ollama running?" if provider == "ollama" else " Check your internet connection."
            return f"I couldn't connect to {label}.{hint}"
        return str(error)[:300]

    # --------------------------------------------------------- offline
    def _offline_reply(self, text: str) -> str:
        words = set(re.findall(r"[a-z']+", text.lower()))
        count = len(self.store)
        if words & {"file", "files", "list", "added", "upload"}:
            if count == 0:
                return (
                    "No files yet. Drop some onto my window and I'll list them.\n\n"
                    + self.status_text
                )
            names = "\n".join(f"• {r.name}" for r in self.store.all())
            return f"I'm tracking {count} file{'s' if count != 1 else ''}:\n{names}"
        if words & {"hi", "hello", "hey"}:
            return (
                "Hi! Drop files onto my window and I'll keep track of them.\n\n"
                + self.status_text
            )
        # try a local search even offline so the user sees something useful
        hits = self.store.search(text, limit=3)
        if hits:
            bits = [f"• {h.name}: {h.text[:120].strip()}…" for h in hits]
            return "I found these bits in your files:\n" + "\n".join(bits)
        return self.status_text

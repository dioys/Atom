"""config.py - every setting for Atom lives here.

Change a value here and the rest of the app follows. Nothing in this file
imports from the other Atom modules, so any module can safely import it.
"""

import json
import os
from pathlib import Path

# ---------------------------------------------------------------- identity
APP_NAME = "Atom"
APP_ID = "Atom.PersonalAssistant"     # Windows taskbar identity (also used by the installer)
PUBLISHER = "Atom"                    # shown in Windows "Installed apps" (change to your own name before publishing)
TAGLINE = "your personal work assistant"

# ------------------------------------------------------------------- paths
# Atom keeps its own data (file list, settings, library) in a hidden folder
# in your home directory, e.g. C:\Users\<you>\.atom on Windows.
DATA_DIR = Path.home() / ".atom"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LIBRARY_DIR = DATA_DIR / "library"   # copies of every uploaded file
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

FILES_DB = DATA_DIR / "atom.db"      # SQLite (files + FTS5 chunks)
SETTINGS_FILE = DATA_DIR / "settings.json"

# ------------------------------------------------------------------- brain
MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1800          # a saved report is written in one go, so leave room
MAX_HISTORY_MESSAGES = 12  # how many past messages Atom remembers per session
MAX_TOKENS_COMPAT = 2000   # reply-size cap. Groq counts it toward its 8,000-per-minute free limit

# ---------------------------------------------------------------- providers
# Atom can think with any of these; pick one in Settings. "base_url" is the
# address Atom talks to (None means Anthropic's own library is used).
PROVIDERS = {
    "gemini": {
        "label": "Google Gemini (free tier)",
        "model": "gemini-3.8-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env": "GEMINI_API_KEY",
        "reasoning": "low",   # think less = answer faster
        # if one model's free allowance runs out, Atom tries these next
        "fallback_models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
        "needs_key": True,
        "key_url": "https://aistudio.google.com/apikey",
        "key_hint": "AIza...",
        "note": (
            "Free tier. Google may use free-tier prompts to improve its products, "
            "so avoid private work files with this one."
        ),
    },
    "groq": {
        "label": "Groq (free plan)",
        "model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "reasoning": "low",   # think less = answer faster
        "fallback_models": ["openai/gpt-oss-20b"],
        "needs_key": True,
        "key_url": "https://console.groq.com/keys",
        "key_hint": "gsk_...",
        "note": "Free plan with daily limits (about 1,000 requests per day on its main models).",
    },
    "ollama": {
        "label": "Ollama (runs on this computer, free)",
        "model": "llama3.2",
        "base_url": "http://localhost:11434/v1",
        "env": "",
        "needs_key": False,
        "key_url": "https://ollama.com/download",
        "key_hint": "(no key needed)",
        "note": (
            "Nothing leaves your computer. Install Ollama, then run: ollama pull llama3.2 "
            "(needs a reasonably powerful PC)."
        ),
    },
    "claude": {
        "label": "Claude (Anthropic, paid)",
        "model": MODEL,
        "base_url": None,
        "env": "ANTHROPIC_API_KEY",
        "needs_key": True,
        "key_url": "https://platform.claude.com/settings/keys",
        "key_hint": "sk-ant-...",
        "note": "Paid with prepaid credits. Max and Team plans include monthly API credits.",
    },
}
DEFAULT_PROVIDER = "groq"

# Atom's character. Edit this to change how he talks.
PERSONALITY = (
    "Your personality: blunt and human. Talk like a sharp friend, not a "
    "customer-service bot: short plain sentences, contractions, no fluff, no "
    "'Great question', no flattery, no apologising for nothing. Give the answer "
    "first, then a reason only if it helps. If the user is wrong or a plan is "
    "bad, say so plainly and say what to do instead. If you don't know or "
    "can't verify something, say 'I'm not sure' or 'I couldn't confirm that' "
    "and never bluff. Blunt is not rude: no insults, and be gentle when the "
    "user is stressed or the news is bad. Dry humour is fine; a joke about "
    "being an atom only now and then. When something fails, say what failed in "
    "a few words, then what to try. Use the user's name occasionally if you "
    "know it, not in every message. You only suggest and never change their "
    "files by yourself. "
    "If the user tells you their name, call remember with 'User's name is X'. "
)

SYSTEM_PROMPT = (
    "You are Atom, a friendly personal work assistant that lives on the user's "
    "desktop. You help them keep track of their work files and what is going "
    "on in their projects. Your answers appear in a small speech bubble, so "
    "keep them short (usually 1-3 sentences), clear and warm, in plain text "
    "with no markdown. " + PERSONALITY +
    "CODE: when the user asks for code, give the simplest beginner-style version that works (plain variables and loops, no clever "
    "tricks, no extra functions, classes or imports unless they are needed), as plain lines with no ``` fences, no comments unless "
    "asked, and at most one short sentence after it. Explain step by step only when the user asks you to explain. "
    "You can search and read the contents of files the user has added. "
    "When relevant file excerpts are provided below, use them to answer. "
    "Cite the source file name when you use information from it. "
    "You also have tools: search_files, list_files, read_file, web_search, table_summary, "
    "make_dashboard, build_powerbi_report, export_powerbi, save_report, open_file, open_app, play_music and music_control. "
    "FACTS: for anything about the outside world (people, places, events, "
    "prices, dates, news, 'is it true that...') or whenever you are not sure, "
    "call web_search BEFORE you answer and base the answer on what it returns; "
    "name the site in a few words, like 'per bbc.com'. If the results contradict "
    "what you thought, go with the results and say you were wrong. If the "
    "search fails or finds nothing, say you couldn't check it. Do not search "
    "for questions about the user's files or numbers, small talk, or things a "
    "tool of yours does. Search with a few plain words and never put file "
    "contents, private file names, passwords or personal details in a search. "
    "For a "
    "status report: call list_files, then table_summary for each Excel or CSV "
    "file and read_file for documents, then call save_report with a clear "
    "report (headings: Summary, Key numbers, Problems and overdue items, "
    "Suggested next steps), then tell the user the 2 or 3 most important "
    "points in one or two sentences. For questions about numbers (totals, "
    "averages, comparing years or groups, trends) use data_aggregate or "
    "data_stats; for a pivot table or cross-tab use data_pivot; for growth, trends or a forecast use data_trend; "
    "for how one column affects another use data_relate; to compare two files or sheets use data_compare; "
    "to put two files together use data_join; to find messy data or typos use data_cleanup; "
    "for reminders ('remind me ... at ...') use reminder, with 'when' in the user's own words; "
    "for a to-do list use todo; for 'what's on today' use briefing; only say a reminder is set or an item "
    "is added if the tool said so, and repeat the time the tool reports; "
    "to see what is on the user's screen use read_screen, and focus on the one problem or question they mean (ignore browser tabs, "
    "menus and ads); to organise files into folders use organize_files (folders: Work, Reports, About me, or their own); for the user's own skills, experience and CV files use "
    "profile (add, remove, show, or use a file as the profile); for what someone asked the user to do on a call "
    "or interview, or a call summary, use call_notes; "
    "to draw a graph use make_chart; for a one-page overview or dashboard use "
    "make_dashboard (leave kpis and charts empty unless the user names them); to "
    "make a report in Microsoft Power BI call build_powerbi_report (it designs the whole "
    "report and opens it in Power BI Desktop by itself; use export_powerbi only when the user "
    "wants just the plain files); open_app can start Power BI on its own; call table_summary first if "
    "you don't know the column names. Use only numbers that come from tool "
    "results; never invent figures. Use a tool when the excerpts "
    "below are not enough, or when the user asks you to open a file or an app "
    "or to play, pause or skip music (just call the tool; do not ask for "
    "permission in words). "
    "For play_music choose kind: artist for a singer or band, track for a "
    "song, playlist for moods like 'lofi' or 'workout', album for an album. "
    "For one specific song put only the title in query and the singer in "
    "artist, e.g. query 'ilomilo', artist 'Billie Eilish', kind track. "
    "You remember things between sessions: when the user asks you to "
    "remember something, or tells you a lasting fact such as a project, a "
    "deadline or a preference, call remember (short note, kind fact, "
    "preference, project or deadline with the date). Call forget when asked "
    "to forget, and recall to look up something said earlier. Never save "
    "passwords or card numbers, and only say something is saved if the "
    "tool said 'Saved'. "
    "Only say music is playing if the tool result says 'Now playing'; if it "
    "says the user must press play, tell them to. After using a tool, tell "
    "the user briefly what you found or did. Never claim to have done "
    "something unless the tool said it was done."
)

# ------------------------------------------------------------------- tools
WEB_SEARCH = True          # Atom may check facts on the internet (only the search words leave your computer)
CONFIRM_ACTIONS = False    # True = ask Yes/No before Atom opens a file or an app
ALWAYS_ON_TOP = True       # Atom stays in front of other windows (the Pin button changes it)
CONFIRM_MUSIC = False      # True = also ask Yes/No before Atom starts playing music
MAX_TOOL_ROUNDS = 8        # how many times Atom may use tools for one question
REPORTS_DIR = DATA_DIR / "reports"   # where status reports (.docx) are saved
CHARTS_DIR = DATA_DIR / "charts"     # where charts (.png) are saved
CHART_THEME = "dark"       # how charts look: "dark" (jester colours) or "light"
POWERBI_DIR = DATA_DIR / "powerbi"   # where "export for Power BI" puts its files

# ------------------------------------------------------------------ look
THEME = "plate"                # "plate" = dark chat plate with a portrait, outline and a tail pointing at him (like Capri);
                               # "hud" = framed sci-fi panels; "classic" = the original floating bubbles
PLATE = {                      # colors of the "plate" look, taken from the jester
    "ink": "#0e0a0b",          # the plate itself (warm near-black)
    "ink2": "#1d1517",         # input box, barcode
    "paper": "#fff4ec",        # main text
    "paper2": "#d8c3c3",       # quoted text
    "paper3": "#8f7a7e",       # quiet labels
    "crimson": "#d81e3c",      # his hat
    "gold": "#e4cc54",         # his hair
    "red": "#ff4b3a",          # alerts
}
PLATE_CHARACTER_HEIGHT = 170   # his height in the plate look (he has no box around him there)
HUD = {                        # colors taken from the jester: crimson hat, gold hair, near-black outfit
    "bg": "#12060b",
    "panel": "#16080d",        # inside the chat box
    "line": "#d81e3c",         # bright crimson frame lines
    "line_dim": "#8a1428",     # quieter crimson lines
    "text": "#fff4ec",         # warm white
    "muted": "#c4a2a8",
    "accent": "#e4cc54",       # gold (his hair): Atom's name, the input bar, name tab
}
HUD_WINDOW_SIZE = (420, 680)   # the window itself is see-through; only the boxes are solid
HUD_BUBBLE_MAX = (392, 240)    # chat box (max width, max height); longer text scrolls
HUD_CHARACTER_HEIGHT = 150     # how tall he is in the HUD look (smaller = smaller box)

# --------------------------------------------------------------- character
CHARACTER = "jester"           # a folder in 'characters': "jester" or "orb"
GREETING = True                # say a hello (with the time of day) when Atom starts (unless KEEP_LAST_CHAT shows your last chat)
KEEP_LAST_CHAT = True          # his last answer stays in the chat box: idle remarks, wake-up lines, suggestions and the morning
                               # briefing never write over it (they become a pop-up or wait), and it is still there after a restart
IDLE_BEHAVIOR = True           # Atom glances around, talks a little and falls asleep when you're away
IDLE_LOOK_SECONDS = 25         # after this much quiet he starts glancing around
IDLE_CHATTER = True            # a short remark now and then (tips, fun facts)
IDLE_CHATTER_SECONDS = 300     # at most one remark this often
IDLE_SLEEP_SECONDS = 600       # he falls asleep after this long (0 = never)

# ------------------------------------------------------------------ memory
MEMORY = True                          # Atom remembers your chats and notes between sessions
MEMORY_DB = DATA_DIR / "memory.db"     # saved on this computer only
RESTORE_MESSAGES = 6                   # how many recent messages he reloads when he starts
MAX_MEMORY_CHARS = 900                 # how much of your notes go into each question
MAX_SAVED_MESSAGES = 400               # older chat messages are deleted past this

# ------------------------------------------------------------- suggestions
SUGGESTIONS = True                  # Atom speaks up about changed files and overdue work
SUGGESTION_EVERY_SECONDS = 120      # how often he looks
SUGGESTION_IDLE_SECONDS = 20        # he stays quiet for this long after you last talked to him
WATCH_FILES = True                  # notice a saved file within seconds (needs the watchdog package)
WATCH_DELAY_SECONDS = 2.0           # wait this long after the last save so a burst counts once
DUE_SOON_DAYS = 7                   # warn about open items due within this many days
TRAY_NOTIFICATIONS = True           # pop up a notification when Atom is hidden in the tray
MAX_READ_CHARS = 4000      # how much of a file read_file hands to the AI

# ----------------------------------------------------------------- spotify
SPOTIFY_REDIRECT_PORT = 8888   # must match the Redirect URI in your Spotify app
SPOTIFY_SCOPES = "user-modify-playback-state user-read-playback-state"
SPOTIFY_TOKEN_FILE = DATA_DIR / "spotify.json"   # your Spotify login (keep private)

# ---------------------------------------------------------------- file list
MAX_FILES = 500            # safety cap on how many files Atom will track
MAX_FILES_PER_FOLDER = 200  # when a folder is dropped, add at most this many

# ------------------------------------------------------------------- voice
SPEECH_LANGUAGE = "en-US"    # default language you speak (change it in Settings)
SPEECH_ENGINE = "auto"       # "auto": Whisper (Groq) when you have a Groq key, otherwise Google. Or "google".
WHISPER_MODEL = "whisper-large-v3-turbo"   # fast and accurate; "whisper-large-v3" is a bit more careful
WHISPER_PROMPT = "Atom, Spotify, Excel, Word, PowerPoint, open, play, chart, report, remember, spreadsheet."
SAMPLE_RATE = 16000          # audio quality sent to speech recognition
SILENCE_LEVEL = 0.02         # loudness (0-1) below which counts as silence
SILENCE_SECONDS = 1.4        # stop listening after this much quiet
MAX_RECORD_SECONDS = 30      # hard limit for one spoken message
NO_SPEECH_SECONDS = 8        # give up if nothing is said for this long

# -------------------------------------------------------------- hotkey
HOTKEY = "ctrl+alt+space"      # press anywhere to bring Atom to the front ("" = off). e.g. "ctrl+shift+a", "win+f9"
HOTKEY_LISTENS = True          # ...and start listening right away (press again to stop)

# ------------------------------------------------------------ daily helper
DAILY = True                   # reminders, a to-do list and a morning briefing
DAILY_DB = DATA_DIR / "daily.db"
REMINDER_CHECK_SECONDS = 15    # how often Atom looks at the clock for a reminder
MORNING_BRIEFING = True        # once a day, the first time Atom starts: reminders, to-do list, overdue work
BRIEFING_FROM_HOUR = 5         # not before this hour (so a 2 a.m. start doesn't use up today's briefing)

# ------------------------------------------------------------ call helper (Step 13)
PROFILE = True                         # your skills and the files that describe you (userprofile.py)
PROFILE_DB = DATA_DIR / "profile.db"
CALL_HELPER = True                     # listen to a call, read the screen, suggest answers, list what was asked of you
CALL_DB = DATA_DIR / "calls.db"        # transcripts and to-dos from calls, saved on this computer only
CALL_SPEECH_LEVEL = 0.008              # loudness (0-1) of the call audio that counts as someone talking
CALL_PAUSE_SECONDS = 0.9               # a pause this long ends one sentence of the call
CALL_MAX_UTTERANCE = 20.0              # seconds: cut very long talking into pieces
CALL_SILENCE_WARNING = 25              # seconds of total silence before Atom says he can't hear the call
CALL_HEAR_ME = False                   # also listen to your own microphone (use headphones, or the speakers' sound is heard twice)
CALL_AUTO_ANSWER = True                # suggest an answer by himself whenever the other person asks something
CALL_VISION = False                    # read the screen with an AI that SEES it (sends the picture online); False = text only, on this PC
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"   # Groq model that can look at a picture (used when CALL_VISION is on)
SCREEN_MAX_CHARS = 3500                # how much screen text is kept

# ---------------------------------------------------------- spoken answers
SPEAK_REPLIES = False          # start with the speaker button on? (the button remembers your choice)
SPEAK_AFTER_VOICE = True       # when you TALK to Atom, he answers out loud even if the button is off
SPEAK_MAX_CHARS = 350          # long answers are read only up to about this much
SPEECH_RATE = 0.0              # -1.0 slow ... 0 normal ... 1.0 fast
SPEECH_VOLUME = 0.9
SPEECH_PITCH = 0.0              # voice pitch, -1.0 (deep) to 1.0 (high); choose the voice itself in Settings
VOICE_MODE = "boy"             # "boy" = a young robot-boy voice made on this PC (needs kokovoice.py set-up), "robot" = electric words, "babble" = cute blips (like Capri), "windows" = a plain Windows voice
BOY_VOICE = "am_puck"          # the voice underneath: am_puck, am_liam, am_eric, am_echo or am_adam (choose in Settings)
BOY_AGE = "teen"               # boy, teen or natural: how young he sounds (choose in Settings)
AI_VOICE = "troy"              # the Groq voice (only used by mode "ai", which Settings no longer offers)
ROBOT_STYLE = "electric"       # electric, robot or radio (choose in Settings)
BABBLE_STYLE = "soft"          # soft, retro, bubbly or deep (choose in Settings)

# ----------------------------------------------------------- extraction
CHUNK_SIZE = 1200          # characters per chunk (roughly 200-300 tokens)
CHUNK_OVERLAP = 150        # overlap so sentences at boundaries aren't lost
MAX_EXTRACT_CHARS = 500_000  # hard cap per file so huge files don't blow up
MAX_SEARCH_HITS = 4        # how many chunks to inject into the prompt
MAX_CONTEXT_CHARS = 3000   # total characters of file excerpts sent with each question

# ------------------------------------------------------------------ window
WINDOW_SIZE = (420, 620)   # Atom is a small, fixed-size, see-through window
SCREEN_MARGIN = 24          # gap from the screen corner when Atom first appears
ATOM_BUBBLE_MAX = (340, 190)  # (max width, max height) of Atom's speech bubble
USER_BUBBLE_MAX = (290, 90)   # same for your bubble; longer text scrolls

COLORS = {
    "bg": "#14161c",
    "panel": "#1b1e26",
    "panel_alt": "#232733",
    "border": "#2c3140",
    "text": "#e7e9ee",
    "muted": "#8b91a3",
    "accent": "#5b8cff",
    "accent_hover": "#7aa2ff",
    "user_bubble": "#3a62d6",
    "atom_bubble": "#262b38",
    "danger": "#e5675f",
}


# ---------------------------------------------------------------- settings
def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_speech_language() -> str:
    return load_settings().get("speech_language") or SPEECH_LANGUAGE


def get_provider() -> str:
    """Which AI provider Atom uses. Defaults to Gemini's free tier, unless you
    already have a Claude key saved from an older version."""
    chosen = load_settings().get("provider")
    if chosen in PROVIDERS:
        return chosen
    return "claude" if get_api_key("claude") else DEFAULT_PROVIDER


def key_from_env(provider: str) -> bool:
    """True if this provider's key comes from an environment variable."""
    env = PROVIDERS[provider]["env"]
    return bool(env and os.environ.get(env))


def get_api_key(provider: str | None = None) -> str:
    """Return the API key for a provider, or "" if none is set.

    Order: the provider's environment variable (e.g. GEMINI_API_KEY) first,
    then the key saved in ~/.atom/settings.json.
    """
    provider = provider or get_provider()
    env = PROVIDERS[provider]["env"]
    if env and os.environ.get(env):
        return os.environ[env]
    settings = load_settings()
    stored = (settings.get("keys") or {}).get(provider, "")
    if provider == "claude":
        stored = stored or settings.get("api_key", "")  # saved by older versions
    return stored


def get_model(provider: str | None = None) -> str:
    """The model name for a provider (your override from Settings, or the default)."""
    provider = provider or get_provider()
    override = (load_settings().get("models") or {}).get(provider, "")
    return override or PROVIDERS[provider]["model"]

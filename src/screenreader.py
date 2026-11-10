"""screenreader.py - Step 13: lets Atom read what is on your screen.

    read_screen()   takes a picture of the screen and returns the words in it

By default the reading is done on this computer (OCR with Tesseract) and the picture goes nowhere. If you turn on
CALL_VISION in config.py, the picture is instead sent to Groq's picture-reading AI, which also understands charts
and images. Nothing is saved; the picture is thrown away after reading.

Needs:  python -m pip install Pillow pytesseract   and the Tesseract program
        (Windows installer: https://github.com/UB-Mannheim/tesseract/wiki). Run  python screenreader.py  to test.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import time
from dataclasses import dataclass

import config

_TESSERACT_PLACES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
)


@dataclass
class ScreenResult:
    text: str = ""
    method: str = "ocr"        # 'ocr' or 'vision'
    error: str = ""            # a message safe to show you; empty when it worked

    @property
    def ok(self) -> bool:
        return not self.error


def clean_text(text: str, limit: int | None = None) -> str:
    """Tidy OCR output: drop empty and junk lines, collapse repeats, keep the first `limit` characters."""
    limit = limit or config.SCREEN_MAX_CHARS
    lines, last = [], ""
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(re.findall(r"[A-Za-z0-9]", line)) < 3 or line == last:
            continue
        lines.append(line)
        last = line
    return "\n".join(lines)[:limit]


def grab_screen():
    """A picture of the whole screen (all monitors). Raises ImportError / OSError."""
    from PIL import ImageGrab
    return ImageGrab.grab(all_screens=True)


def _setup_tesseract(pytesseract) -> None:
    """Point pytesseract at the program when Windows did not put it on the PATH."""
    if shutil.which("tesseract"):
        return
    for place in _TESSERACT_PLACES:
        if place and os.path.isfile(place):
            pytesseract.pytesseract.tesseract_cmd = place
            return


def ocr_image(image) -> str:
    """The words in a picture, read on this computer."""
    import pytesseract
    _setup_tesseract(pytesseract)
    picture = image.convert("L")
    if picture.width > 2400:                                       # big screens: smaller is faster and just as readable
        picture = picture.resize((2400, int(picture.height * 2400 / picture.width)))
    return pytesseract.image_to_string(picture) or ""


def describe_with_ai(image) -> str:
    """The text and pictures on screen, read by Groq's picture AI (the picture is sent online)."""
    import base64

    import openai
    key = config.get_api_key("groq")
    if not key:
        raise RuntimeError("Reading the screen with AI needs a Groq key. Add one in Settings.")
    picture = image.convert("RGB")
    picture.thumbnail((1600, 1600))
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=70)
    url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    client = openai.OpenAI(api_key=key, base_url=config.PROVIDERS["groq"]["base_url"], timeout=40)
    reply = client.chat.completions.create(
        model=config.VISION_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Read this screenshot. Write the text that matters in reading order (questions, code, chat messages, "
                                     "slides, tables). Then add one line starting 'Picture:' that describes any chart or image. No commentary."},
            {"type": "image_url", "image_url": {"url": url}},
        ]}],
    )
    return reply.choices[0].message.content or ""


def _explain(error: Exception) -> str:
    name = type(error).__name__
    if isinstance(error, ImportError):
        missing = getattr(error, "name", "") or "Pillow or pytesseract"
        return f"Reading the screen needs {missing}. Run: python -m pip install Pillow pytesseract"
    if name == "TesseractNotFoundError" or "tesseract is not installed" in str(error).lower():
        return ("I need the Tesseract program to read the screen. Install it (Windows: "
                "https://github.com/UB-Mannheim/tesseract/wiki), then restart me.")
    return f"I couldn't read the screen ({name}: {error})"


def read_screen(before=None, after=None, vision: bool | None = None, grab=None, ocr=None, describe=None, image=None) -> ScreenResult:
    """Take a picture of the screen and read it.

    before() / after()   called around the picture, so Atom can hide his own windows for a moment
    vision               True = use the picture AI (default: config.CALL_VISION)
    image                a picture you already have (the part of the screen you picked): nothing is grabbed
    grab / ocr / describe  replace the real thing (used by tests)
    """
    vision = config.CALL_VISION if vision is None else vision
    if image is not None:
        before = after = None
        grab = lambda: image
    try:
        if before:
            before()
            time.sleep(0.15)                                           # let his windows disappear before the picture
        try:
            image = (grab or grab_screen)()
        finally:
            if after:
                after()
    except Exception as error:
        return ScreenResult(error=_explain(error))
    if vision:
        try:
            text = clean_text((describe or describe_with_ai)(image))
            if text:
                return ScreenResult(text, "vision")
        except Exception as error:
            print(f"[atom] screen vision failed, reading the text instead: {error}", flush=True)
    try:
        text = clean_text((ocr or ocr_image)(image))
    except Exception as error:
        return ScreenResult(error=_explain(error))
    if not text:
        return ScreenResult(error="I looked, but found no readable text on the screen.")
    return ScreenResult(text, "ocr")


if __name__ == "__main__":
    print("Taking a picture of your screen in 3 seconds...")
    time.sleep(3)
    result = read_screen()
    if result.ok:
        print(f"Read it with {result.method}. The first lines:\n")
        print(result.text[:800])
    else:
        print(result.error)

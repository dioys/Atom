import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys
sys.path.insert(0, SRC)
import config, screenreader as sr

assert sr.clean_text("Hello   world\n\n\n--\n!!\nHello   world\nHello   world\nQuestion 1: what is a join?\n  ") == "Hello world\nQuestion 1: what is a join?"
assert len(sr.clean_text("word " * 5000, 100)) == 100
order = []
r = sr.read_screen(before=lambda: order.append("hide"), after=lambda: order.append("show"), grab=lambda: order.append("grab") or "IMG", ocr=lambda img: "Q: Reverse a linked list\nSome code here")
assert r.ok and r.method == "ocr" and "Reverse a linked list" in r.text and order == ["hide", "grab", "show"], (r, order)
# the windows come back even if the picture fails
order.clear()
def bad(): order.append("grab"); raise OSError("no display")
r = sr.read_screen(before=lambda: order.append("hide"), after=lambda: order.append("show"), grab=bad)
assert not r.ok and "couldn't read the screen" in r.error and order == ["hide", "grab", "show"]
r = sr.read_screen(grab=lambda: "IMG", ocr=lambda img: "   \n -- \n")
assert not r.ok and "no readable text" in r.error
def no_tess(img):
    class TesseractNotFoundError(Exception): pass
    raise TesseractNotFoundError("tesseract is not installed or it's not in your PATH")
r = sr.read_screen(grab=lambda: "IMG", ocr=no_tess); assert "Tesseract program" in r.error
def no_pil(): raise ImportError("No module named 'PIL'", name="PIL")
r = sr.read_screen(grab=no_pil); assert "pip install Pillow pytesseract" in r.error
# vision: used when asked; falls back to OCR when it fails
r = sr.read_screen(vision=True, grab=lambda: "IMG", describe=lambda img: "Slide: Q3 sales\nPicture: bar chart", ocr=lambda img: "ocr text here")
assert r.method == "vision" and "bar chart" in r.text
def broken(img): raise RuntimeError("model gone")
r = sr.read_screen(vision=True, grab=lambda: "IMG", describe=broken, ocr=lambda img: "ocr text here"); assert r.method == "ocr" and r.ok
assert config.CALL_VISION is False                       # off unless you turn it on: the picture would be sent online
print("SCREENREADER OK")

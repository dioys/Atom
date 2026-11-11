"""build_exe.py - Step 8: turn Atom into a normal Windows program (Atom.exe).

Run it from the repo folder, with the (.venv) active:

    python -m pip install pyinstaller
    python scripts/build_exe.py                # a folder:  dist\\Atom\\Atom.exe  (starts fast, recommended)
    python scripts/build_exe.py --onefile      # one single Atom.exe (slower to start: it unpacks itself each time)
    python scripts/build_exe.py --shortcut     # also puts an Atom shortcut on your Desktop

Your settings, files, memory and Spotify login live in C:\\Users\\<you>\\.atom,
not inside the program, so building a new Atom.exe never loses them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # the repo folder
SRC = HERE / "src"                                    # Atom's code
sys.path.insert(0, str(SRC))
BUILD_DIR = HERE / "build_files"          # PyInstaller's scratch space
ICON = BUILD_DIR / "atom.ico"

# parts of big packages Atom never uses: leaving them out keeps the program smaller
EXCLUDES = [
    "tkinter", "IPython", "pytest", "scipy", "notebook", "jupyter",
    "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_wxagg",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
]

# modules Atom loads by name or inside try/except, which PyInstaller can miss
HIDDEN = [
    "PySide6.QtTextToSpeech", "PySide6.QtMultimedia", "PySide6.QtNetwork",
    "openai", "anthropic", "pytesseract", "speech_recognition",
    "docx", "pptx", "pypdf", "openpyxl", "pandas", "matplotlib.figure", "matplotlib.ticker",
    "watchdog.observers", "PIL",
    "soundcard", "ddgs", "kokoro_onnx", "numpy", "pywinauto",
]


def qt_plugin_data() -> list[str]:
    """--add-data entries for the Qt plugins that make Atom's voice work."""
    try:
        import PySide6
    except ImportError:
        return []
    plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
    sep = os.pathsep  # ';' on Windows
    return [
        f"{plugins / name}{sep}PySide6/Qt/plugins/{name}"
        for name in ("texttospeech", "multimedia")
        if (plugins / name).is_dir()
    ]


def character_data() -> list[str]:
    """--add-data entries so Atom.exe carries his character pictures (not the raw sheets)."""
    sep = os.pathsep
    folder = SRC / "characters"
    if not folder.is_dir():
        return []
    return [
        f"{pack}{sep}characters/{pack.name}"
        for pack in sorted(folder.iterdir())
        if pack.is_dir() and (pack / "character.json").exists()
    ]


def version_file() -> Path:
    """A Windows 'Details' tab for Atom.exe (name, version, publisher), made from version.py and config.py."""
    import config
    import version

    a, b, c = (version.as_tuple(version.VERSION) + (0, 0, 0))[:3]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{config.PUBLISHER}'),
      StringStruct('FileDescription', '{config.APP_NAME} - personal assistant'),
      StringStruct('FileVersion', '{version.VERSION}'),
      StringStruct('InternalName', '{config.APP_NAME}'),
      StringStruct('OriginalFilename', '{config.APP_NAME}.exe'),
      StringStruct('ProductName', '{config.APP_NAME}'),
      StringStruct('ProductVersion', '{version.VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    path = BUILD_DIR / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build_command(onefile: bool = False, icon: Path | None = None, extra_data: list[str] | None = None,
                  version_info: Path | None = None) -> list[str]:
    """The PyInstaller command line (kept separate so it can be checked without building)."""
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",                      # no black console window
        "--name", "Atom",
        "--distpath", str(HERE / "dist"),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        "--onefile" if onefile else "--onedir",
    ]
    if icon and Path(icon).exists():
        command += ["--icon", str(icon)]
    if version_info and Path(version_info).exists():
        command += ["--version-file", str(version_info)]
    for name in EXCLUDES:
        command += ["--exclude-module", name]
    for name in HIDDEN:
        command += ["--hidden-import", name]
    for data in extra_data or []:
        command += ["--add-data", data]
    command += ["--collect-data", "speech_recognition", "--collect-data", "docx", "--collect-data", "pptx"]
    command.append(str(SRC / "main.py"))
    return command


def make_icon() -> Path | None:
    """Draw Atom's tray icon to a Windows .ico file."""
    try:
        from PySide6.QtWidgets import QApplication

        from PIL import Image
        from ui import make_icon as atom_icon

        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        app = QApplication.instance() or QApplication([])
        png = BUILD_DIR / "atom.png"
        atom_icon().pixmap(256, 256).save(str(png))
        Image.open(png).save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        del app
        return ICON
    except Exception as error:  # a missing icon is not worth stopping for
        print(f"(no custom icon: {error})")
        return None


def desktop_shortcut(target: Path) -> bool:
    """Put 'Atom' on the Desktop, pointing at the built program."""
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
        "[Environment]::GetFolderPath('Desktop')+'\\Atom.lnk');"
        f"$s.TargetPath='{target}';$s.WorkingDirectory='{target.parent}';$s.Save()"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Atom.exe")
    parser.add_argument("--onefile", action="store_true", help="make one single .exe (slower to start)")
    parser.add_argument("--shortcut", action="store_true", help="add an Atom shortcut to the Desktop")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Note: this builds a program for the computer it runs on. Run it on your Windows PC.")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing. Run:  python -m pip install pyinstaller")
        return 1

    print("Drawing Atom's icon...")
    icon = make_icon()
    print("Building Atom (this takes a few minutes the first time)...")
    code = subprocess.call(build_command(args.onefile, icon, qt_plugin_data() + character_data(), version_file()), cwd=HERE)
    if code != 0:
        print("\nThe build failed. Scroll up for the first red error and send it to me.")
        return code

    exe = HERE / "dist" / ("Atom.exe" if args.onefile else "Atom/Atom.exe")
    print(f"\nDone! Your program is here:\n  {exe}")
    if args.shortcut and desktop_shortcut(exe):
        print("A shortcut named Atom is now on your Desktop.")
    print("Tip: open Atom > Settings and tick 'Start Atom when I sign in to Windows'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""make_shortcut.py - put an "Atom" icon on your Desktop (and in the Start menu) that runs Atom from these files.

Why this and not Atom.exe? A built Atom.exe is a frozen COPY: after every update it still runs the OLD code until you
rebuild it. This shortcut starts the files in this folder, so it always runs the newest code you copied in.
Double-click it after an update: if an older Atom is still running he closes himself and the new one starts.

Run it once, from the Atom folder, with the (.venv) active:

    python make_shortcut.py             # Desktop + Start menu (right-click it there > Pin to taskbar)
    python make_shortcut.py --desktop   # Desktop only
    python make_shortcut.py --remove    # take them away again
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICON = HERE / "atom.ico"
NAME = "Atom"


def windowless_python() -> Path:
    """pythonw.exe (runs without a black console window) from the same Python that is running this."""
    python = Path(sys.executable)
    candidate = python.with_name("pythonw.exe")
    return candidate if candidate.exists() else python


def make_icon() -> Path | None:
    """Draw Atom's icon to atom.ico next to main.py (once)."""
    if ICON.exists():
        return ICON
    try:
        from PIL import Image
        from PySide6.QtWidgets import QApplication

        from ui import make_icon as atom_icon

        app = QApplication.instance() or QApplication([])
        png = HERE / "atom_icon.png"
        atom_icon().pixmap(256, 256).save(str(png))
        Image.open(png).save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        png.unlink(missing_ok=True)
        del app
        return ICON
    except Exception as error:      # a plain icon is fine; don't stop for it
        print(f"(no custom icon: {error})")
        return None


def _quote(text: object) -> str:
    """Safe inside a PowerShell single-quoted string."""
    return str(text).replace("'", "''")


def shortcut_script(folders: list[str], target: Path, icon: Path | None, remove: bool = False) -> str:
    """The PowerShell that creates (or deletes) the shortcut in each folder: 'Desktop', 'Programs' (Start menu)."""
    lines = ["$sh = New-Object -ComObject WScript.Shell"]
    for folder in folders:
        path = f"[Environment]::GetFolderPath('{folder}') + '\\{NAME}.lnk'"
        if remove:
            lines.append(f"$p = {path}; if (Test-Path $p) {{ Remove-Item $p; Write-Output ('removed ' + $p) }}")
            continue
        lines += [
            f"$p = {path}",
            "$s = $sh.CreateShortcut($p)",
            f"$s.TargetPath = '{_quote(target)}'",
            f"$s.Arguments = '\"{_quote(HERE / 'main.py')}\"'",
            f"$s.WorkingDirectory = '{_quote(HERE)}'",
            "$s.Description = 'Atom - your personal work assistant'",
        ]
        if icon:
            lines.append(f"$s.IconLocation = '{_quote(icon)}'")
        lines += ["$s.Save()", "Write-Output ('made ' + $p)"]
    return "; ".join(lines)


def run_powershell(script: str) -> tuple[bool, str]:
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def main(argv: list[str] | None = None, run=run_powershell) -> int:
    parser = argparse.ArgumentParser(description="Put Atom on the Desktop and Start menu")
    parser.add_argument("--desktop", action="store_true", help="Desktop only")
    parser.add_argument("--remove", action="store_true", help="remove the shortcuts")
    args = parser.parse_args(argv)
    if sys.platform != "win32" and run is run_powershell:
        print("This makes a Windows shortcut, so run it on your Windows PC.")
        return 1
    folders = ["Desktop"] if args.desktop else ["Desktop", "Programs"]
    python = windowless_python()
    if not args.remove and ".venv" not in str(python).lower() and "venv" not in str(python).lower():
        print(f"Note: this uses  {python}\n"
              "If Atom's add-ons (PySide6 and the rest) live in your .venv, activate it first and run this again.")
    icon = None if args.remove else make_icon()
    ok, output = run(shortcut_script(folders, python, icon, args.remove))
    print(output)
    if not ok:
        print("That didn't work. Copy the message above and send it to me.")
        return 1
    if not args.remove:
        print("\nDone. Double-click Atom on your Desktop. After each update just double-click it again:\n"
              "an older Atom closes by itself and the new one starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

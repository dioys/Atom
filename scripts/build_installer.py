"""build_installer.py - turn the built Atom program into something you can hand to anyone.

Run it AFTER  python scripts/build_exe.py  (it needs dist\\Atom\\Atom.exe):

    python scripts/build_installer.py    # makes  release\\Atom-Setup-<version>.exe  and  release\\Atom-<version>-portable.zip
    python scripts/build_installer.py --zip      # only the portable zip (no Inno Setup needed)

* Atom-Setup-x.y.z.exe  - a normal Windows installer: installs for the current user (no administrator
  needed), adds Start menu + Desktop shortcuts, an uninstaller, and an option to start Atom with Windows.
  Making it needs the free "Inno Setup" program (https://jrsoftware.org/isinfo.php).
* Atom-x.y.z-portable.zip - unzip it on ANY PC (or a USB stick) and run Atom\\Atom.exe. Nothing to install.

Your settings, files and memory live in C:\\Users\\<you>\\.atom on each PC, never inside the program,
so installing, updating or uninstalling Atom does not touch them.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import config
import version

HERE = Path(__file__).resolve().parent.parent      # the repo folder
sys.path.insert(0, str(HERE / "src"))
DIST = HERE / "dist" / "Atom"
RELEASE = HERE / "release"
ISS = HERE / "build_files" / "atom.iss"
ICON = HERE / "build_files" / "atom.ico"

INNO_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe",
]


def inno_script(dist: Path = DIST, out: Path = RELEASE, icon: Path | None = None) -> str:
    """The Inno Setup recipe for the installer (kept separate so it can be checked without Inno Setup)."""
    icon_line = f"SetupIconFile={icon}\n" if icon and Path(icon).exists() else ""
    run_value = '"""{app}\\' + config.APP_NAME + '.exe"" --startup"'   # Inno Setup spells a quote inside quotes as ""
    return f"""; made by build_installer.py - do not edit by hand, run the script again instead
[Setup]
AppId={config.APP_ID}
AppName={config.APP_NAME}
AppVersion={version.VERSION}
AppPublisher={config.PUBLISHER}
DefaultDirName={{autopf}}\\{config.APP_NAME}
DefaultGroupName={config.APP_NAME}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={out}
OutputBaseFilename={config.APP_NAME}-Setup-{version.VERSION}
{icon_line}UninstallDisplayIcon={{app}}\\{config.APP_NAME}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put an {config.APP_NAME} icon on the Desktop"; Flags: checkedonce
Name: "startup"; Description: "Start {config.APP_NAME} when I sign in to Windows"; Flags: unchecked

[Files]
Source: "{dist}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{{group}}\\{config.APP_NAME}"; Filename: "{{app}}\\{config.APP_NAME}.exe"; AppUserModelID: "{config.APP_ID}"
Name: "{{autodesktop}}\\{config.APP_NAME}"; Filename: "{{app}}\\{config.APP_NAME}.exe"; Tasks: desktopicon; AppUserModelID: "{config.APP_ID}"

[Registry]
Root: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueType: string; ValueName: "{config.APP_NAME}"; ValueData: {run_value}; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{{app}}\\{config.APP_NAME}.exe"; Description: "Start {config.APP_NAME} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{{sys}}\\taskkill.exe"; Parameters: "/F /IM {config.APP_NAME}.exe"; Flags: runhidden; RunOnceId: "StopAtom"
"""


def make_zip(dist: Path = DIST, out: Path = RELEASE) -> Path:
    """The portable copy: one folder you can unzip anywhere."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{config.APP_NAME}-{version.VERSION}-portable.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                z.write(path, Path(config.APP_NAME) / path.relative_to(dist))
        for note in ("PRIVACY.md", "LICENSE"):
            if (HERE / note).exists():
                z.write(HERE / note, Path(config.APP_NAME) / note)
    return target


def find_inno() -> str | None:
    import os

    found = shutil.which("ISCC")
    if found:
        return found
    for candidate in INNO_PATHS:
        path = os.path.expandvars(candidate)
        if Path(path).exists():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Make the Atom installer and portable zip")
    parser.add_argument("--zip", action="store_true", help="only make the portable zip")
    args = parser.parse_args()

    if not (DIST / f"{config.APP_NAME}.exe").exists():
        print("I can't find dist\\Atom\\Atom.exe. Run  python scripts/build_exe.py  first (not --onefile).")
        return 1
    RELEASE.mkdir(exist_ok=True)

    print(f"Portable zip: {make_zip()}")
    if args.zip:
        return 0

    inno = find_inno()
    if not inno:
        print("\nThe installer needs the free Inno Setup program: https://jrsoftware.org/isdl.php\n"
              "Install it, then run this again. (The portable zip above already works on its own.)")
        return 0
    ISS.parent.mkdir(exist_ok=True)
    ISS.write_text(inno_script(icon=ICON), encoding="utf-8")
    code = subprocess.call([inno, str(ISS)])
    if code != 0:
        print("Inno Setup reported an error. Scroll up for the first red line and send it to me.")
        return code
    print(f"Installer: {RELEASE / (config.APP_NAME + '-Setup-' + version.VERSION + '.exe')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

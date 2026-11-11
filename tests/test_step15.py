import os as _os, sys as _sys
SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
ROOT_DIR = _os.path.dirname(SRC)
SCRIPTS = _os.path.join(ROOT_DIR, "scripts")
import sys, zipfile, tempfile
from pathlib import Path
sys.path.insert(0, SRC); sys.path.insert(0, SCRIPTS)
import build_installer as bi, build_exe, config, version, make_manifest

# installer recipe has the key lines and no leftover braces from f-string mistakes
t = bi.inno_script()
for need in ("AppName=Atom", f"AppVersion={version.VERSION}", "PrivilegesRequired=lowest",
             "[Tasks]", "startup", "--startup", "[UninstallRun]", f"AppId={config.APP_ID}"):
    assert need in t, need
assert "{config" not in t and "{{" not in t
assert 'ValueData: """{app}\\Atom.exe"" --startup"' in t

# portable zip keeps the Atom/ folder layout
with tempfile.TemporaryDirectory() as d:
    d = Path(d); dist = d / "dist"; (dist / "sub").mkdir(parents=True)
    (dist / "Atom.exe").write_bytes(b"x"); (dist / "sub" / "a.dll").write_bytes(b"y")
    z = bi.make_zip(dist, d / "rel")
    names = zipfile.ZipFile(z).namelist()
    assert "Atom/Atom.exe" in names and "Atom/sub/a.dll" in names, names
    assert z.name == f"Atom-{version.VERSION}-portable.zip"

# exe build: version file + hidden imports + no pixel leftovers
vf = build_exe.version_file()
txt = vf.read_text()
assert version.VERSION in txt and config.PUBLISHER in txt
cmd = build_exe.build_command(False, None, [], vf)
assert "--version-file" in cmd and "soundcard" in cmd
assert not Path(SRC + "/make_pixel.py").exists()
assert (Path(ROOT_DIR) / "PRIVACY.md").exists()
assert "make_shortcut.py" in make_manifest.OPTIONAL
print("ok step15")

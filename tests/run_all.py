"""run_all.py - run every test_*.py in this folder, each in its own process.

    python tests/run_all.py            # all of them
    python tests/run_all.py spotify    # only the ones with 'spotify' in the name

Each test is a plain script (no pytest needed). It uses stand-in Qt classes, so no screen and no
PySide6 are needed. A throw-away HOME keeps your real C:\\Users\\<you>\\.atom untouched.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    wanted = argv[1] if len(argv) > 1 else ""
    tests = sorted(p for p in HERE.glob("test_*.py") if wanted in p.name)
    failed = []
    for path in tests:
        env = dict(os.environ)
        home = tempfile.mkdtemp(prefix="atomtest_")
        env.update(HOME=home, USERPROFILE=home, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        if path.name == "test_hud_paint.py":
            env["ATOM_THEME"] = "hud"
        result = subprocess.run([sys.executable, str(path)], env=env, capture_output=True, text=True, timeout=300)
        ok = result.returncode == 0
        print(("PASS " if ok else "FAIL ") + path.name)
        if not ok:
            failed.append(path.name)
            print("\n".join((result.stdout + result.stderr).strip().splitlines()[-12:]))
    print(f"\n{len(tests) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

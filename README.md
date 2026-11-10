# Atom

A personal AI work assistant for Windows: a little jester on your desktop who reads your work files,
answers questions about them, analyses data, builds Power BI reports, keeps reminders and to-dos, and
can help during calls and interviews (when you switch him on). Your files, memory and settings stay on
your own PC.

## Get Atom (no code needed)
Go to **[Releases](../../releases/latest)** and download:

| File | What it is |
|---|---|
| `Atom-Setup-x.y.z.exe` | Normal installer. Double-click, finish, done. Uninstall from Windows > Installed apps. |
| `Atom-x.y.z-portable.zip` | Unzip anywhere (Desktop, USB stick) and run `Atom\Atom.exe`. Nothing to install. |

Then open Atom > Settings and paste your own AI key (a free Groq key works: console.groq.com).
Optional: install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) if you want him to read your screen.

> The files are not code-signed yet, so Windows may say "Windows protected your PC". Click **More info > Run anyway**.

## Repo layout
```
src/            Atom's code (flat modules; main.py starts it) + characters/ (the jester's pictures)
scripts/        build_exe.py (Atom.exe), build_installer.py (installer + zip), make_character.py
tests/          test_*.py, run with  python tests/run_all.py
assets/sheets/  the original expression sheets the jester was cut from
docs/           install, releasing and CI/CD notes
.github/        CI (ci.yml), release (release.yml), Dependabot
requirements.txt        what Atom needs to run
requirements-dev.txt    what you need to build and check it
```

## Run from source (developers)
```
python -m venv .venv && .venv\Scripts\activate
python -m pip install -r requirements.txt
python src/main.py
```

## Test
```
python tests/run_all.py          # all tests, no screen needed
python tests/run_all.py spotify  # only tests with "spotify" in the name
```

## Build the Windows app
```
python -m pip install -r requirements-dev.txt
python scripts/build_exe.py            # -> dist\Atom\Atom.exe
python scripts/build_installer.py      # -> release\Atom-Setup-x.y.z.exe + portable zip (needs Inno Setup)
```
Or let GitHub do it: push a tag like `v0.16.1` (see [docs/RELEASING.md](docs/RELEASING.md)).

## Privacy
See [PRIVACY.md](PRIVACY.md). Atom has no server and no tracking; it only talks to the AI services you choose.

## License
No license file has been chosen yet, which means **all rights reserved**. Add a `LICENSE` file when you decide
(for example MIT if you want others to reuse the code).

# Atom - installing and publishing

(Easiest: let GitHub build it for you, see RELEASING.md.)

## For you (the maker): build the app on your Windows PC
```
python -m pip install pyinstaller
python scripts/build_exe.py         # makes dist\Atom\Atom.exe   (a few minutes)
python scripts/build_installer.py   # makes release\Atom-Setup-x.y.z.exe  and  release\Atom-x.y.z-portable.zip
```
* The installer needs the free **Inno Setup** program (https://jrsoftware.org/isdl.php). Without it you still get the portable zip.
* Every new round of Atom files needs a new build: the built Atom.exe is a copy and does not pick up loose .py files.
* Your data lives in `C:\Users\<you>\.atom`, so rebuilding / reinstalling never loses it.

## For anyone else: put Atom on any PC
* **Installer:** double-click `Atom-Setup-x.y.z.exe`, tick what you want, finish. No administrator needed. Uninstall from Windows > Installed apps.
* **Portable:** unzip `Atom-x.y.z-portable.zip` anywhere (Desktop, USB stick) and double-click `Atom\Atom.exe`.
* On a new PC: open Atom > Settings, paste your own AI key. (Optional) install **Tesseract** (for "read my screen") from https://github.com/UB-Mannheim/tesseract/wiki .
* Windows may show "Windows protected your PC" because the file is not code-signed yet. Click *More info > Run anyway*. Signing it removes this (see below).

## Before you publish to the public
1. **Name and publisher:** change `APP_NAME` / `PUBLISHER` in `src/config.py`; check the name is not already used in the Microsoft Store.
2. **Code-sign** Atom.exe and the installer (a code-signing certificate, or Microsoft's *Trusted Signing*). Unsigned apps get SmartScreen warnings and are often flagged by antivirus.
3. **Privacy policy:** edit `PRIVACY.md`, host it on a public web page and give that link to the Store.
4. **API keys:** Atom makes users bring their own AI key (good: you pay nothing and hold no data). Keys are currently saved in a plain `settings.json`; for a public release move them to Windows Credential Manager (`keyring`).
5. **Call recording:** Hear transcribes other people's voices. Stores review this closely. Keep the clear on-screen "Hear is ON" indicator and the consent note in `PRIVACY.md`, and describe it honestly in the listing.
6. **Third-party licences:** PySide6 (LGPL), Tesseract (Apache), Kokoro voice model, the jester artwork. Make sure you own or may redistribute each. Add a `THIRD_PARTY.txt`.
7. **Test on a clean PC** (no Python installed) before sending to anyone.

## Microsoft Store (optional)
1. Register a developer account at https://partner.microsoft.com/dashboard (one-time fee for individuals).
2. Package as **MSIX** (Microsoft's "MSIX Packaging Tool", or `makeappx`) from `dist\Atom`, with the same name/publisher you reserved in Partner Center. The Store signs the package for you.
3. Fill the listing (description, 1366x768+ screenshots, privacy-policy link, age rating) and submit for certification (a few days).
4. Rules to expect: no hidden recording, no hard-coded secrets, clear permission use (microphone, screen), working uninstall.
Apple's Mac App Store and Google Play are separate (Atom is Windows-only today).

## Using Atom on another virtual desktop
Windows controls that: right-click Atom's icon in the Task View (Win+Tab) > *Show this window on all desktops*.

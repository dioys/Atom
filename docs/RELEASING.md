# Releasing Atom (CI/CD)

## What runs automatically
| When | Workflow | What it does |
|---|---|---|
| Every push to `main` and every pull request | `ci.yml` | lint (`ruff`: syntax errors, undefined names, unused imports), all tests, checks `src/manifest.json` is up to date. On pull requests that touch build files it also proves the Windows build works. |
| You push a tag `vX.Y.Z` | `release.yml` | runs `ci.yml` first, then on Windows: builds `Atom.exe`, makes the installer + portable zip, (signs them if a certificate is set), writes `SHA256SUMS.txt`, and creates a **draft** GitHub Release with the files attached. |
| Weekly | Dependabot | opens pull requests for newer Python packages and GitHub Actions. |

## To release a new version
1. Change `VERSION` in `src/version.py` (for example `0.17.0`).
2. `python src/make_manifest.py` (updates `src/manifest.json`; CI fails if you forget).
3. Commit and push to `main`; wait for the green tick.
4. `git tag v0.17.0` then `git push origin v0.17.0`.
5. Open GitHub > Releases, check the draft and the notes, press **Publish release**.

The tag and `src/version.py` must match or the release stops on purpose.
People who already installed Atom just run the new `Atom-Setup-x.y.z.exe`: it upgrades in place and keeps their data
(`C:\Users\<you>\.atom`).

## Code-signing (removes the Windows warning)
Buy a code-signing certificate (or use Microsoft Trusted Signing), then add two repository secrets
(Settings > Secrets and variables > Actions):
* `WIN_CERT_BASE64` - your `.pfx` file, base64 encoded (`certutil -encode cert.pfx cert.b64`, paste the text between the lines)
* `WIN_CERT_PASSWORD` - its password

`release.yml` signs `Atom.exe` and the installer automatically when `WIN_CERT_BASE64` exists.
This signing step has not been run yet; test it with a draft release first.

## Good GitHub settings
* Settings > Branches: protect `main` (require the CI checks to pass).
* Never commit `settings.json`, `.atom/`, `*.db` or API keys (`.gitignore` already blocks them).
* Settings > Code security: turn on secret scanning and Dependabot alerts.

## Microsoft Store (later)
Needs an MSIX package and a Partner Center developer account; see `docs/INSTALL.md`. A good next step would be a
second job in `release.yml` that builds the MSIX.

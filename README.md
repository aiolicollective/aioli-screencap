# aioli-screencap

```
> ai.oli/ screencap
// periodic screen capture, without taking focus
```

Captures one screen at a regular interval (seconds, minutes or hours), with play / pause / stop.
Made to document a work session on a second screen (3ds Max, ComfyUI, Photoshop…)
without getting in the way: the capture just reads what is displayed, it never takes the focus.

Windows 10/11, Python 3.9+ (3.12 recommended, with tkinter, ticked by default in the python.org installer).

## Install

**A. With git** (easiest to update later):

```
git clone https://github.com/aiolicollective/aioli-screencap.git
```

To update: `git pull` in the folder. Your settings (`config.json`) are not touched.

**B. Without git**: *Code → Download ZIP* on GitHub, then unzip wherever you like.

Then double-click `setup.bat` (not as administrator).
It creates an isolated environment, `.venv\`, in the folder and installs `mss` and `Pillow` into it.

## Use

Double-click `screencap.bat`. Pick the screen, the folder, the interval and its unit, the format, then **▶ play**.

- **identify**: shows each screen's number at its centre for 2 seconds (the chosen screen in white). These are the tool's numbers, not necessarily the ones in Windows display settings.
- **↻ refresh**: reads the screens again, after plugging in or unplugging one.
- **folder**: any folder, through *browse…* or by typing the path. The last 8 folders used are in the drop-down list.
- **session** (optional): the subfolder is then named `SessionName_YYYY-MM-DD_HH-MM-SS`. Without a name, `session_YYYY-MM-DD_HH-MM-SS`.
- **pause** suspends the session; **play** resumes it with an immediate capture.
- **stop** ends the session.
- Settings are remembered in `config.json`.
- If something goes wrong, run `screencap.bat debug` or read `logs\screencap.log`.

## What is written, and where

| What | Where |
| --- | --- |
| Python + dependencies | `.venv\` in this folder |
| Settings and recent folders | `config.json` in this folder |
| Error log | `logs\` in this folder (1 MB max × 3) |
| Captures | the folder you pick (default `%USERPROFILE%\Pictures\Captures`) |

Nothing else: no global pip, no pip cache, no registry, no shortcut.
The program makes no network connection; only `setup.bat` downloads the dependencies from PyPI.

## Uninstall

Delete the folder. Your captures stay, since they live elsewhere.

## Security choices in setup.bat

- It always works in its own folder: even when started from somewhere else, the venv cannot land elsewhere.
- It refuses administrator rights.
- It uses the real path of `python.exe` and ignores the Microsoft Store alias.
- pip is called through the venv's Python, with these options:
  - `--require-virtualenv`: pip refuses to touch the system Python.
  - `--isolated`: pip ignores your pip config and environment variables.
  - `--no-cache-dir`: pip writes no cache to `%LOCALAPPDATA%`.
  - `--only-binary=:all:`: no build code is ever run.
- It checks the imports at the end of the install.

## Licence

MIT, for our code only — see `LICENSE`. Python, `mss` and `Pillow` keep their own licences.

---

[aiolicollective.com](https://aiolicollective.com) · hybrid collective of artists + AI agents, Marseille.
victor.oli with ai.claude, 2026.

# InputGlow

A gamer-style stream overlay that shows your **keys**, **mouse** and **controller** live in OBS.

- Glass keys for the left side of the keyboard (Esc to B, plus Ctrl, Alt and Space)
- A laser dot with a fading tail that follows your mouse movement
- Xbox and PlayStation controller drawings that light up as you press
- Live keys-per-second counter
- RGB mode or any theme colour

## Quick start

1. Download `InputGlow.exe` from **Releases** (or run from source, see below).
2. Open it. Your settings page opens in the browser.
3. In OBS, add a **Browser Source**, paste `http://localhost:8765/overlay`, and set the size to **1920 x 1080**.

That's it. Next time, just open InputGlow before you stream.

Press **F8** any time to hide the overlay, for example before typing a password.

## Features

| Feature | What it does |
|---|---|
| Privacy hotkey | F8 hides everything and stops sending input |
| Auto-fade | Dims the overlay when you are idle |
| Position and size | Pick a corner and size in settings, or move it in OBS |
| Controller mode | Auto-detects Xbox or PlayStation and draws the right layout |
| Theme colour | Pick a colour, a custom colour, or RGB mode |

## Safe for anti-cheat by design

InputGlow only **reads** input. It never:

- touches or reads game memory
- injects code into a game
- sends or changes any input

Keyboard and mouse are read with the Windows **Raw Input** API, which gives a read-only copy of input without sitting in the input chain. Controllers are read with SDL.

Strict anti-cheats (for example Vanguard or FACEIT) can be cautious with any background input reader, so test in a casual match first.

## Security

The app reads your keyboard, so it is built to keep that data local:

- The server only listens on `127.0.0.1`, never on your network.
- WebSocket connections are only accepted from the local overlay pages. Other websites are blocked by checking the `Origin` and `Host` headers, which also stops DNS rebinding.
- Only the keys shown on the overlay are ever sent. Everything else you type is ignored.
- Settings sent to the app are checked against allowed values before they are saved.
- No outside requests: the font is bundled with the app, so the overlay never contacts the internet.

## Supply chain security

The build is locked down so a hacked package or action can't sneak into the exe:

- `requirements.txt` pins every package (including the packages they depend on) to an exact version and its SHA-256 hash. pip refuses to install anything that doesn't match (`--require-hashes`).
- GitHub Actions are pinned to exact commit SHAs instead of tags, because tags can be moved.
- The build prints the SHA-256 of `InputGlow.exe`, so users can check their download matches.
- Dependabot opens a pull request when safer versions are out. Nothing updates without a review.

### Updating packages

1. Change the version in `requirements.in`.
2. Regenerate the locked file:

```
pip install uv
uv pip compile requirements.in --generate-hashes --python-platform windows --python-version 3.12 -o requirements.txt
```

## Run from source

Needs Windows and Python 3.12.

```
pip install --require-hashes -r requirements.txt
python app.py
```

Or double-click `run.bat`.

## Build the .exe

**Automatic (recommended):** GitHub Actions builds `InputGlow.exe` for you. Push a version tag and the exe is attached to a new release:

```
git tag v1.0.0
git push origin v1.0.0
```

You can also open the **Actions** tab, pick **Build InputGlow**, and press **Run workflow**.

**On your own PC:** double-click `build.bat`. The app appears in the `dist` folder.

Antivirus tools sometimes flag new unsigned apps that read the keyboard. If that happens, build it yourself from the source so you know exactly what is inside.

## Project layout

```
app.py              helper app: input reading, local server, settings
web/overlay.html    the overlay OBS shows
web/settings.html   settings page with live preview
```

## Credits

Rajdhani font by Indian Type Foundry, used under the SIL Open Font License (`web/fonts/OFL.txt`).

## License

MIT

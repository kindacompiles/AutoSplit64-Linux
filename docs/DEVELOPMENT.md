# Developer guide

How AutoSplit64 (Linux port) is put together, how data flows through it at
runtime, and how to build every piece. For end-user setup see the top-level
[`README.md`](../README.md).

> **Scope of this port.** The recognition engine, route format and GUI are the
> upstream [AutoSplit64plus](https://github.com/DaviBe92/AutoSplit64plus) code.
> The Linux work is concentrated in the **capture layer**, the **timer layer**,
> **path handling**, and **packaging** — those are the parts described in most
> detail below.

---

## 1. The big picture

```
                 ┌────────────────────────────────────────────┐
   SM64 console  │                AutoSplit64                  │
        │        │                                             │
   capture card  │   capture layer ──► recognition ──► route   │
        │        │   (frame source)    (what's on       engine │
        ▼        │                      screen)          │     │
   ┌─────────┐   │                                       ▼     │
   │  OBS or │──►│                                  timer layer │──► LiveSplit
   │  V4L2   │   │   PyQt6 GUI (right-click menu, dialogs)      │    (the split)
   └─────────┘   └────────────────────────────────────────────┘
```

The core runs a tight loop: **grab a frame → classify what's happening →
ask the current route step whether to split → if so, tell the timer.** The GUI
runs on the Qt main thread; the detection loop runs on a worker thread.

---

## 2. Repository layout

| Path | What's in it |
|------|--------------|
| `AutoSplit64.py` | Entry point. Builds the Qt `App`, registers every detection *process*, loads the route, and starts the loop on a worker thread. |
| `as64core/` | The engine: capture, recognition, timer, routes, config, paths. |
| `as64gui/` | PyQt6 GUI — `app.py` (main window + right-click menu), `dialogs/` (settings, capture editor, route editor), `graphics/`, `widgets/`. |
| `as64processes/` | The detection *processes* (`standard`, `xcam`, `ddd`, `final`, `lblj`) registered in `AutoSplit64.py`. Each decides, for its situation, when a split/skip/reset should fire. |
| `logic/` | Image-processing building blocks used by the processes. |
| `routes/` | Example `.as64` route files. |
| `templates/` | Default + generated console-reset reference frames. |
| `resources/` | GUI assets, icons, and the ONNX star-classifier model. |
| `obs-plugin/` | The OBS frame-grabber source filter (C). `src/` is shared; `linux/` holds the Linux CMake build. |
| `packaging/` | AppImage builder (`build_appimage.sh`, `AppRun`, `.desktop`). |
| `defaults.ini` | Shipped default config (JSON despite the `.ini` name). |
| `build.bat` | Upstream Windows PyInstaller build (kept for reference; not used on Linux). |

---

## 3. as64core — the engine

### Capture layer

`game_capture.py` wraps three interchangeable frame sources, selected by
`game.capture_method` in config:

| `capture_method` | Backend module | Platform | Notes |
|------------------|----------------|----------|-------|
| `"obs"` | `capture_shmem.py` | Linux + Windows | Reads frames the OBS plugin writes into shared memory (`/dev/shm/as64_grabber` on Linux). |
| `"v4l2"` | `capture_v4l2.py` | Linux | Opens a `/dev/videoN` card directly via OpenCV `CAP_V4L2`. **Exclusive** — only one reader per device, so it can't share the card with OBS. |
| `"window"` | `capture_window.py` | Windows only | Legacy Win32 window capture. |

`GameCapture` also owns the **region math**: the user's `game_region` rectangle
plus fixed ratio constants (`constants.py`) are turned into the sub-regions the
recognizer crops (star count, fade, reset, X-Cam, …).

### Recognition

`model.py` runs the ONNX **star classifier** (via `onnxruntime`); `processing.py`
and `image_utils.py` provide the frame pipeline and the hooks that processes
register against. `as64processes/*` contain the per-situation state machines
(the "processes") that the engine steps through.

### Route engine

`route.py` / `route_loader.py` load `.as64` routes. A split step fires when the
target **star count** is reached *and* the configured number of **fade-outs /
fade-ins** have happened since. The GUI route editor can import a LiveSplit
`.lss` and pre-fill a route.

### Timer layer

This is where "we decided to split" becomes a real LiveSplit action.
`livesplit.py` is the dispatcher; it hides three transports behind one
interface (`connect`, `split`, `reset`, `skip`, `undo`, `split_index`, …):

1. **LiveSplit TCP** (`socket`) — the classic LiveSplit Server protocol.
   Bidirectional: `getsplitindex` can be *read back*.
2. **LiveSplit named pipe** (`win32file`) — Windows only.
3. **OBS LiveSplit One** (`timer_obsws.py`, `OBSWebSocketTimer`) — controls the
   `obs-livesplit-one` source over **OBS WebSocket** (`obsws-python`).

> ### Two different "OBS" integrations — don't confuse them
> - **OBS *capture*** = the frame-grabber **plugin** + shared memory. Moves
>   *pixels* into AutoSplit64.
> - **OBS *timer*** = **OBS WebSocket** firing the LiveSplit One source's
>   hotkeys. Moves *split commands* out to the timer.
>
> They are independent; you can use either, both, or neither.

#### The split-index mirror (a port-specific subtlety)

`obs-livesplit-one` has **no control protocol** — it's driven only through the
source's internal OBS hotkeys (`hotkey_split` = start-or-split, `hotkey_reset`,
`hotkey_undo`, `hotkey_skip`, `hotkey_pause`), so the user doesn't have to bind
physical keys.

That path is effectively **one-way**: unlike TCP, OBS WebSocket can't read the
current split index back. But the engine's main loop *relies* on reading the
split index to advance the route (`base.py` resyncs its route position to the
timer's index each tick). So `OBSWebSocketTimer` keeps a **local mirror**: it
starts at `-1`, and after each hotkey *actually fires* it updates the counter
(`split`/`skip` → `+1`, `undo` → `-1`, `reset` → `-1`, `restart` → `0`).
`split_index()` returns that mirror, so the route advances on the OBS path
exactly as it does on TCP.

> **Known limitation:** splits the user makes **manually in LiveSplit** (not via
> AutoSplit64) can't be observed over this path, so the mirror can drift. This
> is inherent to the hotkey-only interface.

*(This mirror is why splits now advance past the first level on the OBS timer —
see commit `a8604dc`.)*

### Paths & config

`paths.py` keeps two path kinds strictly apart so a **read-only AppImage** mount
works:

- **Bundled, read-only** (app code, GUI assets, default templates, ONNX model,
  `defaults.ini`) → resolved from `__file__` / the app root (or PyInstaller's
  `_MEIPASS` when frozen). Never written to.
- **User-writable** → XDG dirs: config in `~/.config/autosplit64`, data/logs in
  `~/.local/share/autosplit64`.

`config.py` loads `defaults.ini`, overlays the user's `config.ini`, and falls
back to the default on any missing key — so **adding a new config key never
breaks existing installs**. (That's why `remember_window_position`,
`obs_projector_geometry`, etc. could be added safely.)

---

## 4. The OBS frame-grabber plugin

An OBS **effect source filter** (C) you add to your SM64 video source. It copies
every rendered frame into a POSIX shared-memory segment
(`/dev/shm/as64_grabber`) that `capture_shmem.py` reads. On filter removal or OBS
shutdown it `shm_unlink`s the segment so nothing stale is left behind.

- Shared source: `obs-plugin/src/autosplit64plus-framegrabber.c` (the `#else`
  branches are the POSIX port of the original Win32 shared memory).
- Linux build: `obs-plugin/linux/` — see its [README](../obs-plugin/linux/README.md).

```bash
cd obs-plugin/linux
./build.sh          # → build/autosplit64plus-framegrabber.so
```

Needs `cmake`, a C compiler, and OBS dev headers (`libobs-dev` /
`obs-studio-devel` / `obs-studio`). Arch's `libobs.pc` omits the include `-I`
(headers live in `/usr/include/obs/`), so the CMake explicitly `find_path`s
`obs-module.h` — see commit `854d4b3`.

---

## 5. Building the AppImage

The portable distributable. One command:

```bash
./packaging/build_appimage.sh          # → dist/AutoSplit64-*.AppImage
```

It builds **inside a `manylinux_2_28` container** (glibc 2.28) because a Linux
binary's *minimum* glibc equals the host it was built on, and glibc is only
forward-compatible — so building on Arch/current-Ubuntu would refuse to start on
Debian 12. The container gives one artifact that runs on essentially every
current distro. `--native` skips the container for quick local testing (but ties
the result to this host's glibc).

The build downloads a relocatable CPython 3.12
(astral-sh/python-build-standalone), `pip install`s the **runtime** deps
(`pyinstaller` is skipped — it's only for the Windows `.exe`), copies the app
tree, bundles the Qt **xcb** support libs, and packages with `appimagetool`.
Full details and troubleshooting: [`packaging/README.md`](../packaging/README.md).

---

## 6. Dev environment

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python AutoSplit64.py
```

- **Python 3.12 is required** — the deps are pinned and some have no wheels for
  3.13/3.14. On Arch (default Python is newer), get 3.12 via `uv`, the AUR
  `python312`, or `pyenv`.
- Virtualenvs are **not portable** between machines — recreate per machine.
- `opencv-python-headless` is deliberate: regular `opencv-python` bundles its
  own Qt that clashes with PyQt6's xcb plugin. The app uses cv2 only for image
  processing, never its GUI.

---

## 7. Contributing & git conventions

- Commits in this repo use the placeholder identity **`AutoSplit64 Dev
  <dev@localhost>`** and carry **no co-author / attribution trailer**. Nothing
  is pushed to a remote from here.
- When you're ready to publish under your own GitHub account, follow
  [`GIT_IDENTITY.md`](../GIT_IDENTITY.md) to rewrite author/committer to your
  real account + GitHub noreply email, then push.

### Port history (commit milestones)

| Phase | Commit | What landed |
|-------|--------|-------------|
| Base | `d6222ce` | Imported AutoSplit64plus (DaviBe92). |
| 1 | `8004b7c` | Linux groundwork (paths, platform guards). |
| 2 | `e624bfd`, `9fe3706` | Capture layer: POSIX shared memory + V4L2. |
| 3 | `a4fc31c` | Timer: OBS WebSocket + LiveSplit One hotkeys. |
| — | `5f02b21`, `a8604dc`, `854d4b3` | Real-hardware fixes (capture-editor message, OBS split advance, Arch plugin build). |
| 5 | `899ac2f` | AppImage packaging. |
| — | `03a44bf` | QoL: remember window position + pop-out LiveSplit projector. |

---

*This port and its documentation were produced with assistance from
[Claude Code](https://claude.com/claude-code) (Anthropic).*

# AutoSplit64 Linux Port — Spec for Claude Code

Oct 30, 2026 · @The Orchestrator

## Project Overview

AutoSplit64 Linux is a native Linux port of the Super Mario 64 auto-splitter, enabling SM64 speedrunners on Linux to automatically split their timer based on real-time image recognition of the game feed. It works with both capture cards (real console) and emulators, and connects to OBS LiveSplit One for timing.

### What AutoSplit64 does

AutoSplit64 captures the SM64 video feed, analyzes it with OpenCV to detect game state (star counts, fadeouts, screen transitions, file select, final star), and sends split/start/reset commands to a speedrun timer. It is *not* a memory reader — it works by watching the picture, which means it works with real N64 consoles through capture cards, not just emulators.

### Why a Linux port

The original AutoSplit64 and its enhanced fork AutoSplit64plus are Windows-only. Two rough Linux forks exist (SmolAlli/AutoSplit64plusLinux, Poke711/AutoSplit64plusLinux) but they have zero releases, no working timer connection on Linux, no capture card fallback, and describe themselves as "held together with glue and tape."

**What makes this port different from the existing Linux forks:**

- **Actual releases**: AppImage packaging so users download one file and run it, not clone a repo and debug dependencies
- **Working timer integration**: A proper connection to OBS LiveSplit One (the existing forks have a hacky WebSocket server with bare `except:` blocks, hardcoded ports, and tabs-vs-spaces issues)
- **Capture card support**: V4L2 backend for direct capture card use without OBS (no existing fork has this)
- **Documentation**: README with quick start, setup guide, config reference, troubleshooting, and capture card compatibility list
- **Clean codebase**: Built from the pristine AutoSplit64plus base with intentional, well-understood Linux changes rather than incremental patches

### Base codebase

Fork from **DaviBe92/AutoSplit64plus** (not the original Kainev/AutoSplit64, which is mid-rewrite into Electron/React and has no usable Python source on master). AutoSplit64plus is the codebase both existing Linux forks started from. It adds direct OBS integration, automatic LiveSplit connection, automatic capture region detection, and improved star recognition over the original.

**Decision: pristine base + cherry-picked references.** We compared SmolAlli's Linux fork against the pristine AutoSplit64plus base. Most of SmolAlli's changes are mechanical (import guards, platform markers, asset renames) or things we'd rewrite anyway (timer, capture dialog). The one genuinely hard piece — the POSIX shared memory protocol pair (framegrabber.c Linux `#else` branch + capture\_shmem.py) and the cmake/linux preset — we lift from SmolAlli as a reference/starting point. Everything else (paths/XDG, requirements, GUI, timer, V4L2, packaging) we write clean. This gives us a tidy git history and full ownership of every change.

**Attribution:** Credit SmolAlli (and Poke711) in the README and in code comments on files derived from their work. The full fork chain (Kainev → DaviBe92 → SmolAlli → this project) should be visible in the README's acknowledgments section.

### What we keep vs. what we change

- **Keep**: All image recognition and game-state detection logic (Python/OpenCV/NumPy/onnxruntime — already cross-platform), the PyQt6 desktop GUI framework, the route (.as64 JSON files) and template (.jpg reference images) structure
- **Change**: OBS framegrabber plugin (DLL to .so, Named Pipes to POSIX shared memory), timer connection (TCP/Named Pipes to OBS WebSocket or LiveSplit One WebSocket — design TBD in Phase 3), path handling (Windows paths to XDG), config defaults for Linux, packaging (NSIS installer to AppImage), removal of pywin32/pywin32-ctypes dependency
- **Add**: V4L2 capture card backend (genuinely new code — no existing fork has this), Wayland/X11 compatibility handling for PyQt6, Linux setup documentation

## Architecture

&#91;embedded content: data flow · capture to split commands\]

The capture layer accepts frames from either source (OBS plugin via shared memory, or direct V4L2 capture card). The recognition engine is pure Python/OpenCV and doesn't change. The output layer replaces the Windows TCP/Named Pipe client with a WebSocket-based timer connection (exact approach TBD — see Component 2). The GUI is a PyQt6 desktop application, not a web app.

## Component 1 — Game Capture

Two capture methods, selectable in config. The OBS plugin is the primary path; V4L2 is the fallback for users who don't use OBS or want standalone practice.

### OBS Framegrabber Plugin (.so)

The OBS framegrabber plugin C source and CMake build already exist in the DaviBe92/AutoSplit64plus base repo (`obs-plugin/` directory). It compiles to `autosplit64plus-framegrabber.so` on Linux. The plugin registers as an OBS source filter, grabs each rendered frame, and writes it to a POSIX shared memory segment (`shm_open` / `mmap`). The Python side reads from that same segment. The Linux forks (SmolAlli, Poke711) added the POSIX `#else` branches to the C source and a `cmake/linux` preset — we use those as our starting reference.

**What exists in the base repo (DaviBe92):**

- C source in `/obs-plugin/` directory (Windows paths; needs POSIX `#else` branches)
- CMake build system (requires `libobs-dev`, optionally `libsimde-dev`)
- The Linux forks added: POSIX `shm_open`/`mmap` replacing Windows `CreateFileMapping`/`MapViewOfFile`, and `cmake/linux` preset
- Known issue in SmolAlli's version: never calls `shm_unlink` on close, leaving stale `/dev/shm/as64_grabber`; debug prints in hot path; re-mmaps header every frame

**What to do:**

- Clean up the C source, fix the shared memory initialization bug
- Add error handling and logging for when OBS isn't running or the plugin isn't loaded
- Build the `.so` as part of the AppImage packaging, or provide separate install instructions
- Test with OBS 28+ and 30+ (both common on Linux currently)

### V4L2 Capture Card Fallback

Capture cards (like the EVGA XR1 Lite) appear as `/dev/video*` devices on Linux. OpenCV's `VideoCapture` can read from them directly with the V4L2 backend.

**Implementation:**

```python
import cv2
cap = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
ret, frame = cap.read()  # numpy array, ready for recognition
```

**What to do:**

- Add a `capture_method` config option: `obs` (default) or `v4l2`
- Auto-detect available `/dev/video*` devices and list them in the GUI
- Let user select device and resolution
- This is roughly 50 lines of Python — the simplest component in the project

### Wayland vs X11 Considerations

**Correction from original spec:** The display server matters more than initially stated. Because the GUI is PyQt6 (not a browser-based web app), it depends on the Qt platform plugin — on X11 this requires `libxcb-cursor0`, and the `xcb` platform plugin is the typical crash point on a fresh Linux install. The capture pipeline itself (OBS shared memory, V4L2 hardware) is compositor-independent, but the GUI window needs Qt platform support. Both X11 and Wayland are supported by Qt6, but may need different runtime dependencies. The AppImage should bundle the necessary Qt platform plugins for both.

## Component 2 — Timer Integration

The original AutoSplit64plus connects to LiveSplit on Windows via TCP socket (port 16834) or Named Pipes. On Linux, the timer is OBS LiveSplit One, which runs as an OBS source plugin and accepts commands over the OBS WebSocket protocol.

### How OBS LiveSplit One works

OBS LiveSplit One is a native OBS plugin (written in Rust, using livesplit-core) that renders the timer directly inside OBS as a source. It supports hotkeys configured in OBS settings and can accept external control through OBS's built-in WebSocket server (obs-websocket, included in OBS 28+).

Install methods:

- Linux tarball: extract to `~/.config/obs-studio/plugins/`
- Flatpak OBS: `flatpak install flathub com.obsproject.Studio.Plugin.OBSLivesplitOne`
- Arch AUR: `obs-livesplit-one-bin`

### Protocol: OBS WebSocket

OBS 28+ includes obs-websocket (v5) built in. We send commands to the LiveSplit One source via OBS WebSocket requests. The Python client library is `obsws-python` or `obs-websocket-py`.

**Key commands we need to send:**

*Note: The exact timer approach is a Phase 3 design decision. Two legitimate options exist: (1) obsws-python → OBS WebSocket (:4455) → trigger OBS hotkeys bound to LiveSplit One actions, or (2) a WebSocket client connecting directly to LiveSplit One's own WebSocket server (the approach SmolAlli used, on :5678). The obsws-python/hotkey approach is sketched below as a starting point, but both should be evaluated before committing.*

| Action | OBS WebSocket approach |
| --- | --- |
| Start timer | `CallVendorRequest` or trigger the source's hotkey via `TriggerHotkeyByKeySequence` |
| Split | Same — trigger the split hotkey |
| Reset | Trigger the reset hotkey |
| Pause | Trigger the pause hotkey |

**Implementation sketch:**

```python
import obsws_python as obs

client = obs.ReqClient(host='localhost', port=4455, password='changeme')
# Trigger split hotkey configured in OBS
client.trigger_hot_key_by_key_sequence('OBS_KEY_NUMPAD1')
```

**What to do:**

- Replace the existing `livesplit_client.py` TCP socket code with an OBS WebSocket client
- Add config options for OBS WebSocket host, port, and password
- Map each auto-split action (start, split, reset, undo) to the corresponding OBS hotkey
- Add connection status indicator in the GUI
- Handle reconnection gracefully if OBS restarts

### Fallback: Direct LiveSplit Server TCP

Keep the existing TCP client code as a fallback for users who run LiveSplit through Wine or LiveSplit One in a browser with the server component. The protocol is simple text over TCP (port 16834): send `starttimer\r\n`, `split\r\n`, `reset\r\n`, etc. This code already exists and is cross-platform — just don't remove it.

## Component 3 — Image Recognition & Game State

This is the core of AutoSplit64 and it requires no changes. The entire recognition pipeline is Python with OpenCV and NumPy, both of which are fully cross-platform.

### What it detects

- **Star count**: reads the star counter display on screen using template matching and digit recognition
- **Fadeouts/fadeins**: detects screen transitions by monitoring average brightness in key regions
- **Screen states**: identifies file select, course select, final star cutscene, and other game-specific screens
- **Reset detection**: spots when the player returns to the title screen or file select

### Key files (in `as64core/`)

- `image_utils.py` — frame capture interface, image preprocessing
- `game_capture.py` — the abstraction layer between capture source and recognition (this is where we plug in V4L2 as an alternative)
- `star_count.py` — star counter digit recognition
- `route.py` — split route definitions and state tracking
- `split_processor.py` — main loop that runs recognition and triggers splits

### What to do

- **Nothing** to the recognition logic itself
- Update `game_capture.py` to accept frames from the new capture backends (POSIX shared memory reader, V4L2 reader) instead of the Windows-specific capture
- Ensure the frame format (BGR numpy array, expected resolution) matches what OpenCV expects — it should, since both capture methods deliver standard frames

## Component 4 — GUI & Configuration

### PyQt6 Desktop GUI

**Correction:** The GUI is a PyQt6 desktop application with 19 PyQt6 imports — not Flask, not a web app, no browser tab. There is zero Flask code in the codebase.

The `as64gui/` directory contains the Qt application: main window, dialogs (capture editor, route editor, settings), and custom widgets. On Linux, the main change is replacing `MSWindowsFixedSizeDialogHint` with `FramelessWindowHint` + custom close/minimize buttons (SmolAlli already did this, but we write it clean).

**What to do:**

- Remove `pywin32`/`pywin32-ctypes` imports (Windows-only, blocks `pip install` on Linux)
- Guard any remaining `win32gui`/`win32ui`/`win32process` imports behind `sys.platform == 'win32'`
- Replace the commented-out capture editor dialog (SmolAlli just commented out the OBS plugin checkbox + process selector) with a clean Linux capture configuration UI: OBS shared memory toggle, V4L2 device selection dropdown
- Ensure `libxcb-cursor0` dependency is documented (required for the Qt `xcb` platform plugin on X11)
- Test GUI launch on both X11 and Wayland

### Configuration: JSON format

**Correction:** The config files (`defaults.ini` / `config.ini`) are loaded with `json.load()` despite the `.ini` extension — they are JSON, not INI format. Do not use `configparser`.

Changes needed:

- **Add new settings**: `capture_method` (obs/v4l2), `v4l2_device` (/dev/video0), `timer_method` (obs\_websocket/livesplit\_tcp), `obs_ws_host`, `obs_ws_port`, `obs_ws_password`
- **Change default paths**: use XDG conventions — config in `~/.config/autosplit64/`, data in `~/.local/share/autosplit64/`
- **Remove Windows-specific settings**: AmaRecTV references, Windows-specific capture options

### Path Handling

Replace all hardcoded Windows paths (`C:\`, backslashes, registry lookups) with:

- `os.path.expanduser('~')` for home directory
- `pathlib.Path` for cross-platform path operations
- XDG base directory spec: `XDG_CONFIG_HOME` (defaults to `~/.config`), `XDG_DATA_HOME` (defaults to `~/.local/share`)

### Routes and Templates

**Correction:** `routes/` contains `.as64` files (JSON split-route definitions), not HTML routes. `templates/` contains `.jpg` reference images used by the recognition engine for template matching, not Jinja2/HTML templates. Both directories are already cross-platform. Users back up and transfer these between installations.

## Component 5 — Packaging & Distribution

### AppImage

The primary distribution format. An AppImage bundles Python, all pip dependencies, and the application into a single executable file. The user downloads it, runs `chmod +x`, and double-clicks.

**Build approach:**

- Use `python-appimage` or `appimage-builder` to package
- Bundle Python 3.11+, OpenCV, NumPy, PyQt6, websocket-client/obsws-python, onnxruntime, and all other pip deps
- The OBS plugin (`.so`) ships separately — it installs into OBS's plugin directory, not the AppImage
- Include a `build_appimage.sh` script in the repo (the Poke711 fork has a starting point)

**What goes in the AppImage:**

- Python runtime
- All Python packages (opencv-python-headless, numpy, PyQt6, obsws-python, onnxruntime, etc.)
- The application code (as64core, as64gui, as64processes, logic, routes, templates)
- A default config.ini
- An `AppRun` entry point script
- Desktop file and icon for desktop integration

**What ships separately:**

- `autosplit64plus-framegrabber.so` (OBS plugin) — with install instructions for system OBS and Flatpak OBS
- Split route files (user-provided or downloadable from community)

### GitHub Releases

Each release includes:

1. `AutoSplit64Linux-x86_64.AppImage` — the main application
2. `autosplit64-obs-plugin-linux-x86_64.tar.gz` — the OBS framegrabber plugin
3. A `README` section with quick-start instructions
4. SHA256 checksums

### Dependencies the user must have

- OBS Studio 28+ (for the OBS capture method and OBS LiveSplit One)
- OBS LiveSplit One plugin (for the timer)
- A capture card or emulator providing the game feed

The AppImage itself has no external dependencies — it bundles everything.

## Reference Repositories

| Repository | What to use from it | License |
| --- | --- | --- |
| [DaviBe92/AutoSplit64plus](https://github.com/DaviBe92/AutoSplit64plus) | **Base fork.** All Python source: as64core, as64gui, as64processes, logic, routes, templates, config. OBS plugin C source in obs-plugin/ | GPLv3 |
| [SmolAlli/AutoSplit64plusLinux](https://github.com/SmolAlli/AutoSplit64plusLinux) | **Reference only.** Cherry-pick the POSIX shared memory branches (framegrabber.c, capture\_shmem.py) and cmake/linux preset. Attribute in README and code comments | GPLv3 (inherited) |
| [Poke711/AutoSplit64plusLinux](https://github.com/Poke711/AutoSplit64plusLinux) | AppImage build script reference. Attribute in README | GPLv3 (inherited) |
| [Kainev/AutoSplit64](https://github.com/Kainev/AutoSplit64) | Reference only — mid-rewrite, not directly usable. Check for any recognition improvements not yet in AutoSplit64plus | GPLv3 (original) |
| [LiveSplit/obs-livesplit-one](https://github.com/LiveSplit/obs-livesplit-one) | Reference for how the OBS LiveSplit One plugin works, its hotkey system, and how to control it externally | Apache-2.0 / MIT |
| [LiveSplit/LiveSplit.Server](https://github.com/LiveSplit/LiveSplit.Server) | TCP protocol reference for the fallback LiveSplit connection | MIT |

### License

**Correction:** The base codebase (AutoSplit64plus, inherited from Kainev/AutoSplit64) is **GPLv3**, not MIT as originally stated in this spec. Our fork must also be GPLv3. This means anyone who distributes a modified version must also release their source under GPLv3. This is fine for our purposes — we want this to stay open source. OBS LiveSplit One is Apache-2.0/MIT dual-licensed, which is compatible with GPLv3.

## Implementation Order

Work in phases so each produces something testable. Claude Code should tackle these in order.

### Phase 1 — Fork and clean (Day 1)

1. Fork DaviBe92/AutoSplit64plus
2. Clone both the fork and SmolAlli/AutoSplit64plusLinux side by side for reference (cherry-pick the shmem protocol pair and cmake/linux preset from SmolAlli; do not merge wholesale)
3. Remove Windows-only code: NSIS installer, `.bat` scripts, Windows Named Pipe code, AmaRecTV references, `installer.nsh`
4. Replace all Windows path handling with `pathlib.Path` and XDG conventions
5. Update config JSON defaults for Linux paths (note: config files use JSON format despite `.ini` extension)
6. Get the Python code to *import and start* on Linux (it will crash on capture — that's fine). Entry point is `AutoSplit64.py`, not `run.py`

**Milestone**: `python AutoSplit64.py` launches the PyQt6 GUI on Linux without crashing. All Windows-only imports are guarded or removed. Config loads from XDG paths.

### Phase 2 — Capture layer (Days 2–3)

1. Port the OBS framegrabber plugin C source from the Linux fork into the project
2. Set up the CMake build for the `.so`
3. Implement the POSIX shared memory reader in Python (replace Windows `CreateFileMapping` calls)
4. Add the V4L2 capture backend using OpenCV VideoCapture
5. Add `capture_method` config option and wire both backends into `game_capture.py`
6. Test: frames arriving from OBS and from a `/dev/video` device

**Milestone**: the app can capture and display frames from both an OBS source and a direct capture card.

### Phase 3 — Timer connection (Day 4)

1. Install `obsws-python` and write the OBS WebSocket client module
2. Map auto-split actions (start, split, reset, undo, pause) to OBS hotkey triggers
3. Add config options for OBS WebSocket connection (host, port, password)
4. Keep the existing TCP LiveSplit client as a fallback option
5. Add `timer_method` config option to select between obs\_websocket and livesplit\_tcp
6. Test: trigger splits in OBS LiveSplit One from the Python app

**Milestone**: a manual "test split" button in the GUI triggers a split in OBS LiveSplit One.

### Phase 4 — Integration testing (Days 5–6)

1. Run the full pipeline: capture card → OBS → framegrabber → recognition → WebSocket → LiveSplit One split
2. Test with actual SM64 gameplay (real console via capture card, and emulator)
3. Verify star detection accuracy with different capture resolutions and aspect ratios
4. Fix any timing issues, frame drops, or recognition regressions
5. Test the V4L2 path end-to-end without OBS

**Milestone**: the auto-splitter correctly detects and splits on stars during a real SM64 run.

### Phase 5 — Packaging and release (Day 7)

1. Write the `build_appimage.sh` script
2. Build and test the AppImage on a clean system (no dev dependencies pre-installed)
3. Compile and package the OBS plugin `.so`
4. Write the README with: quick start, full setup guide, config reference, troubleshooting
5. Create the GitHub release with AppImage, OBS plugin tarball, and checksums
6. Tag v0.1.0

**Milestone**: a new user can download two files from GitHub Releases, follow the README, and be auto-splitting within 15 minutes.

## Open Questions & Risks

### Known unknowns

- **OBS plugin API stability**: The framegrabber plugin compiles against the OBS plugin API. OBS 28→29→30 introduced breaking changes. The plugin build should pin a minimum OBS version and test against the two most recent major releases. If the API breaks, the V4L2 fallback path keeps the app usable.
- **OBS LiveSplit One hotkey mapping**: The WebSocket approach triggers OBS hotkeys, which in turn trigger LiveSplit One actions. The exact hotkey-to-action binding depends on the user's OBS LiveSplit One configuration. The app should document the required hotkey setup, or auto-detect assigned hotkeys via the OBS WebSocket `GetHotkeyList` call if possible.
- **Capture card quirks**: Different capture cards expose different V4L2 capabilities. The EVGA XR1 Lite is confirmed to work, but other cards (Elgato, AVerMedia) may need different pixel format handling or resolution negotiation. Add a "capture card compatibility" section to the README and invite users to report working hardware.
- **Star detection thresholds**: The existing image recognition thresholds were tuned for Windows capture paths. Different color spaces, gamma curves, or compression from Linux V4L2 drivers or the OBS framegrabber may shift pixel values enough to cause missed or false detections. Plan for a calibration pass during Phase 4.

### Wayland caveats

- The capture pipeline has no Wayland dependency — it reads from hardware (V4L2) or OBS (shared memory), not the desktop compositor.
- OBS on Wayland uses PipeWire for screen capture, but since we capture OBS's output via the framegrabber plugin (which reads from OBS's internal rendering pipeline), the compositor doesn't matter for capture.
- The PyQt6 GUI depends on the Qt platform plugin. On X11, this requires `libxcb-cursor0` (the exact crash point Claude Code hit during Phase 1). On Wayland, Qt6 uses its Wayland platform plugin. The AppImage should bundle both platform plugins.
- **One edge case**: if a future version adds direct window capture (grabbing an emulator window without OBS), that would need compositor-specific code. For now, this is out of scope — the OBS and V4L2 paths cover all use cases.

### OBS version compatibility

- **Minimum**: OBS 28.0 (first version with built-in obs-websocket v5)
- **Recommended**: OBS 30.0+ (latest stable, best PipeWire and plugin support)
- **OBS LiveSplit One**: requires OBS 28+ and is distributed as a separate plugin (tarball, Flatpak, or AUR). The app should check for its presence via `GetSourcesList` on startup and show a clear error if it's missing.
- **obs-websocket protocol**: Use protocol version 5.x only. Version 4.x (the old plugin) is deprecated and should not be supported.

### Other risks

- **AppImage size**: Bundling Python + OpenCV + NumPy + Flask + dependencies could produce a large AppImage (200–400 MB). Consider whether to ship a minimal OpenCV build without GUI/video codec modules the app doesn't use.
- **Thread safety**: The original codebase uses Python threading for concurrent capture and recognition. Verify that the POSIX shared memory reader is thread-safe and that frame handoff between the capture thread and the recognition thread doesn't race.
- **Upstream divergence**: AutoSplit64plus may continue receiving updates. Decide early whether to track upstream changes or treat this as an independent fork. Recommendation: independent fork with cherry-picked fixes, since the Linux capture and timer layers will diverge significantly.

# Building the AutoSplit64 AppImage

`build_appimage.sh` produces a single self-contained `AutoSplit64-*.AppImage`
that bundles its own Python 3.12, all dependencies, and the Qt support
libraries. End users just download it, `chmod +x`, and run — no Python, no venv,
no system packages.

## Quick start

```bash
# Portable build (recommended) — runs on Debian 12, Ubuntu 20.04+, Arch, Fedora…
sudo pacman -S podman          # Arch     (one-time; rootless, no daemon)
# sudo apt install podman      # Debian/Ubuntu
./packaging/build_appimage.sh

# → dist/AutoSplit64-<version>-x86_64.AppImage
```

That's the whole workflow: install `podman` once, then run the script whenever
you want a fresh build. The result lands in `dist/`.

## Why a container?

A Linux binary carries a **minimum glibc version equal to the system it was
built on**, and glibc is only forward-compatible (build-old → run-new, never the
reverse). Arch and current Mint/Ubuntu ship a *newer* glibc than Debian 12, so a
build made directly on them would refuse to start on Debian 12.

To avoid that, the default build runs inside `quay.io/pypa/manylinux_2_28`
(glibc **2.28**, ~2019). The container is created, used, and discarded
automatically — you never interact with it. The AppImage it produces runs on
essentially every current Linux distro.

## Options

| Command | Effect |
|---------|--------|
| `./packaging/build_appimage.sh` | Portable build in a container (default). |
| `./packaging/build_appimage.sh --native` | Build directly on this host. Fast, needs no container, but the AppImage then requires a glibc **≥ this host's** — not portable to older distros. Handy for quick local testing. |
| `./packaging/build_appimage.sh --engine docker` | Force Docker (default auto-detects podman then docker). |
| `./packaging/build_appimage.sh -o DIR` | Output directory for `--native` builds (container builds always write to `dist/`). |

## What the build does

1. Downloads a relocatable CPython 3.12 (astral-sh/python-build-standalone).
2. `pip install`s the pinned **runtime** deps from `requirements.txt`
   (`pyinstaller` is skipped — it's only for the Windows `.exe`).
3. Copies the application tree into the AppDir.
4. Bundles the Qt **xcb** support libraries (notably `libxcb-cursor`) that are
   commonly missing on target systems. Base X11/OpenGL/glibc libraries are
   assumed present on any desktop and are intentionally not bundled.
5. Packages the AppDir with `appimagetool`.

User config/logs/generated templates are written to `~/.config/autosplit64`
and `~/.local/share/autosplit64` (XDG), never into the read-only AppImage — see
`as64core/paths.py`.

## Troubleshooting

- **`could not load the Qt platform plugin "xcb"`** on some target machine:
  a support lib is missing. Add its `.so` name to the `XCB_LIBS` list at the top
  of `build_appimage.sh` and rebuild. Running the AppImage with
  `QT_DEBUG_PLUGINS=1` prints which library failed to load.
- **No container engine found**: install `podman` (or `docker`), or use
  `--native` if you only need it to run on machines as new as this one.
- **Behind a proxy / no network**: the build downloads Python, the wheels, and
  `appimagetool`, so it needs internet access (or a configured proxy).

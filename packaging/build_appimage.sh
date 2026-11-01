#!/usr/bin/env bash
#
# Build an AutoSplit64 AppImage.
#
# By default this runs the build inside an old-glibc container
# (quay.io/pypa/manylinux_2_28_x86_64, glibc 2.28) so the resulting AppImage
# runs on any reasonably recent Linux -- Debian 12, Ubuntu 20.04+, Arch,
# Fedora, etc. -- regardless of how new the machine you build on is. The build
# is self-contained: it downloads a relocatable CPython 3.12, pip-installs the
# pinned runtime dependencies, and packages everything with appimagetool.
#
# Usage:
#   ./packaging/build_appimage.sh                 # portable build (container)
#   ./packaging/build_appimage.sh --native        # build on this host (fast; not portable)
#   ./packaging/build_appimage.sh --engine docker # force docker (default: auto podman/docker)
#   ./packaging/build_appimage.sh -o /tmp/out     # output directory (default: dist/)
#
# Requirements:
#   container build : podman or docker, plus network access
#   --native build  : a C library host new enough is fine, plus network access;
#                     the AppImage then requires glibc >= this host's.
#
set -euo pipefail

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
PY_SERIES="3.12"                                   # bundled Python series
BUILD_IMAGE="quay.io/pypa/manylinux_2_28_x86_64"   # old-glibc build base
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
PBS_API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"

# xcb / xkb support libraries Qt's "xcb" platform plugin dlopen()s at runtime.
# These are the ones commonly ABSENT on target systems (libxcb-cursor above all);
# base X11/GL/glibc libraries are assumed present on any X11 desktop and are
# deliberately NOT bundled.
XCB_LIBS=(
  libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1
  libxcb-randr.so.0 libxcb-render-util.so.0 libxcb-shape.so.0 libxcb-shm.so.0
  libxcb-sync.so.1 libxcb-xfixes.so.0 libxcb-xinerama.so.0 libxcb-xkb.so.1
  libxcb-util.so.1 libxkbcommon.so.0 libxkbcommon-x11.so.0
)

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OUTPUT_DIR="$REPO_DIR/dist"
MODE="container"       # container | native | _build (internal)
ENGINE=""

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --native)   MODE="native"; shift ;;
    --_build)   MODE="_build"; shift ;;   # internal: the actual build, in-place
    --engine)   ENGINE="${2:-}"; shift 2 ;;
    -o|--output) OUTPUT_DIR="$(cd "$(dirname "${2:?}")" 2>/dev/null && pwd)/$(basename "${2}")"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

# ----------------------------------------------------------------------------
# The actual build (runs on the host for --native, or inside the container)
# ----------------------------------------------------------------------------
do_build() {
  command -v curl >/dev/null || die "curl is required"
  local work="$REPO_DIR/build/appimage"
  local appdir="$work/AppDir"
  rm -rf "$work"
  mkdir -p "$appdir/usr" "$appdir/usr/lib" "$OUTPUT_DIR"

  # --- 1. In-container only: install the xcb support libs we bundle ---------
  if [[ "${IN_CONTAINER:-0}" == "1" ]] && command -v dnf >/dev/null; then
    log "Installing xcb/xkb support libraries in the build container"
    dnf -y -q install \
      xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms \
      xcb-util-renderutil libxkbcommon-x11 mesa-libGL fontconfig \
      >/dev/null 2>&1 || warn "some support packages failed to install"
  fi

  # --- 2. Relocatable CPython 3.12 -----------------------------------------
  log "Resolving latest python-build-standalone ${PY_SERIES} (install_only)"
  local pbs_url
  # Pick the plain baseline x86_64 install_only build (not the _v2/_v3/_v4
  # micro-arch variants, not _stripped). The download URL encodes '+' as %2B.
  pbs_url="$(curl -fsSL "$PBS_API" \
    | grep -o 'https://[^"]*cpython-'"${PY_SERIES}"'\.[0-9][0-9]*%2B[0-9][0-9]*-x86_64-unknown-linux-gnu-install_only\.tar\.gz' \
    | sort -u | head -1)"
  [[ -n "$pbs_url" ]] || die "could not find a CPython ${PY_SERIES} install_only build"
  log "Downloading $(basename "$pbs_url")"
  curl -fsSL "$pbs_url" -o "$work/python.tar.gz"
  mkdir -p "$appdir/usr/python"
  # install_only tarballs unpack to a top-level "python/" dir
  tar -xzf "$work/python.tar.gz" -C "$appdir/usr" # -> usr/python/
  local py="$appdir/usr/python/bin/python3"
  [[ -x "$py" ]] || die "bundled python not found after extract"

  # --- 3. Runtime dependencies (no pyinstaller; it's build-only) ------------
  log "Installing runtime dependencies into the bundle"
  grep -vi 'pyinstaller' "$REPO_DIR/requirements.txt" > "$work/requirements.txt"
  "$py" -m pip install --no-cache-dir --upgrade pip >/dev/null
  "$py" -m pip install --no-cache-dir -r "$work/requirements.txt"

  # --- 4. Application tree --------------------------------------------------
  log "Copying the application"
  mkdir -p "$appdir/usr/app"
  local items=(AutoSplit64.py as64core as64gui as64processes logic \
               resources routes templates defaults.ini LICENSE)
  for item in "${items[@]}"; do
    [[ -e "$REPO_DIR/$item" ]] && cp -r "$REPO_DIR/$item" "$appdir/usr/app/" \
      || warn "skipping missing item: $item"
  done
  # Drop any copied bytecode/venv cruft.
  find "$appdir/usr/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

  # --- 5. Bundle the xcb/xkb support libs -----------------------------------
  log "Bundling Qt xcb support libraries"
  local search=(/usr/lib64 /usr/lib /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu)
  local found=0 missing=()
  for lib in "${XCB_LIBS[@]}"; do
    local src=""
    for d in "${search[@]}"; do
      if [[ -e "$d/$lib" ]]; then src="$d/$lib"; break; fi
    done
    if [[ -n "$src" ]]; then cp -L "$src" "$appdir/usr/lib/"; found=$((found+1));
    else missing+=("$lib"); fi
  done
  log "Bundled $found support libs"
  [[ ${#missing[@]} -gt 0 ]] && warn "not found on build host (may still be ok): ${missing[*]}"

  # --- 6. AppDir metadata ---------------------------------------------------
  log "Assembling AppDir metadata"
  install -m 0755 "$SCRIPT_DIR/AppRun" "$appdir/AppRun"
  install -m 0644 "$SCRIPT_DIR/autosplit64.desktop" "$appdir/autosplit64.desktop"
  mkdir -p "$appdir/usr/share/applications" \
           "$appdir/usr/share/icons/hicolor/256x256/apps"
  cp "$SCRIPT_DIR/autosplit64.desktop" "$appdir/usr/share/applications/"
  local icon="$REPO_DIR/resources/gui/icons/as64plus.png"
  if [[ -f "$icon" ]]; then
    cp "$icon" "$appdir/autosplit64.png"
    cp "$icon" "$appdir/usr/share/icons/hicolor/256x256/apps/autosplit64.png"
  else
    warn "app icon not found: $icon"
  fi

  # --- 7. Package with appimagetool ----------------------------------------
  log "Fetching appimagetool"
  curl -fsSL "$APPIMAGETOOL_URL" -o "$work/appimagetool"
  chmod +x "$work/appimagetool"
  local version; version="$(cd "$REPO_DIR" && git describe --tags --always 2>/dev/null || echo dev)"
  local out="$OUTPUT_DIR/AutoSplit64-${version}-x86_64.AppImage"
  log "Packaging -> $out"
  ( cd "$work" && ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 VERSION="$version" \
      ./appimagetool --no-appstream "$appdir" "$out" )
  chmod +x "$out"
  log "Done: $out"
}

# ----------------------------------------------------------------------------
# Container orchestration
# ----------------------------------------------------------------------------
pick_engine() {
  if [[ -n "$ENGINE" ]]; then command -v "$ENGINE" >/dev/null || die "engine not found: $ENGINE"; echo "$ENGINE"; return; fi
  if command -v podman >/dev/null; then echo podman; return; fi
  if command -v docker >/dev/null; then echo docker; return; fi
  die "no container engine found. Install podman (recommended) or docker, or use --native.
  Arch:   sudo pacman -S podman
  Debian: sudo apt install podman"
}

run_in_container() {
  local engine; engine="$(pick_engine)"
  log "Building in $engine using $BUILD_IMAGE (portable / old-glibc)"
  mkdir -p "$OUTPUT_DIR"
  # :Z relabels the mount for SELinux hosts (Fedora/Arch w/ SELinux); harmless elsewhere.
  # The container mounts the repo at /src, so the build writes to /src/dist,
  # which is the host's dist/. (Custom -o is honoured by --native builds; a
  # container build always lands in the repo's dist/.)
  "$engine" run --rm \
    -v "$REPO_DIR:/src:Z" \
    -w /src \
    -e IN_CONTAINER=1 \
    "$BUILD_IMAGE" \
    bash /src/packaging/build_appimage.sh --_build
}

# ----------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------
case "$MODE" in
  container) run_in_container ;;
  native)    log "Native build (AppImage will require glibc >= this host's)"; do_build ;;
  _build)    do_build ;;
esac

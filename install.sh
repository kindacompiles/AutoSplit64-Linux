#!/usr/bin/env bash
#
# AutoSplit64+ (Linux port) — one-shot installer.
#
#   curl -sSL https://raw.githubusercontent.com/kindacompiles/AutoSplit64-Linux/main/install.sh | bash
#
# It can do any combination of:
#   1. Install the app (downloads the latest AppImage + a menu entry).
#   2. Build & install the OBS frame-grabber plugin for your OBS.
#
# Everything is per-user by default (no root) except installing build
# dependencies, which uses sudo and always asks first. Re-running is safe.
#
# Non-interactive use (CI, no TTY): set these env vars instead of answering
# prompts:  AS64_DO_APP=1  AS64_DO_PLUGIN=1  AS64_ASSUME_YES=1
set -euo pipefail

# --- config ------------------------------------------------------------------
REPO="kindacompiles/AutoSplit64-Linux"
BRANCH="main"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
APP_NAME="AutoSplit64"
BIN_DIR="${HOME}/.local/bin"
APPIMAGE_PATH="${BIN_DIR}/${APP_NAME}.AppImage"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
PLUGIN_SLUG="autosplit64plus-framegrabber"
SO_NAME="autosplit64plus-framegrabber.so"

# --- pretty output -----------------------------------------------------------
if [ -t 1 ]; then
    B=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; RST=$'\033[0m'
else
    B=''; DIM=''; GRN=''; YEL=''; RED=''; RST=''
fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s==>%s %s\n' "$B" "$RST" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s  !!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s error:%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

# Read a prompt even when the script itself is coming in on stdin (curl | bash).
TTY=/dev/tty
have_tty() { [ -e "$TTY" ] && { exec 9<"$TTY"; } 2>/dev/null; }
ask_yn() { # ask_yn "Question" default(y/n) -> returns 0 for yes
    local q="$1" def="${2:-y}" ans
    if [ "${AS64_ASSUME_YES:-0}" = "1" ]; then return 0; fi
    if ! have_tty; then
        [ "$def" = "y" ]; return
    fi
    local hint="[Y/n]"; [ "$def" = "n" ] && hint="[y/N]"
    printf '%s %s ' "$q" "$hint" >&2
    read -r ans <&9 || ans=""
    exec 9<&-
    ans="${ans:-$def}"
    case "$ans" in [Yy]*) return 0;; *) return 1;; esac
}

# --- distro / package manager ------------------------------------------------
PKG=""; INSTALL_CMD=""; DEPS=""
detect_pkg() {
    if   command -v apt-get >/dev/null 2>&1; then
        PKG=apt;    INSTALL_CMD="sudo apt-get install -y"
        DEPS="git cmake build-essential pkg-config libobs-dev"
    elif command -v dnf >/dev/null 2>&1; then
        PKG=dnf;    INSTALL_CMD="sudo dnf install -y"
        DEPS="git cmake gcc gcc-c++ pkgconf-pkg-config obs-studio-devel"
    elif command -v pacman >/dev/null 2>&1; then
        PKG=pacman; INSTALL_CMD="sudo pacman -S --needed --noconfirm"
        DEPS="git cmake base-devel pkgconf obs-studio"
    elif command -v zypper >/dev/null 2>&1; then
        PKG=zypper; INSTALL_CMD="sudo zypper install -y"
        DEPS="git cmake gcc gcc-c++ pkgconf obs-studio-devel"
    else
        PKG=""
    fi
}

# --- app (AppImage) ----------------------------------------------------------
install_app() {
    step "Installing the ${APP_NAME} app"
    command -v curl >/dev/null 2>&1 || die "curl is required."

    local api="https://api.github.com/repos/${REPO}/releases/latest"
    say "${DIM}Looking up the latest release...${RST}"
    local url
    url="$(curl -fsSL "$api" 2>/dev/null \
        | grep -o '"browser_download_url": *"[^"]*\.AppImage"' \
        | head -n1 | sed -E 's/.*"(https[^"]+)"/\1/')" || true
    [ -n "$url" ] || die "No .AppImage asset found in the latest release of ${REPO}.
       Check https://github.com/${REPO}/releases — the release may still be building."

    mkdir -p "$BIN_DIR"
    say "Downloading $(basename "$url")"
    curl -fL --progress-bar "$url" -o "${APPIMAGE_PATH}.part" || die "download failed."
    mv -f "${APPIMAGE_PATH}.part" "$APPIMAGE_PATH"
    chmod +x "$APPIMAGE_PATH"
    ok "App installed at ${APPIMAGE_PATH}"

    # Desktop entry + icon (best effort).
    mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
    if curl -fsSL "${RAW}/resources/gui/icons/as64plus.png" -o "${ICON_DIR}/autosplit64.png" 2>/dev/null; then
        ok "Icon installed"
    else
        warn "Could not fetch the icon (menu entry will use a generic one)."
    fi
    cat > "${DESKTOP_DIR}/autosplit64.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AutoSplit64+
GenericName=SM64 Auto Splitter
Comment=Image-recognition auto-splitter for Super Mario 64 speedruns
Exec=${APPIMAGE_PATH}
Icon=autosplit64
Categories=Utility;Game;
Terminal=false
EOF
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    ok "Menu entry created (look for \"AutoSplit64+\")"

    case ":$PATH:" in
        *":$BIN_DIR:"*) say "${DIM}Run it with: ${APP_NAME}.AppImage${RST}";;
        *) warn "${BIN_DIR} is not on your PATH — launch from the menu, or run:
       ${APPIMAGE_PATH}";;
    esac
}

# --- OBS plugin --------------------------------------------------------------
ensure_build_deps() {
    # Only install what's missing.
    local need=0
    command -v cmake >/dev/null 2>&1 || need=1
    command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || need=1
    pkg-config --exists libobs 2>/dev/null || need=1
    [ "$need" = "0" ] && { ok "Build tools and OBS headers already present."; return 0; }

    if [ -z "$PKG" ]; then
        warn "Unknown package manager — install these yourself, then re-run:"
        say  "    cmake, a C/C++ compiler, pkg-config, and the OBS dev headers (libobs)"
        die  "missing build dependencies."
    fi
    say "Build dependencies are needed:"
    say "    ${B}${INSTALL_CMD} ${DEPS}${RST}"
    if ask_yn "Install them now (uses sudo)?" y; then
        # shellcheck disable=SC2086
        $INSTALL_CMD $DEPS || die "dependency install failed."
        ok "Dependencies installed."
    else
        die "can't build the plugin without the dependencies."
    fi
}

locate_source() {
    # Prefer a repo we're already inside; otherwise clone a fresh copy.
    local d
    for d in "$PWD" "$(dirname "$0")"; do
        if [ -f "${d}/obs-plugin/linux/build.sh" ]; then
            SRC_DIR="$(cd "$d" && pwd)"; SRC_TMP=0; return 0
        fi
    done
    command -v git >/dev/null 2>&1 || die "git is required to fetch the plugin source."
    SRC_DIR="$(mktemp -d)"; SRC_TMP=1
    say "${DIM}Cloning plugin source...${RST}"
    git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$SRC_DIR" >/dev/null 2>&1 \
        || die "git clone failed."
}

pick_obs_plugin_dir() {
    # Detect Flatpak OBS vs native and choose a per-user plugin dir.
    local flatpak_cfg="${HOME}/.var/app/com.obsproject.Studio/config/obs-studio"
    local native_cfg="${HOME}/.config/obs-studio"
    local has_flatpak=0 has_native=0
    { command -v flatpak >/dev/null 2>&1 && flatpak info com.obsproject.Studio >/dev/null 2>&1; } && has_flatpak=1
    [ -d "$flatpak_cfg" ] && has_flatpak=1
    command -v obs >/dev/null 2>&1 && has_native=1
    [ -d "$native_cfg" ] && has_native=1

    local choice="native"
    if [ "$has_flatpak" = "1" ] && [ "$has_native" = "1" ]; then
        say "Both Flatpak and native OBS look installed."
        if ask_yn "Install into the Flatpak OBS? (No = native OBS)" n; then choice=flatpak; fi
    elif [ "$has_flatpak" = "1" ]; then
        choice=flatpak
    elif [ "$has_native" = "1" ]; then
        choice=native
    else
        warn "OBS doesn't appear to be installed yet — assuming native OBS."
    fi

    if [ "$choice" = "flatpak" ]; then
        OBS_PLUGIN_DIR="${flatpak_cfg}/plugins/${PLUGIN_SLUG}/bin/64bit"
    else
        OBS_PLUGIN_DIR="${native_cfg}/plugins/${PLUGIN_SLUG}/bin/64bit"
    fi
}

install_plugin() {
    step "Building the OBS frame-grabber plugin"
    ensure_build_deps
    locate_source
    pick_obs_plugin_dir

    local here="${SRC_DIR}/obs-plugin/linux"
    say "${DIM}Compiling...${RST}"
    ( cd "$here" && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null && cmake --build build --parallel >/dev/null ) \
        || die "plugin build failed (see the output above)."
    local so="${here}/build/${SO_NAME}"
    [ -f "$so" ] || die "build finished but ${SO_NAME} wasn't produced."
    ok "Compiled ${SO_NAME}"

    mkdir -p "$OBS_PLUGIN_DIR"
    cp -f "$so" "$OBS_PLUGIN_DIR/"
    ok "Installed to ${OBS_PLUGIN_DIR}"

    [ "${SRC_TMP:-0}" = "1" ] && rm -rf "$SRC_DIR"

    say ""
    say "${B}Next, in OBS:${RST}"
    say "  1. Restart OBS."
    say "  2. Right-click your SM64 video source -> Filters."
    say "  3. Add ${B}AS64+ Frame grabber${RST} under Effect Filters."
    say "  4. In AutoSplit64, set the capture method to OBS."
}

# --- main --------------------------------------------------------------------
main() {
    say "${B}AutoSplit64+ (Linux port) installer${RST}"
    detect_pkg
    [ -n "$PKG" ] && say "${DIM}Detected package manager: ${PKG}${RST}" \
                  || say "${DIM}Unknown package manager — plugin deps must be installed manually.${RST}"

    local do_app="${AS64_DO_APP:-}" do_plugin="${AS64_DO_PLUGIN:-}"
    if [ -z "$do_app" ] && [ -z "$do_plugin" ]; then
        say ""
        say "What would you like to do?"
        say "  ${B}1${RST}) Install the app only (AppImage + menu entry)"
        say "  ${B}2${RST}) Build & install the OBS plugin only"
        say "  ${B}3${RST}) Both  ${DIM}(recommended)${RST}"
        local sel="3"
        if [ "${AS64_ASSUME_YES:-0}" != "1" ] && have_tty; then
            printf 'Choice [3]: ' >&2; read -r sel <&9 || sel=3; exec 9<&-
        fi
        case "${sel:-3}" in
            1) do_app=1; do_plugin=0;;
            2) do_app=0; do_plugin=1;;
            *) do_app=1; do_plugin=1;;
        esac
    fi
    : "${do_app:=0}"; : "${do_plugin:=0}"

    [ "$do_app" = "1" ]    && install_app
    [ "$do_plugin" = "1" ] && install_plugin

    step "Done."
    [ "$do_app" = "1" ] && say "Launch ${B}AutoSplit64+${RST} from your app menu or ${APPIMAGE_PATH}"
    say "Setup help: https://github.com/${REPO}#readme"
}

main "$@"

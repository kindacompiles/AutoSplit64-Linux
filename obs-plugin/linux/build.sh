#!/usr/bin/env bash
# Build the AutoSplit64+ OBS frame-grabber plugin on Linux.
#
# Usage: ./build.sh        (from obs-plugin/linux/, or anywhere)
#
# Produces: obs-plugin/linux/build/autosplit64plus-framegrabber.so
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"

if ! command -v cmake >/dev/null 2>&1; then
    echo "error: cmake is required (e.g. 'sudo apt install cmake')" >&2
    exit 1
fi

if ! pkg-config --exists libobs; then
    echo "error: libobs development files not found." >&2
    echo "  Debian/Ubuntu: sudo apt install libobs-dev" >&2
    echo "  Fedora:        sudo dnf install obs-studio-devel" >&2
    echo "  Arch:          pacman -S obs-studio" >&2
    exit 1
fi

cmake -S "$HERE" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" --parallel

echo
echo "Built: $BUILD/autosplit64plus-framegrabber.so"
echo "See $HERE/README.md for where to install it."

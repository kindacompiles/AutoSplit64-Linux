# AutoSplit64+ OBS frame-grabber — Linux build

This plugin is an OBS **source filter**. Add it to the video source that shows
your SM64 feed; it copies every rendered frame into a POSIX shared-memory
segment (`/dev/shm/as64_grabber`) that AutoSplit64 reads.

## Build

```bash
./build.sh
# or manually:
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

Dependencies: `cmake`, a C compiler, and the OBS development headers
(`libobs-dev` on Debian/Ubuntu, `obs-studio-devel` on Fedora, `obs-studio` on
Arch). The build produces `build/autosplit64plus-framegrabber.so`.

## Install

Copy the `.so` into an OBS plugin directory, then restart OBS.

**System / distro OBS** — either of:

```bash
# per-user (no root)
mkdir -p ~/.config/obs-studio/plugins/autosplit64plus-framegrabber/bin/64bit
cp build/autosplit64plus-framegrabber.so \
   ~/.config/obs-studio/plugins/autosplit64plus-framegrabber/bin/64bit/
```

or system-wide into your distro's OBS plugin dir, commonly
`/usr/lib/x86_64-linux-gnu/obs-plugins/` or `/usr/lib/obs-plugins/`.

**Flatpak OBS:**

```bash
mkdir -p ~/.var/app/com.obsproject.Studio/config/obs-studio/plugins/autosplit64plus-framegrabber/bin/64bit
cp build/autosplit64plus-framegrabber.so \
   ~/.var/app/com.obsproject.Studio/config/obs-studio/plugins/autosplit64plus-framegrabber/bin/64bit/
```

> The Flatpak build must have been compiled against a compatible OBS SDK. If
> the filter does not appear, check OBS's log (Help → Log Files) for a load
> error and confirm the OBS major version matches what you built against.

## Use

1. In OBS, right-click your SM64 video source → **Filters**.
2. Add **AS64+ Frame grabber** under *Effect Filters*.
3. Only one instance is allowed; adding a second shows an error in the filter
   properties.
4. In AutoSplit64, set capture method to **OBS** (`capture_method: "obs"`).

When the filter is removed or OBS closes, the plugin unlinks
`/dev/shm/as64_grabber` so no stale segment is left behind.

## Attribution

The POSIX shared-memory port (the `#else` branches in
`../src/autosplit64plus-framegrabber.c`) follows the approach pioneered by the
Linux forks **SmolAlli/AutoSplit64plusLinux** and **Poke711/AutoSplit64plusLinux**,
rewritten here with a proper `shm_unlink` on close. The plugin itself is from
**DaviBe92/AutoSplit64plus**. Licensed GPLv3.

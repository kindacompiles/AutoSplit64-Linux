"""Reader for the OBS frame-grabber plugin's shared-memory segment.

The plugin (``obs-plugin/src/autosplit64plus-framegrabber.c``) publishes each
rendered frame into a shared-memory segment named ``as64_grabber`` with a
16-byte header of four little-endian ``uint32`` values::

    [0] width       (pixels)
    [1] height      (pixels)
    [2] linesize    (bytes per row; the plugin always packs this to width*4)
    [3] frame_counter

followed by ``height * linesize`` bytes of BGRA pixels. A header of
``0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF`` is the plugin's "closing" sentinel.

Two platform backends share that protocol:

* **Windows** uses a named file mapping (``OpenFileMappingW`` + ``mmap`` with a
  ``tagname``) — the original code path, preserved here behind ``sys.platform``.
* **Linux/POSIX** reads ``/dev/shm/as64_grabber`` directly. The plugin creates
  it with ``shm_open("/as64_grabber", ...)``, which surfaces at that path. No
  Win32/ctypes calls are involved.

The POSIX reader re-opens the segment when OBS recreates it (resolution change
or OBS restart), detected by a change of inode or required size, so it does not
re-map the header on every frame.
"""

import sys
import mmap

import numpy as np

SHMEM_NAME = "as64_grabber"
POSIX_SHMEM_PATH = "/dev/shm/" + SHMEM_NAME
_HEADER_BYTES = 16
_SENTINEL = 0xFFFFFFFF

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    import ctypes

    FILE_MAP_READ = 0x0004


class SharedMemoryCapture(object):
    def __init__(self):
        self.width = 0
        self.height = 0
        self.linesize = 0
        self.shmem_size = 0

        # Windows backend state
        self.shmem_handle = None
        self.shmem = None

        # POSIX backend state
        self._fd = -1
        self._mm = None
        self._ino = None

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_header(raw):
        header = np.frombuffer(raw, dtype=np.uint32, count=4)
        return int(header[0]), int(header[1]), int(header[2])

    def _decode_frame(self, raw):
        """Turn a full ``header + pixels`` buffer into an (H, W, 3) BGR array."""
        if len(raw) != self.shmem_size:
            raise Exception("Incomplete data read from shared memory")

        pixels = np.frombuffer(raw, dtype=np.uint8, offset=_HEADER_BYTES)
        expected = self.height * self.width * 4
        if len(pixels) != expected:
            raise Exception(f"Data size mismatch: got {len(pixels)}, expected {expected}")

        # Drop the alpha channel; return a contiguous BGR frame for OpenCV.
        return np.ascontiguousarray(pixels.reshape(self.height, self.width, 4)[:, :, :3])

    def _apply_dimensions(self, width, height, linesize):
        if width == _SENTINEL and height == _SENTINEL and linesize == _SENTINEL:
            raise Exception("OBS closed the connection")
        if width <= 0 or height <= 0 or linesize <= 0:
            raise Exception("Invalid dimensions reported by the OBS plugin")
        self.width = width
        self.height = height
        self.linesize = linesize
        self.shmem_size = _HEADER_BYTES + height * linesize

    # ================================================================== #
    # POSIX (Linux) backend
    # ================================================================== #
    def _posix_map(self):
        import os

        size = os.fstat(self._fd).st_size
        if size < _HEADER_BYTES:
            raise Exception("Shared memory segment is too small / not ready yet")
        self._mm = mmap.mmap(self._fd, size, prot=mmap.PROT_READ)
        self._ino = os.fstat(self._fd).st_ino

    def _posix_open(self):
        import os

        if self._mm is not None:
            return True
        try:
            self._fd = os.open(POSIX_SHMEM_PATH, os.O_RDONLY)
        except FileNotFoundError:
            raise Exception(
                "Could not find OBS Grabber Plugin!\n\n"
                "Make sure the AS64+ Frame grabber filter is added to your source "
                "and OBS is running."
            )
        try:
            self._posix_map()
        except Exception:
            os.close(self._fd)
            self._fd = -1
            raise
        return True

    def _posix_close(self):
        import os

        if self._mm is not None:
            try:
                self._mm.close()
            except (ValueError, BufferError):
                pass
            self._mm = None
        if self._fd != -1:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = -1
        self._ino = None

    def _posix_ensure_fresh(self):
        """Reopen if OBS recreated the segment (new inode) or it vanished."""
        import os

        if self._mm is None:
            self._posix_open()
            return
        try:
            st = os.stat(POSIX_SHMEM_PATH)
        except FileNotFoundError:
            self._posix_close()
            raise Exception("OBS closed the connection")
        if st.st_ino != self._ino:
            self._posix_close()
            self._posix_open()

    def _posix_read_header(self):
        self._posix_ensure_fresh()
        width, height, linesize = self._parse_header(self._mm[:_HEADER_BYTES])
        self._apply_dimensions(width, height, linesize)
        # Grow the mapping if the segment got bigger (resolution increase).
        if self.shmem_size > len(self._mm):
            self._posix_close()
            self._posix_open()

    def _posix_capture(self):
        self._posix_read_header()
        return self._decode_frame(self._mm[: self.shmem_size])

    def _posix_capture_size(self):
        self._posix_read_header()
        return int(self.width), int(self.height)

    # ================================================================== #
    # Windows backend (original behaviour, preserved)
    # ================================================================== #
    def _win_open(self):
        if self.shmem_handle:
            return True
        self.shmem_handle = ctypes.windll.kernel32.OpenFileMappingW(FILE_MAP_READ, False, SHMEM_NAME)
        if not self.shmem_handle:
            raise Exception(
                "Could not find OBS Grabber Plugin!\n\n"
                "Please make sure the plugin is enabled and OBS is running."
            )
        self._win_update_dimensions()
        self.shmem = mmap.mmap(-1, self.shmem_size, tagname=SHMEM_NAME, access=mmap.ACCESS_READ)
        return True

    def _win_close(self):
        try:
            if self.shmem is not None:
                self.shmem.close()
                self.shmem = None
        except ValueError:
            self.shmem = None
        if self.shmem_handle:
            ctypes.windll.kernel32.CloseHandle(self.shmem_handle)
            self.shmem_handle = None

    def _win_update_dimensions(self):
        if not self.shmem_handle:
            self._win_open()
        shmem_header = mmap.mmap(-1, _HEADER_BYTES, tagname=SHMEM_NAME)
        shmem_header.seek(0)
        width, height, linesize = self._parse_header(shmem_header.read(_HEADER_BYTES))
        shmem_header.close()

        if width != self.width or height != self.height or linesize != self.linesize:
            self._apply_dimensions(width, height, linesize)
            if self.shmem:
                self.shmem.close()
                self.shmem = mmap.mmap(-1, self.shmem_size, tagname=SHMEM_NAME, access=mmap.ACCESS_READ)

    def _win_capture(self):
        self._win_update_dimensions()
        if not self.shmem:
            raise Exception("Shared memory not initialized")
        self.shmem.seek(0)
        return self._decode_frame(self.shmem.read(self.shmem_size))

    def _win_capture_size(self):
        self._win_update_dimensions()
        return int(self.width), int(self.height)

    # ================================================================== #
    # Public API (dispatches to the active backend)
    # ================================================================== #
    def open_shmem(self):
        return self._win_open() if _IS_WIN else self._posix_open()

    def close_shmem(self):
        return self._win_close() if _IS_WIN else self._posix_close()

    def get_capture_size(self):
        return self._win_capture_size() if _IS_WIN else self._posix_capture_size()

    def capture(self):
        return self._win_capture() if _IS_WIN else self._posix_capture()


def test_capture():
    """Interactive smoke test: press 'w' to grab a frame, 'q' to quit."""
    import time
    import cv2

    cap = SharedMemoryCapture()
    try:
        cap.open_shmem()
        width, height = cap.get_capture_size()
        print(f"Capture size: {width}x{height}")

        cv2.namedWindow("Capture Test", cv2.WINDOW_NORMAL)
        frame = None
        while True:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("w"):
                start = time.time()
                frame = cap.capture()
                print(f"New frame captured in {(time.time() - start) * 1000:.2f} ms")
            if frame is not None:
                cv2.imshow("Capture Test", frame)
            if key == ord("q"):
                break
    finally:
        cv2.destroyAllWindows()
        cap.close_shmem()


if __name__ == "__main__":
    test_capture()

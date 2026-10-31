"""Direct capture-card backend using Video4Linux2 via OpenCV.

Capture cards (e.g. the EVGA XR1 Lite) expose themselves as ``/dev/video*``
nodes on Linux. OpenCV's ``VideoCapture`` with the V4L2 backend reads frames
from them directly, with no OBS involved, delivering a standard BGR ``numpy``
array ready for the recognition engine.

This is the "no OBS" fallback path selected by ``capture_method: "v4l2"``.
It has no Windows counterpart.
"""

import glob
import os
import re

import cv2


def _device_sort_key(path):
    m = re.search(r"(\d+)$", path)
    return (int(m.group(1)) if m else 1 << 30, path)


class V4L2Capture(object):
    def __init__(self, device="/dev/video0", width=0, height=0):
        self._device = device
        self._req_width = int(width) if width else 0
        self._req_height = int(height) if height else 0
        self._cap = None
        self.width = 0
        self.height = 0

    def open(self):
        if self._cap is not None and self._cap.isOpened():
            return True

        if not os.path.exists(self._device):
            raise Exception(
                f"Capture device {self._device} does not exist.\n\n"
                "Plug in the capture card and check the device path "
                "(it is usually /dev/video0)."
            )

        cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            raise Exception(
                f"Could not open capture device {self._device}.\n\n"
                "Another program may be using it, or your user may lack "
                "permission (try adding yourself to the 'video' group)."
            )

        if self._req_width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._req_width)
        if self._req_height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._req_height)

        self._cap = cap
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return True

    def capture(self):
        if self._cap is None:
            self.open()

        ret, frame = self._cap.read()
        if not ret or frame is None:
            raise Exception(f"Failed to read a frame from {self._device}")

        # OpenCV already delivers BGR; keep dimensions in sync with the driver.
        self.height, self.width = frame.shape[:2]
        return frame

    def get_capture_size(self):
        if self._cap is None:
            self.open()
        return int(self.width), int(self.height)

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @staticmethod
    def list_devices():
        """Return available ``/dev/video*`` device paths, numerically sorted.

        Note: a capture card often exposes several nodes (the first is usually
        the one that yields frames); the user picks the right one in the GUI.
        """
        return sorted(glob.glob("/dev/video*"), key=_device_sort_key)

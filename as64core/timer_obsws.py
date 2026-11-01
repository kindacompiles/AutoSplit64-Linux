"""Timer backend that drives the OBS LiveSplit One plugin over OBS WebSocket.

The obs-livesplit-one plugin has no control protocol of its own; it is driven
through OBS. OBS 28+ ships obs-websocket v5 (default ``localhost:4455``), and
the LiveSplit One source registers named hotkeys that we fire with the
``TriggerHotkeyByName`` request:

    split  -> hotkey_split   (also starts the timer if it is stopped)
    reset  -> hotkey_reset
    undo   -> hotkey_undo
    skip   -> hotkey_skip
    pause  -> hotkey_pause

These are the plugin's *internal* hotkey names, so the user does not have to
bind any physical keys in OBS. There is no separate "start"; a split on a
stopped timer starts it (start-or-split), which matches the TCP client's
``startorsplit`` behaviour.

Note: the hotkey path is effectively one-way. Unlike the TCP LiveSplit Server
protocol, OBS WebSocket cannot read the current split index back from the
LiveSplit One plugin. Instead this backend tracks its *own* split index,
mirroring LiveSplit's ``getsplitindex`` semantics by counting the hotkeys it
fires (-1 = timer not running; the first start-or-split makes it 0; each
further split/skip increments; undo decrements; reset returns to -1). The app's
main loop reads this back exactly as it does the TCP index, which is what drives
the route position forward. The only limitation is that split changes the user
makes *manually* in LiveSplit (not via AutoSplit64) cannot be observed, so the
tracked index can drift from LiveSplit if the user splits by hand mid-run.
"""

import time


# LiveSplit One internal hotkey names (registered by the obs-livesplit-one
# plugin for its source).
HOTKEY_SPLIT = "hotkey_split"
HOTKEY_RESET = "hotkey_reset"
HOTKEY_UNDO = "hotkey_undo"
HOTKEY_SKIP = "hotkey_skip"
HOTKEY_PAUSE = "hotkey_pause"


class OBSWebSocketTimer(object):
    def __init__(self, host="localhost", port=4455, password=""):
        self._host = host or "localhost"
        try:
            self._port = int(port)
        except (TypeError, ValueError):
            self._port = 4455
        self._password = password or ""
        self._client = None
        # Local mirror of LiveSplit's split index (-1 == timer not running),
        # since the plugin cannot report it back over OBS WebSocket. Updated
        # only after a hotkey actually fires (see the action methods).
        self._split_index = -1

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def connect(self):
        """Open the OBS WebSocket connection and verify a LiveSplit One source.

        Raises ``Exception`` with a user-facing message on any failure.
        """
        try:
            import obsws_python as obsws
        except ImportError:
            raise Exception(
                "The 'obsws-python' package is not installed.\n\n"
                "Install the app requirements (pip install -r requirements.txt) "
                "or run: pip install obsws-python"
            )

        try:
            self._client = obsws.ReqClient(
                host=self._host, port=self._port, password=self._password, timeout=3
            )
        except Exception as e:
            self._client = None
            raise Exception(
                f"Could not connect to OBS WebSocket at {self._host}:{self._port}.\n\n"
                "Make sure OBS is running and its WebSocket server is enabled "
                "(Tools -> WebSocket Server Settings), and that the host, port and "
                f"password are correct.\n\n({e})"
            )

        if not self.livesplit_source_name():
            raise Exception(
                "Connected to OBS, but no LiveSplit One source was found.\n\n"
                "Add a 'LiveSplit One' source in OBS (install the obs-livesplit-one "
                "plugin) before starting."
            )
        return self

    def livesplit_source_name(self):
        """Return the name of the first LiveSplit One input, or None."""
        if self._client is None:
            return None
        try:
            inputs = self._client.get_input_list().inputs
        except Exception:
            return None
        for inp in inputs:
            kind = str(inp.get("inputKind", "") or inp.get("unversionedInputKind", "")).lower()
            if "livesplit" in kind:
                return inp.get("inputName")
        return None

    def connected(self):
        if self._client is None:
            return False
        try:
            self._client.get_version()
            return True
        except Exception:
            return False

    def _reconnect(self):
        try:
            self.disconnect()
            self.connect()
            return True
        except Exception:
            return False

    def disconnect(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _trigger(self, hotkey_name):
        if self._client is None and not self._reconnect():
            raise Exception("LiveSplit (OBS) connection lost")
        try:
            self._client.trigger_hotkey_by_name(hotkey_name)
        except Exception:
            # OBS may have restarted; try one reconnect then retry once.
            if self._reconnect():
                self._client.trigger_hotkey_by_name(hotkey_name)
            else:
                raise Exception("LiveSplit (OBS) connection lost")

    def split(self):
        # start-or-split: the first press starts the timer (index 0), each
        # subsequent press advances a segment. Counter is bumped only after the
        # hotkey actually fires (a raised _trigger leaves the index untouched).
        self._trigger(HOTKEY_SPLIT)
        self._split_index += 1

    def reset(self):
        self._trigger(HOTKEY_RESET)
        self._split_index = -1

    def restart(self):
        # reset, then split starts a fresh run (start-or-split).
        self._trigger(HOTKEY_RESET)
        time.sleep(0.05)
        self._trigger(HOTKEY_SPLIT)
        self._split_index = 0

    def skip(self):
        self._trigger(HOTKEY_SKIP)
        self._split_index += 1

    def undo(self):
        self._trigger(HOTKEY_UNDO)
        if self._split_index > -1:
            self._split_index -= 1

    def pause(self):
        self._trigger(HOTKEY_PAUSE)

    def open_projector(self, geometry_b64=None):
        """Pop out a windowed projector for the LiveSplit One source.

        ``geometry_b64`` is a Qt ``saveGeometry()`` byte string, base64-encoded
        (the format OBS expects for a windowed projector). When given, the
        projector opens at that size/position; otherwise OBS places it. Raises
        with a user-facing message if there is no LiveSplit source or the call
        fails.
        """
        if self._client is None and not self._reconnect():
            raise Exception("LiveSplit (OBS) connection lost")
        source = self.livesplit_source_name()
        if not source:
            raise Exception("No LiveSplit One source found in OBS.")
        try:
            # monitor_index must be -1 for a windowed (geometry-based) projector.
            self._client.open_source_projector(
                source, monitor_index=-1, projector_geometry=geometry_b64
            )
        except Exception as e:
            raise Exception(f"Could not open the LiveSplit projector in OBS.\n\n({e})")

    def split_index(self):
        """Current split index mirror (-1 when the timer is not running)."""
        return self._split_index

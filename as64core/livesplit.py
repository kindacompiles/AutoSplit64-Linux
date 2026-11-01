import socket
import select
import sys
import time

# The named-pipe transport uses pywin32 and is Windows-only. Guard the import
# so the module loads on Linux; the Linux timer transport is implemented in
# Phase 2+. The TCP path (sockets) is already cross-platform.
if sys.platform == "win32":
    import win32file
    import win32pipe
else:
    win32file = None
    win32pipe = None

from . import config
from .timer_obsws import OBSWebSocketTimer

# Last connection error message (set by connect() so callers can show a clear
# reason instead of a generic one).
_last_connection_error = None


def connection_error():
    return _last_connection_error


# Connect to the timer and return a connection handle (TCP socket, Windows pipe
# handle, or an OBSWebSocketTimer). Returns False on failure.
def connect() -> object:
    global _last_connection_error
    _last_connection_error = None

    method = config.get("connection", "timer_method")

    if method == "obs_websocket":
        timer = OBSWebSocketTimer(
            config.get("connection", "obs_ws_host"),
            config.get("connection", "obs_ws_port"),
            config.get("connection", "obs_ws_password"),
        )
        try:
            timer.connect()
            return timer
        except Exception as e:
            _last_connection_error = str(e)
            return False

    return _connect_livesplit(force_tcp=(method == "livesplit_tcp"))


# Connect to the classic LiveSplit Server (TCP) or LiveSplit named pipe.
def _connect_livesplit(force_tcp=False) -> object:
    # Get connection type from config
    ls_connection_type = config.get("connection", "ls_connection_type")
    if force_tcp:
        ls_connection_type = 1

    # Check if connection type is named pipe (0 indicates named pipe)
    if ls_connection_type == 0:
        # Get named pipe host from config. Name is always LiveSplit
        ls_pipe_path = "\\\\" + config.get("connection", "ls_pipe_host") + "\\pipe\\LiveSplit"
        try:
            # Connect to named pipe
            ls_socket = win32file.CreateFile(ls_pipe_path, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, 0, None )
            # Set the pipe to byte mode
            win32pipe.SetNamedPipeHandleState(ls_socket, win32pipe.PIPE_READMODE_BYTE, None, None)
            return ls_socket
        except:
            return False
    # Check if connection type is TCP (1 indicates TCP)
    elif ls_connection_type == 1:
        try:
            # Initialize socket
            ls_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Get host and port from config and connect to host via TCP
            ls_socket.connect((config.get("connection", "ls_host"), config.get("connection", "ls_port")))
            return ls_socket
        except:
            return False
    else:
        return False


def disconnect(ls_socket) -> None:
    # Check if connection even exists. It may be None (never connected, e.g.
    # the run thread errored before connecting) or False (failed connect);
    # either way there is nothing to close.
    if ls_socket is False or ls_socket is None:
        return
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.disconnect()
        return
    ls_socket.close()


def check_connection(ls_socket) -> bool:
    # Check if connection has been established
    if (ls_socket is False):
        return False
    if isinstance(ls_socket, OBSWebSocketTimer):
        return ls_socket.connected()
    # Check if communication is possible and response is received
    if split_index(ls_socket) is False:
        return False
    else:
        return True


def send(ls_socket, command) -> None:
    # Check if connection type is pipe or socket
    # If it is a socket:
    if isinstance(ls_socket, socket.socket):
        # Send the command to the socket
        ls_socket.send(command.encode('utf-8'))
    # If it is a pipe:
    else:
        # Send the command to the pipe
        try:
            win32file.WriteFile(ls_socket, command.encode('utf-8'))
        except:
            raise Exception("LiveSplit connection lost")

def split(ls_socket) -> None:
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.split()
        return
    send(ls_socket, "startorsplit\r\n")


def reset(ls_socket) -> None:
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.reset()
        return
    send(ls_socket, "reset\r\n")

def restart(ls_socket) -> None:
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.restart()
        return
    send(ls_socket, "reset\r\nstarttimer\r\n")

def skip(ls_socket) -> None:
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.skip()
        return
    send(ls_socket, "skipsplit\r\n")


def undo(ls_socket) -> None:
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.undo()
        return
    send(ls_socket, "unsplit\r\n")


def open_projector(ls_socket, geometry_b64=None) -> None:
    """Pop out a windowed LiveSplit projector (OBS WebSocket timer only)."""
    if isinstance(ls_socket, OBSWebSocketTimer):
        ls_socket.open_projector(geometry_b64)
        return
    raise Exception(
        "Popping out the LiveSplit view requires the OBS WebSocket timer "
        "method (Settings -> Connection -> Timer Method)."
    )


def split_index(ls_socket):
    # OBS WebSocket cannot read the plugin's split index, so the timer mirrors
    # it locally from the hotkeys it has fired. Return that so the main loop
    # advances the route exactly as it does on the TCP path.
    if isinstance(ls_socket, OBSWebSocketTimer):
        return ls_socket.split_index()
    # Check if connection type is pipe or socket
    # If it is a socket:
    if isinstance(ls_socket, socket.socket):
        # Send the command to the socket
        try:
            ls_socket.send("getsplitindex\r\n".encode('utf-8'))
        except:
            return False
        
        # Wait for response
        readable = select.select([ls_socket], [], [], 0.5)
        if readable[0]:
            try:
                data = (ls_socket.recv(1000)).decode("utf-8")
                if not isinstance(data, bool):
                    return int(data)
                else:
                    return False
            except:
                return False
        else:
            return False
    # If it is a pipe:
    else:
        # Send the command to the pipe
        try:
            win32file.WriteFile(ls_socket, "getsplitindex\r\n".encode('utf-8'))
        except:
            return False
        # Get current time
        start_time = time.time()
        # Set timeout to 0.5 seconds
        timeout = 0.5
        # Read from pipe until success or timeout
        while True:
            # Check if the timeout has occurred
            if time.time() - start_time > timeout:
                return False
            # Peek at the pipe to see if there is data as it is non-blocking
            try:
                peek_data, available , _ = win32pipe.PeekNamedPipe(ls_socket, 1000)
            except:
                raise Exception("LiveSplit connection lost")
            # If there is data available:
            if available > 0:
                # Read the data from the pipe
                data = win32file.ReadFile(ls_socket, 1000)[1].decode("utf-8")
                if not isinstance(data, bool):
                    return int(data)
                else:
                    return False
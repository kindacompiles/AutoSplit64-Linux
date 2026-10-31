"""Cross-platform path resolution for the AutoSplit64 Linux port.

Two kinds of paths are kept strictly separate:

* **Bundled, read-only resources** (application code, GUI assets, the default
  reset templates, the ONNX model, ``defaults.ini``) live under the
  *application root* -- the directory that contains ``AutoSplit64.py``.  When
  running from source that is the repository root; when frozen with PyInstaller
  it is the unpacked bundle directory.  These are resolved with
  :func:`resource_path`.

* **User-writable state** follows the XDG Base Directory specification:
  configuration under ``$XDG_CONFIG_HOME/autosplit64`` (default
  ``~/.config/autosplit64``) and data/logs under ``$XDG_DATA_HOME/autosplit64``
  (default ``~/.local/share/autosplit64``).

The original Windows code resolved everything relative to the current working
directory, which only worked because the app was always launched from its
install folder.  That breaks for an AppImage or a .desktop launcher, so the
Linux port resolves bundled resources from ``__file__`` instead.
"""

import os
import sys
from pathlib import Path

APP_NAME = "autosplit64"


def app_root() -> Path:
    """Directory holding the bundled application and its read-only resources."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks data files to ``_MEIPASS``; fall back to the
        # executable's directory for a one-folder build.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    # as64core/paths.py -> as64core -> <app root>
    return Path(__file__).resolve().parent.parent


def _xdg_base(env_var: str, *default_under_home: str) -> Path:
    value = os.environ.get(env_var, "").strip()
    if value:
        return Path(value)
    return Path.home().joinpath(*default_under_home)


def config_dir() -> Path:
    """User configuration directory, created if missing."""
    path = _xdg_base("XDG_CONFIG_HOME", ".config") / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """User data directory (routes, generated templates, logs), created if missing."""
    path = _xdg_base("XDG_DATA_HOME", ".local", "share") / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    """Full path to the user's ``config.ini`` (JSON despite the extension)."""
    return config_dir() / "config.ini"


def defaults_file() -> Path:
    """Full path to the bundled, read-only ``defaults.ini``."""
    return app_root() / "defaults.ini"


def log_file() -> Path:
    """Full path to the application log."""
    return data_dir() / "autosplit64.log"


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource, relative to :func:`app_root`."""
    return app_root().joinpath(*parts)

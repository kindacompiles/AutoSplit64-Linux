"""Resource path helpers.

Historically these resolved paths relative to the current working directory
(and scrubbed Windows backslashes).  The Linux port resolves bundled resources
relative to the application root instead -- see :mod:`as64core.paths` -- so the
app works regardless of the directory it is launched from (AppImage, .desktop
entry, etc.).  The public function names and signatures are unchanged so the
rest of the codebase does not need to care.
"""

import os
from pathlib import Path

from . import paths


def base_path(relative_path=None):
    """Path to a bundled resource (formerly ``dirname(sys.argv[0])``)."""
    if not relative_path:
        return str(paths.app_root())
    return str(paths.app_root() / relative_path)


def absolute_path(relative_path=None):
    """Absolute path within the application tree (formerly the CWD)."""
    if not relative_path:
        return str(paths.app_root())
    return str(paths.app_root() / relative_path)


def resource_path(relative_path):
    """Absolute path to a bundled resource, works for source and PyInstaller."""
    return str(paths.app_root() / relative_path)


def user_data_path(relative_path):
    """Absolute path to a *user-writable* data file (XDG data dir).

    Use this for anything the app generates or overwrites at runtime -- preview
    frames, generated reset templates, etc. The application root is read-only
    when running from an AppImage, so generated files must never be written
    there; they belong under ``paths.data_dir()``.
    """
    return str(paths.data_dir() / relative_path)


def abs_to_rel(p):
    """Make ``p`` relative to the application root when it lives inside it."""
    try:
        return str(Path(p).resolve().relative_to(paths.app_root()))
    except (ValueError, OSError):
        return p


def rel_to_abs(p):
    """Resolve a (possibly relative) path against the application root."""
    if os.path.isabs(p):
        return p
    return str(paths.app_root() / p)

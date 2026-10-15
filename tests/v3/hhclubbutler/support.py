"""Execute the full plugin class with inert host adapters and no network access."""
from __future__ import annotations
import ast
import __future__
import json
import os
from pathlib import Path
import re
import runpy
import tempfile
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]


def temporary_state():
    directory = os.environ.get("HHCLUB_TEST_TMPDIR")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="hhclubbutler-test-", dir=directory)


def forbidden(*args, **kwargs):
    raise AssertionError("Live host/network access is prohibited in plugin tests")


class Base:
    def __init__(self):
        self._temporary = temporary_state()

    def get_data_path(self):
        return Path(self._temporary.name)


def load():
    source = (ROOT / "plugins.v3/hhclubbutler/__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    scope = dict(globals())
    scope.update(runpy.run_path(str(ROOT / "plugins.v3/hhclubbutler/matching.py")))
    scope.update({
        "_PluginBase": Base, "BaseModel": type("BaseModel", (), {}),
        "Field": lambda **kw: kw.get("default_factory", lambda: None)(), "ConfigDict": dict,
        "Depends": lambda f: f, "verify_resource_token": forbidden, "verify_token": forbidden,
        "HTMLResponse": type("HTMLResponse", (), {}),
        "settings": SimpleNamespace(TZ="UTC"),
        "pytz": SimpleNamespace(timezone=lambda name: ZoneInfo(name)),
        "logger": SimpleNamespace(info=Mock(), warning=Mock(), error=Mock()),
        "EventType": SimpleNamespace(PluginAction="action"),
        "eventmanager": SimpleNamespace(register=lambda _: lambda fn: fn),
        "NotificationType": SimpleNamespace(Plugin="plugin"),
        "requests": SimpleNamespace(Session=forbidden), "SiteOper": forbidden,
        "DownloaderHelper": forbidden, "BackgroundScheduler": forbidden,
    })
    exec(compile(tree, "<full-plugin-with-inert-host>", "exec",
                 flags=__future__.annotations.compiler_flag), scope)
    return scope["HHClubButler"]


Subject = load()


def enrich(host):
    """Use real safety methods when an older test extracts only one endpoint."""
    if not hasattr(host, "get_data_path"):
        host._temporary = temporary_state()
        host.get_data_path = lambda: Path(host._temporary.name)
    for key, value in {"_enabled": True, "_stopped": False, "_delete_generation": 0,
                       "_delete_lock": threading.Lock(), "_delete_guard": {},
                       "_delete_resolved": [], "_delete_guard_loaded": False}.items():
        if not hasattr(host, key):
            setattr(host, key, value)
    for name in ("_safe_error", "_operation_allowed", "_torrent_field", "_data_paths", "_paths_overlap",
                 "_validate_delete_files", "_load_delete_guard", "_save_delete_guard", "_guard_deletion",
                 "_reconcile_delete_guard", "_cancel_delete_reservation", "_is_completed"):
        if not hasattr(host, name):
            setattr(host, name, Subject.__dict__[name].__get__(host, type(host)))
    return host

"""Isolated offline adapter for Dian115Sign; never a real MoviePilot host.

Run only in a dedicated process with DIAN115_OFFLINE_TEST=1. Without that
explicit opt-in, these offline-only test modules are excluded from collection.
"""
import copy
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
from typing import Generic, TypeVar


def _install_offline_doubles():
    """Install import/storage/scheduler doubles only in a clean test process."""
    if "app" in sys.modules:
        raise RuntimeError("Run Dian115Sign offline tests in a clean process without a loaded MoviePilot host.")
    from pydantic import BaseModel
    ROOT = Path(__file__).resolve().parents[3]

    def module(name, **attrs):
        item = types.ModuleType(name)
        item.__dict__.update(attrs)
        sys.modules[name] = item
        return item

    class PluginBase:
        def __init__(self):
            self.data = {}
            self.saved_config = {}
            self.notifications = []
            self.path = Path(tempfile.mkdtemp(prefix="dian115-test-"))
        def get_data(self, key):
            return copy.deepcopy(self.data.get(key))
        def save_data(self, key, value):
            self.data[key] = copy.deepcopy(value)
        def del_data(self, key):
            self.data.pop(key, None)
        def get_data_path(self):
            return self.path
        def update_config(self, value):
            self.saved_config = copy.deepcopy(value)
            return True
        def post_message(self, **kwargs):
            self.notifications.append(kwargs)

    T = TypeVar("T")
    class Response(BaseModel, Generic[T]):
        success: bool
        message: str = ""
        data: T | None = None

    class Event:
        def __init__(self, data=None):
            self.event_data = data or {}
    class EventManager:
        def register(self, event):
            return lambda method: method
    class CronTrigger:
        @classmethod
        def from_crontab(cls, expression, timezone=None):
            if len(expression.split()) != 5:
                raise ValueError("stub: not five fields")
            value = cls()
            value.expression, value.timezone = expression, timezone
            return value
    class DateTrigger:
        def __init__(self, run_date):
            self.run_date = run_date

    module("app", __path__=[])
    module("app.plugins", __path__=[str(ROOT / "plugins.v3")], _PluginBase=PluginBase)
    module("app.schemas", __path__=[], Response=Response)
    module("app.schemas.types", EventType=types.SimpleNamespace(PluginAction="PluginAction"),
           NotificationType=types.SimpleNamespace(Plugin="Plugin"))
    module("app.sdk", __path__=[])
    module("app.sdk.config", settings=types.SimpleNamespace(PROXY=None))
    module("app.sdk.events", Event=Event, eventmanager=EventManager())
    module("app.sdk.logging", logger=logging.getLogger("dian115-test"))
    module("app.sdk.browser", launch_browser_context=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("not mocked")))
    # Only scheduler import contracts are doubled, not claimed to be integration tested.
    module("apscheduler", __path__=[])
    module("apscheduler.triggers", __path__=[])
    module("apscheduler.triggers.cron", CronTrigger=CronTrigger)
    module("apscheduler.triggers.date", DateTrigger=DateTrigger)


if os.environ.get("DIAN115_OFFLINE_TEST") == "1":
    _install_offline_doubles()
else:
    collect_ignore = ["test_plugin.py", "test_browser.py"]

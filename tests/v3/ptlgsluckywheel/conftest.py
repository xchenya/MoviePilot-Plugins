"""Offline MP contract adapter; network is denied in every test."""
import copy
import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def module(monkeypatch, tmp_path):
    """Import the real plugin via its production namespace with stubbed host I/O."""
    class Base:
        def __init__(self):
            self.notifications = []
            self.saved_config = {}

        def get_data_path(self):
            return tmp_path

        def update_config(self, value):
            self.saved_config = copy.deepcopy(value)
            return True

        def post_message(self, **kwargs):
            self.notifications.append(kwargs)

    def stub(name, **attrs):
        obj = ModuleType(name)
        obj.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, obj)

    site = SimpleNamespace(url="https://ptlgs.org/", cookie="session=fixture-secret", ua="fixture-UA")
    stub("app", __path__=[])
    stub("app.plugins", __path__=[str(ROOT / "plugins.v3")])
    stub("app.sdk", __path__=[])
    stub("app.sdk.plugin", _PluginBase=Base)
    stub("app.sdk.config", settings=SimpleNamespace(PROXY={"https": "http://proxy.invalid:8080"}))
    stub("app.sdk.logging", logger=logging.getLogger("ptlgs-test"))
    stub("app.db", __path__=[])
    stub("app.db.oper", __path__=[])
    stub("app.db.oper.site", SiteOper=lambda: SimpleNamespace(get_by_domain=lambda _: site))
    stub("app.schemas", __path__=[])
    stub("app.schemas.types", NotificationType=SimpleNamespace(Plugin="plugin"))
    for name in list(sys.modules):
        if name == "app.plugins.ptlgsluckywheel" or name.startswith("app.plugins.ptlgsluckywheel."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("real network is forbidden")))
    result = importlib.import_module("app.plugins.ptlgsluckywheel")
    result.site_fixture = site
    yield result
    for name in list(sys.modules):
        if name == "app.plugins.ptlgsluckywheel" or name.startswith("app.plugins.ptlgsluckywheel."):
            sys.modules.pop(name, None)


@pytest.fixture
def plugin(module):
    """An enabled plugin with no scheduled or external side effects."""
    obj = module.PtlgsLuckyWheel()
    obj.init_plugin({"enabled": True, "daily_target": 20, "interval": 3})
    obj._cancel.wait = Mock(return_value=False)
    return obj

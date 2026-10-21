"""V3 port tests for HDSky's DiceBetNatural, without network or account writes.

Keep these isolated from MoviePilot imports so static and simulated checks can run
before any real HDSky login. The integration acceptance test is manual/opt-in.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock
from urllib.parse import urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/hdskydicebetnatural/__init__.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _class_node() -> ast.ClassDef:
    return next(
        item for item in ast.parse(_source()).body
        if isinstance(item, ast.ClassDef) and item.name == "HdskyDiceBetNatural"
    )


def _method(name: str):
    return next(
        item for item in _class_node().body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )


class FakeBase:
    DEFAULT_UA = "Test User Agent"
    LOG_TAG = "[TEST]"
    FORUM_ID = 71
    _enabled = False
    _notify = False
    _humanize = False

    def __init__(self):
        self.data = {}
        self.config_saves = []
        self._site_id = None

    def get_data(self, key):
        return self.data.get(key)

    def save_data(self, key, value):
        self.data[key] = value

    def update_config(self, value):
        self.config_saves.append(dict(value))
        return True


class FakeCron:
    @staticmethod
    def from_crontab(expr, timezone=None):
        if len(expr.split()) != 5:
            raise ValueError("invalid cron")
        return ("cron", expr, timezone)


class FakeDate:
    def __init__(self, run_date):
        self.run_date = run_date


LOGGER = SimpleNamespace(
    info=Mock(), warning=Mock(), error=Mock(), debug=Mock(),
)


def _isolate(*names):
    """Create only selected source methods inside a fake class and fake imports."""
    body = [copy.deepcopy(_method(name)) for name in names]
    node = ast.fix_missing_locations(
        ast.Module(body=[
            ast.ClassDef(
                name="HdskyDiceBetNatural",
                bases=[ast.Name(id="FakeBase", ctx=ast.Load())],
                keywords=[],
                body=body,
                decorator_list=[],
            ),
        ], type_ignores=[]),
    )
    namespace = {
        "FakeBase": FakeBase, "threading": threading,
        "settings": SimpleNamespace(TZ="UTC"),
        "pytz": SimpleNamespace(timezone=lambda name: timezone.utc),
        "CronTrigger": FakeCron, "DateTrigger": FakeDate,
        "datetime": datetime, "timedelta": timedelta,
        "urljoin": urljoin, "urlsplit": urlsplit,
        "logger": LOGGER, "re": re,
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
    }
    exec(compile(node, "<HDSky-isolated>", "exec"), namespace)
    return namespace["HdskyDiceBetNatural"]


def _stub_config_helpers(p):
    p._normalize_site_id = lambda v: int(v) if v else None
    p._parse_fixed_types = lambda cfg: list(cfg.get("fixed_types") or ["大"])
    p._clamp_amount = lambda v: max(100, min(int(v), 100000))
    p._parse_amount_by_type = lambda cfg: {}
    p._clamp_interval = lambda v: max(1, int(v))
    p._to_optional_int = lambda v: int(v) if v else None
    p._list_hdsky_sites = lambda: []


def test_market_and_source_metadata():
    cls = _class_node()
    attrs = {
        target.id: item.value.value
        for item in cls.body
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
        for target in item.targets if isinstance(target, ast.Name)
    }
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = package["HdskyDiceBetNatural"]
    assert entry["version"] == attrs["plugin_version"] == "2.0.0"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["release"] is False
    assert attrs["plugin_author"] == "Kuanghom"
    assert attrs["plugin_icon"].startswith("https://")
    assert "Kuanghom/MoviePilot-Plugins" in _source()


def test_v3_imports_and_lifecycle_are_not_v2():
    source = _source()
    assert "from app.sdk.plugin import _PluginBase" in source
    assert "from app.sdk.network import SitesHelper, RequestUtils" in source
    assert "from app.sdk.config import settings" in source
    assert "from app.db.oper.site import SiteOper" in source
    assert "from app.sdk.logging import logger" in source
    assert "from app.schemas.types import NotificationType" in source
    assert "BackgroundScheduler(" not in source
    assert "from app.core" not in source
    assert "from app.helper" not in source
    assert "from app.utils" not in source
    assert "def _is_cancelled(" in source
    assert "self._thread_ctx = threading.local()" in source


def test_old_config_and_native_cron_lifecycle():
    cls = _isolate("__init__", "init_plugin", "stop_service",
                   "_is_cancelled", "get_state", "get_service")
    p = cls()
    _stub_config_helpers(p)
    p.init_plugin({"enabled": True, "cron": "*/5 * * * *", "site_id": 42})
    assert p.get_state()
    services = p.get_service()
    assert len(services) == 1
    assert services[0]["id"] == "HdskyDiceBetNatural.Run"
    assert services[0]["kwargs"]["generation"] == 1
    assert services[0]["trigger"][0] == "cron"
    assert p._site_id == 42
    assert p._fixed_types == ["大"]
    assert not p._onlyonce
    p.stop_service()
    assert not p.get_state() and p.get_service() == []


def test_one_shot_must_persist_toggle_before_scheduler():
    cls = _isolate("__init__", "init_plugin", "stop_service",
                   "_is_cancelled", "get_state", "get_service")
    p = cls()
    _stub_config_helpers(p)
    p.init_plugin({"enabled": True, "onlyonce": True, "site_id": 1})
    assert len(p.get_service()) == 2
    assert p.get_service()[1]["id"].endswith(".Once")
    assert isinstance(p.get_service()[1]["trigger"], FakeDate)
    assert p.get_service()[1]["kwargs"]["skip_jitter"] is True
    assert p.config_saves[-1]["onlyonce"] is False

    p2 = cls()
    _stub_config_helpers(p2)
    p2.update_config = Mock(return_value=False)
    p2.init_plugin({"enabled": True, "onlyonce": True, "site_id": 1})
    assert not p2.get_state()
    assert not p2.get_service()


def test_invalid_cron_fails_closed():
    cls = _isolate("__init__", "init_plugin", "stop_service",
                   "_is_cancelled", "get_state", "get_service")
    p = cls()
    _stub_config_helpers(p)
    p.init_plugin({"enabled": True, "cron": "bad", "site_id": 1})
    assert "Cron" in p._config_error
    assert not p.get_state() and not p.get_service()


def test_reload_cancels_old_generation_even_if_new_event_is_active():
    cls = _isolate("__init__", "init_plugin", "stop_service",
                   "_is_cancelled", "_wait", "get_service")
    p = cls()
    _stub_config_helpers(p)
    p.init_plugin({"enabled": True, "site_id": 1})
    old = p._cancel
    old_generation = p._generation
    p.init_plugin({"enabled": True, "site_id": 1})
    assert old.is_set() and p._cancel is not old
    assert not p._is_cancelled()
    p._thread_ctx.generation = old_generation
    p._thread_ctx.cancel = old
    assert p._is_cancelled()
    assert p._wait(0)
    delattr(p._thread_ctx, "cancel")
    delattr(p._thread_ctx, "generation")


def test_url_guard_rejects_cross_site_cookie_leaks():
    cls = _isolate("_allowed_url")
    ok = ("https://hdsky.me/forums.php", "https://www.hdsky.me/forums.php")
    bad = (
        "http://hdsky.me/forums.php", "https://hdsky.me.evil.example",
        "https://evil.example/", "https://user:password@hdsky.me/",
        "https://hdsky.me:8443/", "ftp://hdsky.me/",
        "https://hdsky.me@evil.example/", "//evil.example/",
    )
    assert all(cls._allowed_url(value) for value in ok)
    assert not any(cls._allowed_url(value) for value in bad)


def test_bet_confirmation_rejects_generic_html_success_and_amount_mismatch():
    cls = _isolate("_post_bet", "_same_bet_amount")
    p = cls()
    p.BASE_URL = "https://hdsky.me"
    p._last_referer = None
    p._auth_failed = False
    p._get = Mock(return_value="<html/>")
    p._human_pause = Mock()
    p._post = Mock(return_value="<html>提交成功</html>")
    p._fetch_topic_detail = Mock(return_value={
        "self_bets": [{"bet_type": "大", "amount": 200}],
    })
    assert p._post_bet("89", "大", 100)[0] is False
    assert p._post.call_count == 1
    assert "未确认" in p._post_bet("89", "小", 100)[1]
    p._fetch_topic_detail.return_value = {
        "self_bets": [{"bet_type": "大", "amount": 100}],
    }
    assert p._post_bet("89", "大", 100) == (True, "ok")


def test_post_requires_known_origin_and_no_redirect(monkeypatch):
    cls = _isolate("_post", "_allowed_url")
    p = cls()
    p._cancel = threading.Event()
    p._thread_ctx = threading.local()
    p._generation = 1
    p._auth_failed = False
    p._cookie = "DO_NOT_LOG_COOKIE=secret"
    p._ua = "TestUA"
    p._site_id = 1
    p.BASE_URL = "https://hdsky.me"
    p._last_referer = None
    p.LOG_TAG = "[test]"
    p._is_cancelled = Mock(return_value=False)
    p._request_headers = Mock(return_value={})
    p._proxies = Mock(return_value=None)
    fake_response = SimpleNamespace(status_code=200, text="ok")
    fake = Mock()
    fake.return_value.post_res.return_value = fake_response
    p._post.__globals__["RequestUtils"] = fake
    assert p._post("/forums.php?action=post", {"body": "大 100"}) == "ok"
    assert fake.return_value.post_res.call_args.kwargs["allow_redirects"] is False
    count = fake.call_count
    assert p._post("https://evil.example/", {"body": "大 100"}) is None
    assert fake.call_count == count
    fake.return_value.post_res.return_value = SimpleNamespace(status_code=302, text="redirect")
    assert p._post("/forums.php?action=post", {"body": "大 100"}) is None
    fake.return_value.post_res.return_value = SimpleNamespace(
        status_code=200, text="<title>HDSky :: 登录</title>"
    )
    assert p._post("/forums.php?action=post", {"body": "大 100"}) is None
    assert p._auth_failed


def test_pending_post_never_blindly_retries():
    cls = _isolate("_post_bet", "_same_bet_amount")
    p = cls()
    p.FORUM_ID = 71
    p.BASE_URL = "https://hdsky.me"
    p._last_referer = None
    p._auth_failed = False
    p._get = Mock(return_value="any")
    p._human_pause = Mock()
    p._post = Mock(return_value=None)
    p._fetch_topic_detail = Mock()
    ok, message = p._post_bet("200", "小", 100)
    assert not ok and "未确认" in message
    assert p._post.call_count == 1
    p._fetch_topic_detail.assert_not_called()

"""SiQiCleanBeach V3 regression checks without live site credentials or DB."""
from __future__ import annotations

import ast
import copy
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, List, Tuple
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
CODE = ROOT / "plugins.v3" / "siqicleanbeach" / "__init__.py"


def _source() -> str:
    return CODE.read_text(encoding="utf-8")


def _plugin_class() -> ast.ClassDef:
    return next(
        node for node in ast.parse(_source()).body
        if isinstance(node, ast.ClassDef) and node.name == "SiQiCleanBeach"
    )


def _method(name: str) -> ast.FunctionDef:
    return next(
        node for node in _plugin_class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _isolated_class(*names: str):
    """Compile just chosen methods; avoid MoviePilot app imports and network."""
    body = [copy.deepcopy(_method(name)) for name in names]
    module = ast.fix_missing_locations(
        ast.Module(
            body=[ast.ClassDef(
                name="SiQiCleanBeach", bases=[], keywords=[], body=body, decorator_list=[]
            )],
            type_ignores=[],
        )
    )
    namespace = {
        "requests": requests,
        "BeautifulSoup": BeautifulSoup,
        "re": re,
        "threading": threading,
        "time": time,
        "datetime": datetime,
        "List": List,
        "Tuple": Tuple,
        "Dict": Dict,
        "Optional": Optional,
        "Any": Any,
        "logger": SimpleNamespace(
            info=Mock(), debug=Mock(), warning=Mock(), error=Mock(), exception=Mock()
        ),
    }
    exec(compile(module, str(CODE), "exec"), namespace)
    return namespace["SiQiCleanBeach"]


def test_v3_metadata_and_source_license():
    plugin = _plugin_class()
    attrs = {
        target.id: item.value.value
        for item in plugin.body
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
        for target in item.targets
        if isinstance(target, ast.Name)
    }
    market = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = market["SiQiCleanBeach"]
    assert attrs["plugin_version"] == entry["version"] == "2.2.1"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["release"] is False
    assert attrs["plugin_author"].startswith("bfjy")
    assert "GPL-3.0" in _source()


def test_sdk_and_security_contracts():
    source = _source()
    assert "from app.sdk.events import Event, eventmanager" in source
    assert "from app.sdk.logging import logger" in source
    assert "from app.db.oper.site import SiteOper" in source
    assert "from app.db.site_oper" not in source
    assert "verify=False" not in source
    assert "disable_warnings" not in source
    assert "class ActionResponse(BaseModel)" in source
    assert "class StatsResponse(BaseModel)" in source
    api = ast.get_source_segment(source, _method("get_api"))
    assert api is not None
    assert api.count('"response_model"') == 2
    assert api.count('"auth": "bear"') == 2
    assert '"methods": ["POST"]' in api


def test_separate_runtime_lock_and_mutable_state():
    cls = _plugin_class()
    class_values = {
        target.id
        for item in cls.body if isinstance(item, ast.Assign)
        for target in item.targets if isinstance(target, ast.Name)
    }
    assert "_lock" not in class_values
    assert "_stats" not in class_values
    assert "_inventory" not in class_values
    init_source = ast.get_source_segment(_source(), _method("__init__"))
    assert "self._lock = threading.Lock()" in init_source
    assert "self._inventory" in init_source


def test_nested_html_inventory_parsing(monkeypatch):
    cls = _isolated_class("__cookie_to_dict", "__fetch_inventory", "__read_beach_cooldown")
    plugin = cls()
    plugin.MOWAN_URL = "https://si-qi.xyz/mowan.php"
    plugin.ITEM_ICONS = {}
    plugin._user_agent = "fixture-browser"
    plugin._session = None
    response = SimpleNamespace(status_code=200, text="""
        <div class="inventory-grid">
          <div class="inventory-item"><div class="wrapper">
            <span class="item-icon">🪵</span>
            <div class="item-name">木材</div>
            <div class="item-count"><b>1,234</b> 个</div>
          </div></div>
          <div class="inventory-item">
            <div class="item-name">砖块</div><div class="item-count">22</div>
          </div>
          <div class="inventory-item">
            <div class="item-name">旧电池</div><div class="item-count">7</div>
          </div>
        </div>
    """)
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    inventory = plugin._SiQiCleanBeach__fetch_inventory("c_secure_pass=x; cf_clearance=y")
    assert inventory["木材"]["count"] == 1234
    assert inventory["旧电池"]["count"] == 7
    assert inventory["砖块"]["count"] == 22
    assert get.call_args.kwargs["verify"] is True
    assert get.call_args.kwargs["timeout"] == (10, 30)
    assert get.call_args.kwargs["cookies"]["c_secure_pass"] == "x"


def test_unknown_inventory_markup_keeps_cache(monkeypatch):
    cls = _isolated_class("__cookie_to_dict", "__fetch_inventory", "__read_beach_cooldown")
    p = cls()
    p.MOWAN_URL = "https://si-qi.xyz/mowan.php"
    p.ITEM_ICONS = {}
    p._user_agent = "fixture-browser"
    p._session = None
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=200, text="<h1>页面升级</h1>")
    )
    assert p._SiQiCleanBeach__fetch_inventory("c_secure_pass=x") is None


def test_cookie_parser_blocks_header_injection():
    cls = _isolated_class("__cookie_to_dict")
    assert cls._SiQiCleanBeach__cookie_to_dict("a=b=c; b=two") == {"a": "b=c", "b": "two"}
    with pytest.raises(ValueError):
        cls._SiQiCleanBeach__cookie_to_dict("a=b\r\nInjected: x")


def test_concurrent_manual_runs_are_rejected():
    cls = _isolated_class("_queue_manual_run", "run_once_api")
    p = cls()
    p._lock = threading.Lock()
    p._stop_event = threading.Event()
    started = threading.Event()
    unblock = threading.Event()
    completed = threading.Event()

    def fake_run(reserved=False):
        try:
            assert reserved is True
            started.set()
            unblock.wait(2)
        finally:
            p._lock.release()
            completed.set()

    p.run_clean_task = fake_run
    try:
        first = p.run_once_api()
        assert first["success"] is True
        assert started.wait(2)
        assert p.run_once_api()["success"] is False
    finally:
        unblock.set()
    assert completed.wait(2)

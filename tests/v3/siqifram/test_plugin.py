"""Offline contract tests; host services and all site traffic are mocked."""
import ast
import inspect
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "siqifram"


@pytest.fixture
def module(monkeypatch):
    """Execute the complete plugin with real HTTP/model libraries, without MP/DB."""
    class PluginBase:
        def __init__(self):
            self.data = {}
            self.config = {}
            self.post_message = Mock()

        def get_data(self, key):
            return self.data.get(key)

        def save_data(self, key, value):
            self.data[key] = value

        def update_config(self, config):
            self.config = dict(config)

    tree = ast.parse((PLUGIN / "__init__.py").read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module.startswith("app."))
        and not (isinstance(node, ast.Try) and any(
            isinstance(item, ast.ImportFrom) and item.module.startswith("app.")
            for item in node.body
        ))
    ]
    loaded = ModuleType("siqifram_offline")
    monkeypatch.setitem(sys.modules, loaded.__name__, loaded)
    loaded.__dict__.update(
        _PluginBase=PluginBase, logger=Mock(),
        settings=SimpleNamespace(TZ="Asia/Shanghai", PROXY=None, AI_AGENT_ENABLE=False),
        SiteOper=Mock(return_value=SimpleNamespace(get_by_domain=lambda domain:
            SimpleNamespace(url="https://si-qi.xyz", ua="fixture-UA", cookie="session=one"))),
        RecognizeCaptchaTool=None,
        NotificationType=SimpleNamespace(SiteMessage="site"),
        remove_plugin_job=Mock(), update_plugin_job=Mock(),
    )
    exec(compile(tree, str(PLUGIN / "__init__.py"), "exec"), loaded.__dict__)
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("unmocked GET")))
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("unmocked POST")))
    return loaded


@pytest.fixture
def plugin(module):
    instance = module.SiqiFram()
    instance.init_plugin({})
    return instance


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


def test_market_and_api_contract(plugin, module):
    entry = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["SiqiFram"]
    assert plugin.plugin_version == entry["version"] == "2.0.0"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["release"] is True  # Federation packaging requirement.
    assert "KoWming" in plugin.plugin_author
    assert "GNU GENERAL PUBLIC LICENSE" in (PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert plugin.get_render_mode() == ("vue", "dist/assets")
    routes = plugin.get_api()
    assert len(routes) == 25
    assert all(route["auth"] == "bear" for route in routes)
    assert all(issubclass(route["response_model"], BaseModel) for route in routes)
    assert all(route["methods"] == ["POST"] for route in routes
               if route["path"] in {"/buy-plot-slot", "/plant", "/harvest", "/sell"})
    assert str(inspect.signature(next(r["endpoint"] for r in routes
        if r["path"] == "/plant"))) == "(payload: dict = None) -> Dict[str, Any]"
    assert "app.sdk.scheduler" in (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert "app.db.site_oper" not in (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_disabled_init_and_cache_do_not_contact_site(plugin):
    assert plugin.get_state() is False
    assert plugin.get_service() == []
    plugin.save_data("farm_status", {"success": True, "seeds": [{"id": 1}]})
    assert plugin._get_data() == {"success": True, "seeds": [{"id": 1}], "cached": True}
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_reload_resets_config_and_ai_requires_available_tool(plugin, module):
    plugin.init_plugin({"enabled": True, "auto_sell": True, "use_proxy": True})
    plugin.init_plugin({})
    assert not plugin._enabled and not plugin._auto_sell and not plugin._use_proxy
    module.settings.AI_AGENT_ENABLE = True
    assert not plugin._get_config()["ai_available"]
    module.RecognizeCaptchaTool = Mock()
    assert plugin._get_config()["ai_available"]


def test_old_config_normalization_and_schedule(plugin, module):
    future = int(time.time()) + 3600
    plugin.save_data("next_harvest_at", future)
    plugin.init_plugin({"enabled": "true", "cron": "invalid", "harvest_delay_minutes": 90,
                        "retry_count": -1, "retry_interval": -9})
    assert plugin._cron == "5 */4 * * *"
    assert plugin._harvest_delay_minutes == 30
    assert plugin._retry_count == plugin._retry_interval == 0
    services = plugin.get_service()
    assert [s["id"] for s in services] == ["siqifram", "siqifram-harvest"]
    assert int(plugin._next_run_time.timestamp()) == future + 1800
    plugin._schedule_next_harvest({"user_lands": [
        {"seed_id": 1, "harvest_time": future + 100},
        {"seed_id": 2, "harvest_time": future},
        {"seed_id": None},
    ]})
    assert plugin.get_data("next_harvest_at") == future
    module.update_plugin_job.assert_called_with("SiqiFram")


def test_clone_stop_only_removes_own_jobs(plugin, module):
    clone = type("SiqiFram_work", (module.SiqiFram,), {})()
    clone.init_plugin({"enabled": True})
    module.remove_plugin_job.reset_mock()
    clone.stop_service()
    module.remove_plugin_job.assert_called_once_with("SiqiFram_work")
    assert clone._stop_event.is_set()
    assert not plugin._stop_event.is_set()
    clone._schedule_next_harvest({"user_lands": []})
    module.update_plugin_job.assert_not_called()


def test_read_retries_and_fresh_site_cookie(plugin, monkeypatch):
    plugin._retry_interval = 0
    get = Mock(side_effect=[requests.ReadTimeout(), response({"success": True})])
    monkeypatch.setattr(requests, "get", get)
    assert plugin._json_response(plugin._request("fetch"))["success"]
    assert get.call_count == 2
    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs["headers"]["cookie"] == "session=one"
    plugin._siteoper = SimpleNamespace(get_by_domain=lambda domain:
        SimpleNamespace(url="https://si-qi.xyz", ua="new-UA", cookie="session=two"))
    get.side_effect = None
    get.return_value = response({"success": True})
    plugin._request("fetch")
    assert get.call_args.kwargs["headers"]["cookie"] == "session=two"


@pytest.mark.parametrize("failure", [
    requests.ReadTimeout("lost response"),
    response({"success": True}, 500),
    response(["unexpected shape"]),
])
def test_write_uncertainty_stops_without_retry(plugin, monkeypatch, failure):
    post = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    monkeypatch.setattr(requests, "post", post)
    route = next(r for r in plugin.get_api() if r["path"] == "/buy-plot-slot")
    result = route["endpoint"]({"land_id": 1})
    assert result["success"] is False and result["uncertain"] is True
    assert "刷新" in result["message"]
    assert post.call_count == 1
    requests.get.assert_not_called()


def test_uncertain_harvest_has_no_fallback_or_later_actions(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "auto_sell": True, "auto_plant": True})
    plugin._get_harvest_captcha = Mock(return_value={
        "success": True, "captcha": {"imagehash": "hash", "image_url": "/captcha.php"}})
    plugin._ocr_captcha = Mock(return_value="1234")
    plugin._harvest_ready = Mock()
    plugin._sell_all_inventory = Mock()
    plugin._plant_fill_empty = Mock()
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.ReadTimeout()))
    plugin._farm_task()
    assert requests.post.call_count == 1
    plugin._harvest_ready.assert_not_called()
    plugin._sell_all_inventory.assert_not_called()
    plugin._plant_fill_empty.assert_not_called()
    assert "结果不明" in plugin.get_data("last_result")


def test_successful_write_preserves_site_fields_and_body(plugin, monkeypatch):
    post = Mock(return_value=response({"success": True, "msg": "已种植", "new_field": [1]}))
    monkeypatch.setattr(requests, "post", post)
    plugin.get_farm_data = Mock(return_value={"success": True, "user_lands": []})
    result = plugin._plant({"land_id": 2, "plot_index": 0, "seed_id": "3"})
    assert result["new_field"] == [1]
    assert post.call_args.kwargs["data"] == {
        "action": "plant", "land_id": 2, "plot_index": 0, "seed_id": "3"}
    assert plugin.get_data("farm_status")["success"]


@pytest.mark.parametrize("path", [
    "https://other.example/a.png", "//other.example/a.png",
    "http://si-qi.xyz/a.png", "https://si-qi.xyz@other.example/a.png",
])
def test_image_proxy_rejects_foreign_origins(plugin, path):
    assert not plugin._stage_image(path)["success"]
    assert plugin._ocr_captcha(path) is None
    requests.get.assert_not_called()


def test_stop_prevents_new_requests_and_parallel_api_is_busy(plugin):
    route = next(r for r in plugin.get_api() if r["path"] == "/plant")
    results = []
    with plugin._run_lock:
        worker = threading.Thread(target=lambda: results.append(route["endpoint"]({})))
        worker.start()
        worker.join(2)
    assert results and results[0]["success"] is False
    assert "正在执行" in results[0]["message"]
    plugin.stop_service()
    with pytest.raises(RuntimeError, match="已停止"):
        plugin._request("fetch")
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_real_fastapi_registration_bodies_and_raw_payloads(plugin, monkeypatch):
    app = FastAPI()
    for route in plugin.get_api():
        options = {key: value for key, value in route.items() if key != "auth"}
        app.add_api_route(**options)
    client = TestClient(app)
    assert client.get("/config").json()["seed_id"] == "1"
    assert client.get("/status").json()["enabled"] is False
    saved = client.post("/config", json={"enabled": False, "seed_id": "9"}).json()
    assert saved["success"] and saved["config"]["seed_id"] == "9"
    monkeypatch.setattr(requests, "post", Mock(return_value=response({
        "success": True, "msg": "ok", "new_field": 42})))
    plugin.get_farm_data = Mock(return_value={"success": True, "user_lands": []})
    planted = client.post("/plant", json={"land_id": 4, "plot_index": 0}).json()
    assert planted == {"success": True, "msg": "ok", "new_field": 42}
    assert requests.post.call_args.kwargs["data"]["land_id"] == 4
    monkeypatch.setattr(requests, "get", Mock(return_value=SimpleNamespace(
        status_code=200, content=b"png", headers={"content-type": "image/png"})))
    image = client.get("/stage-image", params={"path": "/images/carrot.png"}).json()
    assert image == {"success": True, "data": "data:image/png;base64,cG5n"}
    assert "requestBody" in app.openapi()["paths"]["/plant"]["post"]

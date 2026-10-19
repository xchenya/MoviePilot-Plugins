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


def page_response(markup):
    result = requests.Response()
    result.status_code = 200
    result.encoding = "utf-8"
    result._content = markup.encode("utf-8")
    return result


@pytest.mark.parametrize("markup, expected", [
    ('<a href="userdetails.php?id=9"><b>DENON</b></a>'
     '<table id="info_block"><tr><td><table><tr><td>欢迎，'
     '<a href="userdetails.php?id=37"><span class="VIP">实际用户</span></a>'
     ' [<a href="logout.php">退出</a>]</td></tr></table></td></tr></table>', "实际用户"),
    ("<div id=info_block><a class='user' href='/userdetails.php?foo=1&amp;id=37'>"
     "<b>Alice &amp; Bob</b></a> <a href='/logout.php'>退出</a></div>", "Alice & Bob"),
    ('<div id="info_block"><a href="//si-qi.xyz/userdetails.php?id=37">SameSite</a>'
     '<a href="https://si-qi.xyz/logout.php">退出</a>'
     '<a href="userdetails.php?id=9"><b>DENON</b></a></div>', "SameSite"),
    ('<a href="userdetails.php?id=9"><b>DENON</b></a>', ""),
    ('<div id="info_block"><a href="userdetails.php?id=37">NoLogout</a></div>'
     '<a href="logout.php">退出</a>', ""),
    ('<div id="info_block"><a href="https://other.example/userdetails.php?id=37">Foreign</a>'
     '<a href="logout.php">退出</a></div>', ""),
    ('<div id="info_block"><a href="userdetails.php?id=0">Invalid</a>'
     '<a href="logout.php">退出</a></div>', ""),
    ('<div id="info_block"><a href="userdetails.php?id=37">AccountA</a>'
     '<a href="logout.php">退出</a></div>'
     '<div id="info_block"><a href="userdetails.php?id=38">AccountB</a>'
     '<a href="logout.php">退出</a></div>', ""),
])
def test_page_username_comes_only_from_authenticated_header(plugin, monkeypatch, markup, expected):
    markup += '<span id="user-steal-gain">1,234.5</span><span id="user-farm-like-total">8</span>'
    monkeypatch.setattr(requests, "get", Mock(return_value=page_response(markup)))
    assert plugin._get_page_meta() == {"current_username": expected,
                                      "user_steal_gain": 1234.5, "user_farm_like_total": 8}
    assert requests.get.call_count == 1
    requests.post.assert_not_called()


@pytest.mark.parametrize("api_name, header, expected", [
    (None, '<div id="info_block"><a href="userdetails.php?id=37"><span>实际用户</span></a>'
     '<a href="logout.php">退出</a></div>', "实际用户"),
    ("ApiAccount", '<div id="info_block"><a href="userdetails.php?id=37">HeaderAccount</a>'
     '<a href="logout.php">退出</a></div>', "ApiAccount"),
    (None, "", "未识别"),
])
def test_task_notification_and_shared_cache_use_the_resolved_account(plugin, monkeypatch, api_name, header, expected):
    plugin.init_plugin({"enabled": True, "auto_harvest": False, "auto_plant": False})
    farm = {"success": True, "seeds": [{"id": 1}], "user_lands": [], "user_bonus": 411162}
    if api_name is not None:
        farm["current_username"] = api_name
    page = '<a href="userdetails.php?id=9"><b>DENON</b></a>' + header
    monkeypatch.setattr(requests, "get", Mock(side_effect=[response(farm), page_response(page)]))
    plugin._farm_task()
    text = plugin.post_message.call_args.kwargs["text"]
    assert f"👤 用户：{expected}" in text
    assert "DENON" not in text
    assert "🪄 魔力值：411162" in text
    assert plugin._get_data()["current_username"] == ("" if expected == "未识别" else expected)
    requests.post.assert_not_called()


def test_market_and_api_contract(plugin, module):
    entry = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["SiqiFram"]
    assert plugin.plugin_version == entry["version"] == "2.1.4"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["release"] is True  # Federation packaging requirement.
    assert "KoWming" in plugin.plugin_author
    assert "GNU GENERAL PUBLIC LICENSE" in (PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert plugin.get_render_mode() == ("vue", "dist/assets-v2.1.4")
    assert (PLUGIN / plugin.get_render_mode()[1] / "remoteEntry.js").is_file()
    routes = plugin.get_api()
    assert len(routes) == 28
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


def test_crop_config_defaults_subset_empty_and_clone_isolation(plugin, module):
    defaults = ["萝卜", "西红柿", "玉米", "茄子", "蘑菇", "樱桃"]
    assert plugin._get_config()["steal_crops"] == defaults
    assert module.FarmConfig().steal_crops == defaults
    result = plugin._save_config({"steal_crops": ["玉米", "萝卜", "玉米", "西瓜"]})
    assert result["config"]["steal_crops"] == ["萝卜", "玉米"]
    assert plugin.config["steal_crops"] == ["萝卜", "玉米"]
    assert plugin._save_config({})["config"]["steal_crops"] == ["萝卜", "玉米"]
    assert plugin._save_config({"steal_crops": []})["config"]["steal_crops"] == []
    assert module.SiqiFram()._steal_crops == defaults
    plugin.init_plugin({"steal_crops": "萝卜"})
    assert plugin._steal_crops == []


def test_separate_steal_save_keeps_planting_seed_and_all_other_settings(plugin):
    plugin.init_plugin({"enabled": True, "seed_id": "120", "auto_plant": True,
                        "cron": "20 */3 * * *", "cookie": "session=custom"})
    before = {k: v for k, v in plugin._get_config().items() if k not in {"auto_steal", "steal_crops"}}
    saved = plugin._save_steal_config({"auto_steal": True, "steal_crops": ["玉米"],
                                      "seed_id": "1", "cron": "bad"})
    assert saved["config"] == {"auto_steal": True, "steal_crops": ["玉米"]}
    assert {k: v for k, v in plugin._get_config().items() if k in before} == before
    assert plugin.config["seed_id"] == "120"
    plugin._save_config({"notify": False})
    assert plugin._seed_id == "120" and plugin._auto_steal and plugin._steal_crops == ["玉米"]
    plugin.init_plugin(plugin.config)
    assert plugin._seed_id == "120" and plugin._steal_crops == ["玉米"]


@pytest.mark.parametrize("selected", [[], ["萝卜"], ["玉米", "樱桃"]])
def test_full_seed_catalog_is_independent_of_steal_filter(plugin, selected):
    catalog = [{"id": 91, "name": "萝卜", "unlock_harvest": 0},
               {"id": 120, "name": "樱桃", "unlock_harvest": 40},
               {"id": 200, "name": "西瓜", "unlock_harvest": 100}]
    plugin.init_plugin({"seed_id": "120", "steal_crops": selected})
    plugin.get_farm_data = Mock(return_value={"success": True, "seeds": catalog,
                                              "user_stats": {"total_harvest": 50}})
    assert plugin._get_seeds(refresh=True) == {"success": True, "seeds": catalog,
                                   "user_stats": {"total_harvest": 50}, "cached": False}
    assert plugin._seed_id == "120"
    assert plugin.get_data("farm_status") is None


def test_seed_load_failure_does_not_replace_saved_default(plugin):
    plugin.init_plugin({"seed_id": "120"})
    plugin.get_farm_data = Mock(return_value={"success": False, "message": "读取失败"})
    assert plugin._get_seeds(refresh=True) == {"success": False, "message": "读取失败"}
    plugin._save_steal_config({"steal_crops": ["萝卜"]})
    assert plugin._seed_id == plugin.config["seed_id"] == "120"


@pytest.mark.parametrize("change", ["plugin_cookie", "site_cookie", "site_url"])
def test_seed_cache_is_persistent_read_only_and_scoped_to_account(plugin, monkeypatch, change):
    farm = {"success": True, "seeds": [{"id": 120, "name": "樱桃", "unlock_harvest": 40}],
            "user_stats": {"total_harvest": 50}}
    get = Mock(return_value=response(farm))
    monkeypatch.setattr(requests, "get", get)
    plugin._get_page_meta = Mock(return_value={})
    plugin.init_plugin({"seed_id": "120"})
    get.assert_not_called()
    assert plugin._get_seeds()["cached"] is False
    assert get.call_count == 1
    expected = {"success": True, "seeds": farm["seeds"], "user_stats": farm["user_stats"], "cached": True}
    assert plugin._get_seeds() == expected
    plugin.init_plugin(plugin._get_config())
    assert plugin._get_seeds() == expected
    assert get.call_count == 1
    # Scheduled/manual farm reads also keep the catalog and unlock counts current.
    farm["user_stats"]["total_harvest"] = 100
    get.return_value = response(farm)
    plugin.get_farm_data()
    assert plugin._get_seeds()["user_stats"]["total_harvest"] == 100
    get.return_value = response({"success": False, "message": "读取失败"})
    assert not plugin._get_seeds(refresh=True)["success"]
    assert plugin._get_seeds()["user_stats"]["total_harvest"] == 100
    before_change = get.call_count
    if change == "plugin_cookie":
        plugin._save_config({"cookie": "session=two"})
    else:
        site = SimpleNamespace(url="https://si-qi.xyz", ua="fixture-UA", cookie="session=one")
        setattr(site, "cookie" if change == "site_cookie" else "url",
                "session=two" if change == "site_cookie" else "https://siqi.xyz")
        plugin._siteoper.get_by_domain = lambda _: site
    assert not plugin._get_seeds()["success"]
    assert get.call_count == before_change + 1
    assert "session=" not in json.dumps(plugin.get_data("farm_status"))
    get.return_value = response({"success": True, "seeds": [{"id": 200, "name": "西瓜"}],
                                 "user_stats": {"total_harvest": 0}})
    assert plugin._get_seeds()["cached"] is False
    assert plugin._get_seeds()["seeds"] == [{"id": 200, "name": "西瓜"}]
    assert plugin._seed_id == "120"
    requests.post.assert_not_called()


@pytest.mark.parametrize("old_snapshot", [None, {"success": True, "seeds": []},
    {"success": True, "seeds": [{"id": 999}], "user_stats": {"total_harvest": 9999}}])
def test_old_frontend_plain_seed_get_refreshes_missing_or_unverified_cache(plugin, monkeypatch, old_snapshot):
    # v2.1.1 only calls GET /seeds; it never sends refresh=true or handles needs_refresh.
    plugin.save_data("farm_status", old_snapshot)
    get = Mock(return_value=response({"success": True,
        "seeds": [{"id": 120, "name": "樱桃"}], "user_stats": {"total_harvest": 50}}))
    monkeypatch.setattr(requests, "get", get)
    plugin._get_page_meta = Mock(return_value={})
    endpoint = next(r["endpoint"] for r in plugin.get_api() if r["path"] == "/seeds")
    fresh = endpoint()
    assert fresh == {"success": True, "seeds": [{"id": 120, "name": "樱桃"}],
                     "user_stats": {"total_harvest": 50}, "cached": False}
    assert endpoint() == {**fresh, "cached": True}
    assert get.call_count == 1
    assert plugin.get_data("seed_catalog") is None
    assert plugin._get_data()["seeds"] == fresh["seeds"]
    requests.post.assert_not_called()


def test_completed_task_and_reloaded_config_share_the_same_snapshot(plugin, module, monkeypatch):
    plugin.init_plugin({"enabled": True, "auto_plant": False, "auto_harvest": False, "notify": False,
                        "seed_id": "120", "steal_crops": ["玉米"]})
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"success": True,
        "current_username": "fixture-user", "seeds": [{"id": 120, "name": "樱桃"}],
        "user_stats": {"total_harvest": 50}, "user_lands": []})))
    plugin._get_page_meta = Mock(return_value={})
    plugin._farm_task()
    stored = json.loads(json.dumps(plugin.data))
    assert "seed_catalog" not in stored
    reloaded = module.SiqiFram()
    reloaded.data = stored
    reloaded.init_plugin(plugin._get_config())
    requests.get.reset_mock()
    assert reloaded._get_data()["current_username"] == "fixture-user"
    assert reloaded._get_seeds() == {"success": True, "seeds": stored["farm_status"]["seeds"],
                                    "user_stats": {"total_harvest": 50}, "cached": True}
    assert reloaded._seed_id == "120" and reloaded._steal_crops == ["玉米"]
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_shared_farm_snapshot_takes_precedence_over_legacy_seed_catalog(plugin):
    context = plugin._seed_cache_key()
    plugin.save_data("farm_status", {"success": True, "_cache_context": context,
                                      "seeds": [{"id": 200}], "user_stats": {"total_harvest": 100}})
    plugin.save_data("seed_catalog", {"context": context, "seeds": [{"id": 120}],
                                      "user_stats": {"total_harvest": 50}})
    assert plugin._get_seeds() == {"success": True, "seeds": [{"id": 200}],
                                   "user_stats": {"total_harvest": 100}, "cached": True}
    requests.get.assert_not_called()
    requests.post.assert_not_called()


@pytest.mark.parametrize("kind, message", [
    ("read", "数据读取中"), ("farm", "农场任务执行中"), ("config", "配置保存中"),
])
def test_busy_reason_matches_active_operation_and_cached_seeds_never_wait(plugin, kind, message):
    plugin.init_plugin({"enabled": True, "auto_harvest": False, "auto_plant": False, "notify": False})
    plugin.save_data("seed_catalog", {"context": plugin._seed_cache_key(),
                                      "seeds": [{"id": 120}], "user_stats": {"total_harvest": 50}})
    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return {"success": True, "seeds": [{"id": 120}]}

    plugin.get_farm_data = Mock(side_effect=blocked)
    if kind == "config":
        plugin.update_config = Mock(side_effect=blocked)
    routes = plugin.get_api()
    seed_route = next(r["endpoint"] for r in routes if r["path"] == "/seeds")
    save_route = next(r["endpoint"] for r in routes if r["path"] == "/config" and r["methods"] == ["POST"])
    run = {"read": lambda: seed_route(refresh=True), "farm": plugin._farm_task,
           "config": lambda: save_route({"notify": False})}[kind]
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(2)
        assert seed_route()["cached"] is True
        assert next(r["endpoint"] for r in routes if r["path"] == "/data")()["success"] is False
        assert seed_route(refresh=True) == {"success": False, "message": message + "，请稍后重试"}
        assert save_route({})["message"] == message + "，请稍后重试"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert plugin._run_activity == ""
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def steal_fixture(plugin, monkeypatch):
    # Deliberately non-sequential IDs: crop names must come from the site catalog.
    crops = [(91, "萝卜"), (5, "西红柿"), (62, "玉米"),
             (27, "茄子"), (9, "蘑菇"), (120, "樱桃"), (1, "西瓜")]
    farm = {"success": True, "seeds": [{"id": i, "name": name} for i, name in crops]}
    victim = {"success": True, "victim_id": 88, "max_steal_count": 20,
              "steal_count_today": 0, "victim_lands": [{"id": 3, "unlocked": 1}],
              "victim_plots": [
                  {"land_id": 3, "plot_index": n, "seed_id": i, "is_ready": 1}
                  for n, (i, name) in enumerate(crops)
              ] + [{"land_id": 3, "plot_index": 7, "seed_id": 999,
                    "seed_name": "萝卜", "is_ready": 1}]}
    plugin.get_farm_data = Mock(return_value=farm)
    post = Mock(side_effect=lambda url, **kwargs: response(
        victim if kwargs["data"]["action"] == "get_victim_farm"
        else {"success": True, "reward": 2}))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return victim, post


def test_automatic_steal_only_six_named_crops_from_catalog(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    result = plugin._steal_once()
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert result["success"] and len(writes) == 6
    assert [item["plot_index"] for item in writes] == [0, 1, 2, 3, 4, 5]
    assert plugin._is_daily_action_done("steal")


def test_subset_filters_maturity_and_leaves_daily_retry_available(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_crops = ["樱桃"]
    victim["victim_plots"][5].update(is_ready=0, harvest_time=int(time.time()) + 500)
    result = plugin._steal_once()
    assert not result["success"] and "所选范围" in result["message"]
    assert not plugin._is_daily_action_done("steal")
    assert [call.kwargs["data"]["action"] for call in post.call_args_list] == ["get_victim_farm"]
    victim["victim_plots"][5]["is_ready"] = 1
    assert plugin._steal_once()["success"]
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert [item["plot_index"] for item in writes] == [5]


@pytest.mark.parametrize("catalog", [None, {"success": False}, {"success": True, "seeds": []}])
def test_empty_selection_or_missing_catalog_sends_no_steal_requests(plugin, catalog):
    if catalog is None:
        plugin._steal_crops = []
    else:
        plugin.get_farm_data = Mock(return_value=catalog)
    assert not plugin._steal_once()["success"]
    assert not plugin._is_daily_action_done("steal")
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_manual_api_rejects_unselected_unknown_forged_and_replayed_plots(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_crops = ["萝卜"]
    target = plugin._get_steal_target()
    assert target["victim_plots"][0]["steal_allowed"]
    assert not target["victim_plots"][1]["steal_allowed"]
    post.reset_mock()
    for payload in [
        {"victim_id": 88, "land_id": 3, "plot_index": 1},
        {"victim_id": 88, "land_id": 3, "plot_index": 7, "seed_name": "萝卜"},
        {"victim_id": 99, "land_id": 3, "plot_index": 0},
        {"victim_id": 88, "land_id": 3},
    ]:
        assert not plugin._steal_plot(payload)["success"]
    post.assert_not_called()
    allowed = {"victim_id": 88, "land_id": 3, "plot_index": 0}
    assert plugin._steal_plot(allowed)["success"]
    assert not plugin._steal_plot(allowed)["success"]
    assert post.call_count == 1
    plugin._finish_stealing()
    assert plugin._steal_target == {}


def test_crop_filter_supports_legacy_nested_plots(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    nested = victim.pop("victim_plots")[:1]
    victim["lands"] = [{"id": 3, "plots": [{k: v for k, v in nested[0].items() if k != "land_id"}]}]
    assert plugin._steal_once()["success"]
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert len(writes) == 1 and writes[0]["land_id"] == 3


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
    assert "其他操作处理中" in results[0]["message"]
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
    stealing = client.post("/steal-config", json={
        "auto_steal": True, "steal_crops": ["玉米"], "seed_id": "1",
    }).json()
    assert stealing == {"success": True, "message": "偷菜配置已保存",
                        "config": {"auto_steal": True, "steal_crops": ["玉米"]}}
    assert client.get("/config").json()["seed_id"] == "9"
    plugin.get_farm_data = Mock(return_value={"success": True,
        "seeds": [{"id": 91, "name": "萝卜", "unlock_harvest": 0},
                  {"id": 200, "name": "西瓜", "unlock_harvest": 100}],
        "user_stats": {"total_harvest": 50}})
    assert len(client.get("/seeds").json()["seeds"]) == 2
    assert len(client.get("/seeds", params={"refresh": True}).json()["seeds"]) == 2
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

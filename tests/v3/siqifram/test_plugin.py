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


@pytest.fixture
def quota_clock(module, monkeypatch):
    real_datetime = module.datetime
    clock = {"now": real_datetime(2026, 10, 20, 12, 0, tzinfo=module.ZoneInfo("Asia/Shanghai"))}

    class Clock(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz) if tz else clock["now"].replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    return clock


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
    assert plugin.plugin_version == entry["version"] == "2.2.3"
    assert entry["system_version"] == ">=3.0.0"
    assert entry["release"] is True  # Federation packaging requirement.
    assert plugin.plugin_author == "xchenya" and plugin.author_url == "https://github.com/xchenya"
    assert "KoWming/MoviePilot-Plugins" in (PLUGIN / "README.md").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in (PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert plugin.get_render_mode() == ("vue", "dist/assets-v2.2.3")
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
    assert plugin._get_data() == {"success": True, "seeds": [{"id": 1}], "cached": True,
                                  "steal_paused_until": None}
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
    before = {k: v for k, v in plugin._get_config().items()
              if k not in {"auto_steal", "steal_crops", "steal_cron", "steal_refresh_count"}}
    saved = plugin._save_steal_config({"auto_steal": True, "steal_crops": ["玉米"],
                                      "steal_cron": "*/20 * * * *", "steal_refresh_count": 7,
                                      "seed_id": "1", "cron": "bad"})
    assert saved["config"] == {"auto_steal": True, "steal_crops": ["玉米"], "steal_cron": "*/20 * * * *",
                               "steal_refresh_count": 7}
    assert {k: v for k, v in plugin._get_config().items() if k in before} == before
    assert plugin.config["seed_id"] == "120"
    plugin._save_config({"notify": False})
    assert plugin._seed_id == "120" and plugin._auto_steal and plugin._steal_crops == ["玉米"]
    plugin.init_plugin(plugin.config)
    assert plugin._seed_id == "120" and plugin._steal_crops == ["玉米"]
    assert plugin._steal_cron == "*/20 * * * *"
    assert plugin._steal_refresh_count == 7


@pytest.mark.parametrize("value,expected", [(None, 3), ("bad", 3), (-1, 1), (0, 1), (1, 1),
                                          ("5", 5), (20, 20), (99, 20)])
def test_target_refresh_budget_normalizes_on_load_and_independent_save(plugin, value, expected):
    plugin.init_plugin({"seed_id": "120", "cookie": "session=custom", "steal_refresh_count": value})
    assert plugin._get_config()["steal_refresh_count"] == expected
    saved = plugin._save_steal_config({"steal_refresh_count": value, "seed_id": "1", "cookie": "forged"})
    assert saved["config"]["steal_refresh_count"] == expected
    assert plugin._seed_id == "120" and plugin._cookie == "session=custom"
    plugin._save_config({"notify": False})
    assert plugin.config["steal_refresh_count"] == expected


def test_old_configs_and_models_default_to_three_total_targets(plugin, module):
    assert module.FarmConfig().steal_refresh_count == module.StealConfig().steal_refresh_count == 3
    plugin.init_plugin({"steal_refresh_count": 20})
    plugin.init_plugin({"seed_id": "120"})
    assert plugin._get_steal_config()["steal_refresh_count"] == 3


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
    plugin._steal_refresh_count = 1  # Existing single-target contract fixtures keep their original scope.
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


def target_refresh_fixture(plugin, monkeypatch, seed_ids):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_refresh_count = 3
    plugin._steal_crops = ["茄子"]
    targets = [{**victim, "victim_id": 88 + index, "victim_name": f"测试目标{index + 1}",
                "max_steal_count": 1, "victim_plots": [
                    {"land_id": 3, "plot_index": 0, "seed_id": seed_id, "is_ready": 1}]}
               for index, seed_id in enumerate(seed_ids)]
    remaining = iter(targets)
    post.side_effect = lambda url, **kwargs: response(next(remaining)
        if kwargs["data"]["action"] == "get_victim_farm" else {"success": True, "reward": 2})
    return targets, post


def test_saved_budget_checks_two_misses_then_steals_the_third_eggplant_target(plugin, monkeypatch):
    targets, post = target_refresh_fixture(plugin, monkeypatch, [91, 62, 27])
    route = next(r for r in plugin.get_api() if r["path"] == "/steal")
    result = route["endpoint"]({"steal_refresh_count": 20, "steal_crops": ["萝卜"]})
    assert result["success"] and result["stolen_count"] == 1
    assert result["checked_targets"] == result["target_limit"] == 3
    assert [item["target_id"] for item in result["attempts"]] == [88, 89, 90]
    assert [item["matched_plots"] for item in result["attempts"]] == [0, 0, 1]
    assert result["attempts"][0]["excluded"]["unselected_crop"] == 1
    assert result["attempts"][1]["excluded"]["unselected_crop"] == 1
    assert "本轮已检查 3/3 个目标" in result["message"]
    assert all(f"ID：{item['victim_id']}" in result["message"] for item in targets)
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == [
        "get_victim_farm", "get_victim_farm", "get_victim_farm", "steal_vegetable", "finish_stealing"]
    assert post.call_args_list[3].kwargs["data"]["victim_id"] == 90
    assert plugin.get_farm_data.call_count == 4  # Every target has a fresh precheck, then post-success refresh.
    assert plugin._steal_target == {}


def test_patrol_logs_all_checked_targets_and_uses_the_same_saved_budget(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "notify": False})
    _, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    plugin._steal_task()
    message = plugin.get_data("last_steal_result")
    assert "本轮已检查 2/3 个目标" in message and "ID：88" in message and "ID：89" in message
    assert "ID：90" not in message
    assert sum(c.kwargs["data"]["action"] == "get_victim_farm" for c in post.call_args_list) == 2


def test_no_match_budget_stops_without_stealing_finishing_or_pausing(plugin, monkeypatch):
    _, post = target_refresh_fixture(plugin, monkeypatch, [91, 62, 27])
    plugin._steal_refresh_count = 2
    result = plugin._steal_once()
    assert not result["success"] and result["checked_targets"] == result["target_limit"] == 2
    assert "本轮已检查 2/2 个目标" in result["message"]
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["get_victim_farm"] * 2
    assert len(result["attempts"]) == 2 and plugin.get_data("steal_quota_pause") is None


def test_first_matching_target_stops_even_with_a_larger_refresh_budget(plugin, monkeypatch):
    _, post = target_refresh_fixture(plugin, monkeypatch, [27, 27, 27])
    plugin._steal_refresh_count = 20
    result = plugin._steal_once()
    assert result["success"] and result["checked_targets"] == 1 and result["target_limit"] == 20
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == [
        "get_victim_farm", "steal_vegetable", "finish_stealing"]


@pytest.mark.parametrize("failure", ["target_failure", "unknown_quota", "zero_quota", "can_steal_false",
                                     "missing_target_id", "write_failure"])
def test_non_empty_target_failures_do_not_refresh_to_a_third_target(plugin, monkeypatch, failure):
    targets, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    if failure == "target_failure":
        targets[1].update(success=False, message="目标读取失败")
    elif failure == "unknown_quota":
        targets[1]["max_steal_count"] = None
    elif failure == "zero_quota":
        targets[1]["steal_count_today"] = 1
    elif failure == "can_steal_false":
        targets[1]["can_steal"] = False
    elif failure == "missing_target_id":
        targets[1].pop("victim_id")
    else:
        original = post.side_effect
        post.side_effect = lambda url, **kwargs: (response({"success": False, "message": "偷取被拒绝"})
            if kwargs["data"]["action"] == "steal_vegetable" else original(url, **kwargs))
    result = plugin._steal_once()
    assert not result["success"]
    if failure == "missing_target_id":
        assert "目标无效" in result["message"] and result["checked_targets"] == 1
    expected = ["get_victim_farm", "get_victim_farm"]
    if failure == "write_failure":
        expected.append("steal_vegetable")
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == expected
    assert plugin._steal_target == {}


@pytest.mark.parametrize("action", ["get_victim_farm", "steal_vegetable"])
def test_uncertain_second_target_never_refreshes_or_finishes(plugin, monkeypatch, action):
    _, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    original = post.side_effect

    def uncertain(url, **kwargs):
        if kwargs["data"]["action"] == action and post.call_count >= 2:
            raise requests.ReadTimeout("lost response")
        return original(url, **kwargs)

    post.side_effect = uncertain
    route = next(r for r in plugin.get_api() if r["path"] == "/steal")
    result = route["endpoint"]({})
    assert not result["success"] and result["uncertain"] is True
    expected = ["get_victim_farm", "get_victim_farm"]
    if action == "steal_vegetable":
        expected.append("steal_vegetable")
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == expected
    assert plugin._steal_target == {}


@pytest.mark.parametrize("blocked", [
    {"success": False, "message": "获取农场失败"},
    {"success": True, "can_steal": False},
    {"success": True, "max_steal_count": 1, "steal_count_today": 1},
])
def test_each_refresh_rechecks_current_farm_and_stops_when_it_is_blocked(plugin, monkeypatch, blocked):
    _, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    initial = plugin.get_farm_data.return_value
    plugin.get_farm_data.side_effect = [initial, blocked]
    result = plugin._steal_once()
    assert not result["success"] and result["checked_targets"] == 1
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["get_victim_farm"]
    assert plugin.get_farm_data.call_count == 2


def test_new_exhaustion_pause_is_not_treated_as_an_empty_target_to_refresh(plugin, monkeypatch):
    targets, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    targets[0]["msg"] = "今日可偷数量已用完"
    result = plugin._steal_once()
    assert not result["success"] and result["checked_targets"] == 1
    assert plugin._get_steal_pause() is not None
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["get_victim_farm"]


def test_manual_refresh_continues_after_old_pause_expires_with_fresh_positive_quota(plugin, monkeypatch, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "steal_crops": ["茄子"]})
    plugin._observe_steal_quota({"success": True, "max_steal_count": 3, "steal_count_today": 3},
                              plugin._today_key(), plugin._seed_cache_key())
    assert plugin._steal_paused_until() == "2026-10-21 00:00:00"
    quota_clock["now"] = quota_clock["now"].replace(day=21, hour=0, minute=1)
    targets, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    for target in targets:
        target["max_steal_count"] = 3
    farm = {**plugin.get_farm_data.return_value, "can_steal": True,
            "max_steal_count": 3, "steal_count_today": 0}
    plugin.get_farm_data.side_effect = [farm, farm, {**farm, "steal_count_today": 1}]
    route = next(r for r in plugin.get_api() if r["path"] == "/steal")
    result = route["endpoint"]({})
    assert result["success"] and result["checked_targets"] == 2
    assert [item["target_id"] for item in result["attempts"]] == [88, 89]
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == [
        "get_victim_farm", "get_victim_farm", "steal_vegetable", "finish_stealing"]
    assert plugin._steal_paused_until() is None


@pytest.mark.parametrize("stop_before_first", [True, False])
def test_stop_prevents_initial_or_subsequent_target_refresh(plugin, monkeypatch, stop_before_first):
    _, post = target_refresh_fixture(plugin, monkeypatch, [91, 27, 27])
    if stop_before_first:
        plugin.stop_service()
    else:
        original = post.side_effect

        def stop_after_response(url, **kwargs):
            result = original(url, **kwargs)
            plugin.stop_service()
            return result

        post.side_effect = stop_after_response
    result = plugin._steal_once()
    assert not result["success"] and "已停止" in result["message"]
    assert result["checked_targets"] == (0 if stop_before_first else 1)
    assert post.call_count == (0 if stop_before_first else 1)
    assert plugin.get_farm_data.call_count == (0 if stop_before_first else 1)
    assert plugin._steal_target == {}


def test_automatic_steal_only_six_named_crops_from_catalog(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    result = plugin._steal_once()
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert result["success"] and len(writes) == 6
    assert [item["plot_index"] for item in writes] == [0, 1, 2, 3, 4, 5]
    assert not plugin._is_daily_action_done("steal")


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


@pytest.mark.parametrize("mode", ["automatic", "manual"])
def test_same_eggplant_snapshot_with_one_remaining_works_in_both_modes(plugin, monkeypatch, mode):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_crops = ["茄子"]
    victim["steal_count_today"] = 19
    if mode == "automatic":
        result = plugin._steal_once()
        assert result["stolen_count"] == 1
        assert result["diagnostics"]["matched_plots"] == 1
    else:
        plugin._get_steal_target()
        result = plugin._steal_plot({"victim_id": 88, "land_id": 3, "plot_index": 3})
    assert result["success"]
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert writes == [{"action": "steal_vegetable", "victim_id": 88, "land_id": 3, "plot_index": 3}]


def test_unmatched_target_reports_exclusive_filter_counts_in_result_and_patrol_log(plugin, monkeypatch, module):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "notify": False, "steal_crops": ["茄子"]})
    victim, post = steal_fixture(plugin, monkeypatch)
    victim.update(victim_name="本次测试目标", steal_count_today=19,
                  victim_lands=[{"id": 3, "unlocked": 1}, {"id": 4, "unlocked": 0}],
                  victim_plots=[
                      {"land_id": 3, "plot_index": 0, "seed_id": None, "stolen": True},
                      {"land_id": 3, "plot_index": 1, "seed_id": 999, "seed_name": "茄子", "is_ready": 1},
                      {"land_id": 3, "plot_index": 2, "seed_id": 91, "is_ready": 1},
                      {"land_id": 3, "plot_index": 3, "seed_id": 27, "is_ready": 0,
                       "harvest_time": int(time.time()) + 3600},
                      {"land_id": 3, "plot_index": 4, "seed_id": 27, "is_ready": 1, "stolen": True},
                      {"land_id": 4, "plot_index": 0, "seed_id": 27, "is_ready": 0, "stolen": True},
                  ])
    result = plugin._steal_once()
    assert not result["success"] and result["remaining_steals"] == 1
    assert result["diagnostics"] == {
        "target_id": 88, "target_name": "本次测试目标", "selected_crops": ["茄子"],
        "checked_plots": 6, "matched_plots": 0,
        "excluded": {"land_unavailable": 1, "empty": 1, "unrecognized_crop": 1,
                     "unselected_crop": 1, "not_ready": 1, "already_stolen": 1},
    }
    assert "本次目标农场" in result["message"] and "本次测试目标（ID：88）" in result["message"]
    assert "检查 6 个坑位，所选作物：茄子，匹配 0 个" in result["message"]
    assert "土地不可用 1、空地 1、作物无法识别 1、作物未选 1、未成熟 1、已偷 1" in result["message"]
    plugin._steal_task()
    assert plugin.get_data("last_steal_result") == result["message"]
    assert sum(result["message"] in call.args[0] for call in module.logger.info.call_args_list) == 1
    assert [call.kwargs["data"]["action"] for call in post.call_args_list] == ["get_victim_farm"] * 2
    plugin.post_message.assert_not_called()


def test_different_returned_targets_can_have_different_selected_crop_results(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_crops = ["茄子"]
    first = {**victim, "victim_name": "没有所选作物的目标", "max_steal_count": 1,
             "victim_plots": [{"land_id": 3, "plot_index": 0, "seed_id": 91, "is_ready": 1}]}
    second = {**victim, "victim_id": 99, "victim_name": "有成熟茄子的目标", "max_steal_count": 1,
              "victim_plots": [{"land_id": 3, "plot_index": 0, "seed_id": 27, "is_ready": 1}]}
    targets = iter([first, second])
    post.side_effect = lambda url, **kwargs: response(next(targets)
        if kwargs["data"]["action"] == "get_victim_farm" else {"success": True, "reward": 2})
    first_result = plugin._steal_once()
    assert not first_result["success"]
    assert first_result["diagnostics"]["target_id"] == 88
    assert first_result["diagnostics"]["excluded"]["unselected_crop"] == 1
    assert len(post.call_args_list) == 1
    second_result = plugin._steal_once()
    assert second_result["success"] and second_result["diagnostics"]["target_id"] == 99
    writes = [call.kwargs["data"] for call in post.call_args_list
              if call.kwargs["data"]["action"] == "steal_vegetable"]
    assert len(writes) == 1 and writes[0]["victim_id"] == 99


def test_steal_route_preserves_diagnostics_saved_choices_lock_and_uncertainty(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    plugin._steal_crops = ["茄子"]
    assert plugin._auto_steal is False
    victim["victim_plots"] = [{"land_id": 3, "plot_index": 0, "seed_id": 91, "is_ready": 1}]
    route = next(r for r in plugin.get_api() if r["path"] == "/steal")
    app = FastAPI()
    app.add_api_route(**{key: value for key, value in route.items() if key != "auth"})
    client = TestClient(app)
    result = client.post("/steal", json={"steal_crops": ["萝卜"]}).json()
    assert not result["success"]
    assert result["diagnostics"]["selected_crops"] == ["茄子"]
    assert result["diagnostics"]["excluded"]["unselected_crop"] == 1
    post.reset_mock()
    with plugin._run_lock:
        busy = client.post("/steal", json={}).json()
    assert not busy["success"] and "稍后重试" in busy["message"]
    post.assert_not_called()
    victim["victim_plots"][0]["seed_id"] = 27
    original = post.side_effect

    def uncertain(url, **kwargs):
        if kwargs["data"]["action"] == "steal_vegetable":
            raise requests.ReadTimeout("lost response")
        return original(url, **kwargs)

    post.side_effect = uncertain
    result = client.post("/steal", json={}).json()
    assert not result["success"] and result["uncertain"] is True
    assert [call.kwargs["data"]["action"] for call in post.call_args_list] == ["get_victim_farm", "steal_vegetable"]
    assert plugin._steal_target == {} and plugin._run_activity == ""


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


@pytest.mark.parametrize("quota, expected", [
    ({}, None), ({"max_steal_count": 2}, None),
    ({"max_steal_count": 0, "steal_count_today": 0}, 0),
    ({"max_steal_count": 5, "steal_count_today": 2}, 3),
    ({"max_steal_count": " 5 ", "steal_count_today": "2"}, 3),
    ({"max_steal_count": 5, "steal_count_today": 8}, 0),
    ({"max_steal_count": True, "steal_count_today": 0}, None),
    ({"max_steal_count": 5, "steal_count_today": -1}, None),
    ({"max_steal_count": 5, "steal_count_today": "bad"}, None),
])
def test_steal_quota_never_guesses_missing_or_invalid_counts(plugin, quota, expected):
    assert plugin._remaining_steals(quota) == expected


@pytest.mark.parametrize("quota", [
    {"max_steal_count": None}, {"steal_count_today": None},
    {"max_steal_count": 0, "steal_count_today": 0},
    {"max_steal_count": 20, "steal_count_today": 20},
])
def test_unknown_or_zero_target_quota_sends_no_steal_or_finish(plugin, monkeypatch, quota):
    victim, post = steal_fixture(plugin, monkeypatch)
    victim.update(quota)
    result = plugin._steal_once()
    assert result["success"] is False
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["get_victim_farm"]
    assert not plugin._is_daily_action_done("steal")


@pytest.mark.parametrize("availability", [
    {"can_steal": False}, {"can_steal": "0"},
    {"max_steal_count": 5, "steal_count_today": 5},
])
def test_live_farm_precheck_stops_before_selecting_a_target(plugin, monkeypatch, availability):
    _, post = steal_fixture(plugin, monkeypatch)
    plugin.get_farm_data.return_value.update(availability)
    assert not plugin._steal_once()["success"]
    post.assert_not_called()


def test_automatic_steal_caps_writes_at_remaining_count(plugin, monkeypatch):
    victim, post = steal_fixture(plugin, monkeypatch)
    victim["steal_count_today"] = 18
    result = plugin._steal_once()
    assert result["stolen_count"] == 2
    actions = [c.kwargs["data"]["action"] for c in post.call_args_list]
    assert actions.count("get_victim_farm") == 1
    assert actions.count("steal_vegetable") == 2
    assert actions.count("finish_stealing") == 1


def test_zero_quota_pauses_only_steal_and_queued_patrols_use_no_network(plugin, module, monkeypatch, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "notify": False})
    plugin._next_run_time = quota_clock["now"] + module.timedelta(hours=1)
    plugin._get_page_meta = Mock(return_value={})
    get = Mock(return_value=response({"success": True, "max_steal_count": 1, "steal_count_today": 1,
                                      "seeds": [{"id": 27, "name": "茄子"}]}))
    monkeypatch.setattr(requests, "get", get)
    plugin._steal_task()
    pause = plugin.get_data("steal_quota_pause")
    assert pause == {"context": plugin._seed_cache_key(), "day": "2026-10-20",
                     "resume_at": int(quota_clock["now"].replace(day=21, hour=0).timestamp())}
    assert "session=one" not in json.dumps(pause)
    assert plugin._get_data()["steal_paused_until"] == "2026-10-21 00:00:00"
    assert plugin._get_status()["steal_paused_until"] == "2026-10-21 00:00:00"
    services = {s["id"]: s for s in plugin.get_service()}
    assert set(services) == {"siqifram", "siqifram-harvest", "siqifram-steal-resume"}
    resume = services["siqifram-steal-resume"]
    assert resume["trigger"] == "date" and resume["kwargs"]["misfire_grace_time"] is None
    assert resume["kwargs"]["run_date"].strftime("%Y-%m-%d %H:%M:%S") == "2026-10-21 00:00:00"
    for _ in range(3):
        plugin._steal_task()
    assert get.call_count == 1
    requests.post.assert_not_called()
    module.update_plugin_job.assert_called_once_with("SiqiFram")


@pytest.mark.parametrize("action,message", [
    ("get_victim_farm", "今日已偷过菜，明天再来吧"),
    ("steal_vegetable", "今日可偷数量已用完"),
    ("finish_stealing", "今日偷菜次数已用完。"),
])
def test_explicit_site_exhaustion_pauses_without_numeric_counts(plugin, module, monkeypatch, quota_clock, action, message):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    post = Mock(return_value=response({"success": False, "msg": message}))
    monkeypatch.setattr(requests, "post", post)
    assert not plugin._json_response(plugin._request(action, "POST"))["success"]
    assert plugin._steal_paused_until() == "2026-10-21 00:00:00"
    module.update_plugin_job.assert_called_once()
    plugin._steal_task()
    assert post.call_count == 1
    requests.get.assert_not_called()


@pytest.mark.parametrize("data", [
    {"success": True, "can_steal": False},
    {"success": True, "can_steal": False, "max_steal_count": 3, "steal_count_today": 1},
    {"success": True, "max_steal_count": 3, "steal_count_today": 1},
    {"success": False, "max_steal_count": 0, "steal_count_today": 0, "message": "读取失败"},
    {"success": False, "message": "本次目标农场未找到所选范围内的成熟作物"},
    {"success": False, "message": "请求频率过高"},
    {"success": False, "uncertain": True, "message": "写入结果不明"},
    {"success": True, "message": "偷菜成功"},
])
def test_non_exhausted_or_unknown_results_never_pause(plugin, module, quota_clock, data):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    plugin._observe_steal_quota(data, plugin._today_key(), plugin._seed_cache_key())
    assert plugin.get_data("steal_quota_pause") is None
    assert plugin._steal_paused_until() is None
    module.update_plugin_job.assert_not_called()
    requests.get.assert_not_called()
    requests.post.assert_not_called()


@pytest.mark.parametrize("total", [1, 2])
def test_successful_batch_uses_fresh_remaining_quota_to_pause(plugin, monkeypatch, quota_clock, total):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "steal_crops": ["茄子"]})
    plugin._get_page_meta = Mock(return_value={})
    state = {"used": 0}
    get = Mock(side_effect=lambda *args, **kwargs: response({"success": True,
        "can_steal": state["used"] < total, "max_steal_count": total, "steal_count_today": state["used"],
        "seeds": [{"id": 27, "name": "茄子"}]}))

    def site_post(url, **kwargs):
        action = kwargs["data"]["action"]
        if action == "get_victim_farm":
            return response({"success": True, "victim_id": 88, "max_steal_count": total,
                "steal_count_today": state["used"], "victim_plots": [
                    {"land_id": 3, "plot_index": 0, "seed_id": 27, "is_ready": 1}]})
        if action == "steal_vegetable":
            state["used"] += 1
        return response({"success": True, "reward": 2})

    post = Mock(side_effect=site_post)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    plugin._steal_task()
    assert state["used"] == 1 and plugin.post_message.call_count == 1
    assert bool(plugin._get_steal_pause()) is (total == 1)
    if total == 1:
        plugin._steal_task()
        assert get.call_count == 2 and post.call_count == 3


@pytest.mark.parametrize("manual_action", ["plot", "finish"])
def test_manual_actions_observe_fresh_zero_quota(plugin, monkeypatch, quota_clock, manual_action):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "steal_crops": ["茄子"]})
    plugin._get_page_meta = Mock(return_value={})
    plugin._steal_target = {"victim_id": 88, "max_steal_count": 1, "steal_count_today": 0,
        "victim_plots": [{"land_id": 3, "plot_index": 0, "seed_id": 27, "is_ready": 1,
                          "steal_crop_name": "茄子"}]}
    monkeypatch.setattr(requests, "get", Mock(return_value=response({
        "success": True, "max_steal_count": 1, "steal_count_today": 1})))
    monkeypatch.setattr(requests, "post", Mock(return_value=response({"success": True})))
    result = (plugin._steal_plot({"victim_id": 88, "land_id": 3, "plot_index": 0})
              if manual_action == "plot" else plugin._finish_stealing())
    assert result["success"] and plugin._steal_paused_until() == "2026-10-21 00:00:00"


@pytest.mark.parametrize("first_callback", ["date", "queued_cron"])
def test_midnight_resume_waits_for_lock_and_runs_once_in_either_callback_order(plugin, module, quota_clock, first_callback):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "notify": False})
    plugin._observe_steal_quota({"success": True, "max_steal_count": 1, "steal_count_today": 1},
                              plugin._today_key(), plugin._seed_cache_key())
    resume = next(s for s in plugin.get_service() if s["id"] == "siqifram-steal-resume")
    quota_clock["now"] = quota_clock["now"].replace(day=21, hour=0)
    plugin._steal_once = Mock(return_value={"success": False, "message": "没有可偷作物"})
    module.update_plugin_job.reset_mock()
    entered = threading.Event()

    def run():
        entered.set()
        if first_callback == "date":
            resume["func"](**resume["func_kwargs"])
        else:
            plugin._steal_task()

    if first_callback == "date":
        with plugin._run_lock:
            worker = threading.Thread(target=run)
            worker.start()
            assert entered.wait(2) and worker.is_alive()
            plugin._steal_once.assert_not_called()
        worker.join(2)
        assert not worker.is_alive()
        plugin._steal_task()
    else:
        run()
        resume["func"](**resume["func_kwargs"])
    plugin._steal_once.assert_called_once_with()
    assert plugin.get_data("steal_quota_pause") is None
    assert "siqifram-steal" in {s["id"] for s in plugin.get_service()}
    assert plugin._resuming_steal is False
    assert module.update_plugin_job.call_count == (1 if first_callback == "date" else 2)
    quota_clock["now"] += module.timedelta(minutes=1)
    plugin._steal_task()
    assert plugin._steal_once.call_count == 2


def test_pause_survives_save_reload_but_not_account_switch_and_expired_pause_catches_up(plugin, module, quota_clock):
    config = {"enabled": True, "auto_steal": True, "cookie": "session=one"}
    plugin.init_plugin(config)
    plugin._observe_steal_quota({"success": True, "max_steal_count": 1, "steal_count_today": 1},
                              plugin._today_key(), plugin._seed_cache_key())
    plugin._save_config({"notify": False})
    assert "siqifram-steal-resume" in {s["id"] for s in plugin.get_service()}
    reloaded = module.SiqiFram()
    reloaded.data = dict(plugin.data)
    reloaded.init_plugin(config)
    assert reloaded._steal_paused_until() == "2026-10-21 00:00:00"
    reloaded.init_plugin({**config, "cookie": "session=two"})
    assert reloaded._steal_paused_until() is None
    assert "siqifram-steal" in {s["id"] for s in reloaded.get_service()}
    quota_clock["now"] = quota_clock["now"].replace(day=22)
    plugin.init_plugin(config)
    resume = next(s for s in plugin.get_service() if s["id"] == "siqifram-steal-resume")
    assert resume["kwargs"]["run_date"] == quota_clock["now"] + module.timedelta(seconds=1)
    plugin._steal_once = Mock(return_value={"success": False, "message": "没有可偷作物"})
    resume["func"](**resume["func_kwargs"])
    plugin._steal_once.assert_called_once()
    assert plugin.get_data("steal_quota_pause") is None


@pytest.mark.parametrize("change", [{"enabled": False}, {"auto_steal": False}, {"steal_crops": []}, "stop"])
def test_disabled_or_stopped_steal_never_registers_or_runs_resume(plugin, module, quota_clock, change):
    config = {"enabled": True, "auto_steal": True}
    plugin.init_plugin(config)
    plugin._observe_steal_quota({"success": True, "max_steal_count": 0, "steal_count_today": 0},
                              plugin._today_key(), plugin._seed_cache_key())
    resume = next(s for s in plugin.get_service() if s["id"] == "siqifram-steal-resume")
    if change == "stop":
        plugin.stop_service()
    else:
        plugin.init_plugin({**config, **change})
    assert not {s["id"] for s in plugin.get_service()} & {"siqifram-steal", "siqifram-steal-resume"}
    assert plugin._get_status()["steal_paused_until"] is None
    module.update_plugin_job.reset_mock()
    resume["func"](**resume["func_kwargs"])
    module.update_plugin_job.assert_not_called()
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_old_resume_after_external_account_change_reconciles_without_using_old_token(plugin, module, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "cookie": "session=one"})
    plugin._observe_steal_quota({"success": True, "max_steal_count": 1, "steal_count_today": 1},
                              plugin._today_key(), plugin._seed_cache_key())
    resume = next(s for s in plugin.get_service() if s["id"] == "siqifram-steal-resume")
    plugin._cookie = "session=two"
    quota_clock["now"] = quota_clock["now"].replace(day=21, hour=0)
    plugin._steal_once = Mock()
    module.update_plugin_job.reset_mock()
    resume["func"](**resume["func_kwargs"])
    plugin._steal_once.assert_not_called()
    module.update_plugin_job.assert_called_once()
    assert "siqifram-steal" in {s["id"] for s in plugin.get_service()}


@pytest.mark.parametrize("method,action", [("GET", "fetch"), ("POST", "get_victim_farm")])
def test_exhaustion_response_crossing_midnight_does_not_pause_the_new_day(plugin, module, monkeypatch, quota_clock, method, action):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    quota_clock["now"] = quota_clock["now"].replace(hour=23, minute=59, second=59)

    def delayed_response(*args, **kwargs):
        quota_clock["now"] += module.timedelta(seconds=2)
        return response({"success": True, "max_steal_count": 1, "steal_count_today": 1})

    monkeypatch.setattr(requests, method.lower(), Mock(side_effect=delayed_response))
    assert plugin._json_response(plugin._request(action, method))["success"]
    assert plugin.get_data("steal_quota_pause") is None
    module.update_plugin_job.assert_not_called()


def test_quota_observation_uses_actual_request_cookie_not_a_later_account(plugin, module, monkeypatch, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "cookie": "session=one"})

    def account_changed_during_request(*args, **kwargs):
        assert kwargs["headers"]["cookie"] == "session=one"
        plugin._cookie = "session=two"
        return response({"success": True, "max_steal_count": 1, "steal_count_today": 1})

    monkeypatch.setattr(requests, "post", Mock(side_effect=account_changed_during_request))
    assert plugin._json_response(plugin._request("get_victim_farm", "POST"))["success"]
    assert plugin.get_data("steal_quota_pause") is None
    module.update_plugin_job.assert_not_called()


def test_scheduler_failure_preserves_site_result_and_expired_recovery_record(plugin, module, monkeypatch, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    module.update_plugin_job.side_effect = RuntimeError("scheduler unavailable")
    monkeypatch.setattr(requests, "get", Mock(return_value=response({
        "success": True, "max_steal_count": 1, "steal_count_today": 1})))
    assert plugin._json_response(plugin._request("fetch"))["success"]
    pause = dict(plugin.get_data("steal_quota_pause"))
    requests.get.reset_mock()
    plugin._steal_task()
    requests.get.assert_not_called()
    quota_clock["now"] = quota_clock["now"].replace(day=21, hour=0)
    plugin._steal_once = Mock(return_value={"success": False, "message": "检查完成，无可偷作物"})
    plugin._resume_steal_task(pause["context"], pause["resume_at"])
    assert plugin.get_data("steal_quota_pause") == pause
    assert plugin.get_data("last_steal_result") == "检查完成，无可偷作物"
    assert "siqifram-steal-resume" in {s["id"] for s in plugin.get_service()}
    assert module.logger.warning.call_count == 2


def test_pause_indicator_is_serialized_in_data_refresh_and_status(plugin, module, quota_clock):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    plugin._observe_steal_quota({"success": True, "max_steal_count": 1, "steal_count_today": 1},
                              plugin._today_key(), plugin._seed_cache_key())
    plugin.save_data("farm_status", {"success": True})
    plugin.get_farm_data = Mock(return_value={"success": True})
    app = FastAPI()
    for route in plugin.get_api():
        if route["path"] in {"/data", "/refresh", "/status"}:
            app.add_api_route(**{k: v for k, v in route.items() if k != "auth"})
    client = TestClient(app)
    assert client.get("/data").json()["steal_paused_until"] == "2026-10-21 00:00:00"
    assert client.post("/refresh", json={}).json()["steal_paused_until"] == "2026-10-21 00:00:00"
    assert client.get("/status").json()["steal_paused_until"] == "2026-10-21 00:00:00"
    plugin._auto_steal = False
    assert client.get("/data").json()["steal_paused_until"] is None
    requests.get.assert_not_called()
    requests.post.assert_not_called()


def test_three_schedules_are_separate_and_steal_settings_remain_isolated(plugin, module):
    plugin.save_data("next_harvest_at", int(time.time()) + 3600)
    plugin.init_plugin({"enabled": True, "cron": "0 */4 * * *", "auto_steal": True,
                        "auto_harvest": False, "auto_plant": False, "notify": False})
    services = {s["id"]: s for s in plugin.get_service()}
    assert set(services) == {"siqifram", "siqifram-harvest", "siqifram-steal"}
    assert str(services["siqifram"]["trigger"]) == "cron[month='*', day='*', day_of_week='*', hour='*/4', minute='0']"
    assert str(services["siqifram-steal"]["trigger"]) == "cron[month='*', day='*', day_of_week='*', hour='*', minute='*/15']"
    plugin.get_farm_data = Mock(return_value={"success": True, "user_lands": []})
    plugin._steal_once = Mock(return_value={"success": False, "message": "没有可偷作物"})
    for key in ("siqifram", "siqifram-harvest"):
        services[key]["func"](**services[key]["func_kwargs"])
    plugin._steal_once.assert_not_called()
    services["siqifram-steal"]["func"]()
    plugin._steal_once.assert_called_once_with()
    plugin._save_steal_config({"steal_cron": "invalid"})
    assert plugin._steal_cron == "*/15 * * * *" and plugin._cron == "0 */4 * * *"
    plugin._save_steal_config({"auto_steal": False})
    assert "siqifram-steal" not in {s["id"] for s in plugin.get_service()}
    assert plugin._get_status()["last_steal_result"] == "没有可偷作物"
    plugin.post_message.assert_not_called()


@pytest.mark.parametrize("close_on_finish", [False, True])
def test_each_steal_patrol_obeys_live_quota_even_after_old_daily_marker(plugin, monkeypatch, close_on_finish):
    plugin.init_plugin({"enabled": True, "auto_steal": True, "steal_crops": ["萝卜"]})
    plugin.save_data("auto_steal_done_date", plugin._today_key())
    state = {"used": 0, "closed": False}

    def live_farm():
        return {"success": True, "can_steal": not state["closed"] and state["used"] < 3,
                "max_steal_count": 3, "steal_count_today": state["used"],
                "seeds": [{"id": 91, "name": "萝卜"}]}

    def site_post(url, **kwargs):
        action = kwargs["data"]["action"]
        if action == "get_victim_farm":
            return response({"success": True, "victim_id": 88, "max_steal_count": 3,
                "steal_count_today": state["used"], "victim_plots": [
                    {"land_id": 3, "plot_index": 0, "seed_id": 91, "is_ready": 1}]})
        if action == "steal_vegetable":
            state["used"] += 1
        elif action == "finish_stealing":
            state["closed"] = close_on_finish
        return response({"success": True, "reward": 2})

    plugin.get_farm_data = Mock(side_effect=live_farm)
    post = Mock(side_effect=site_post)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    for _ in range(4):
        plugin._steal_task()
    expected = 1 if close_on_finish else 3
    assert state["used"] == expected
    assert sum(c.kwargs["data"]["action"] == "get_victim_farm" for c in post.call_args_list) == expected
    assert plugin.post_message.call_count == expected
    assert ("站点当前不允许" if close_on_finish else "今日可偷数量已用完") in plugin.get_data("last_steal_result")
    assert plugin._run_activity == ""


def test_failed_finish_is_reported_after_partial_success(plugin, monkeypatch):
    _, post = steal_fixture(plugin, monkeypatch)
    original = post.side_effect
    post.side_effect = lambda url, **kwargs: (response({"success": False, "message": "结束被拒绝"})
        if kwargs["data"]["action"] == "finish_stealing" else original(url, **kwargs))
    result = plugin._steal_once()
    assert not result["success"] and result["stolen_count"] == 6
    assert "结束被拒绝" in result["message"]
    assert sum(c.kwargs["data"]["action"] == "finish_stealing" for c in post.call_args_list) == 1
    post.reset_mock()
    assert not plugin._steal_plot({"victim_id": 88, "land_id": 3, "plot_index": 0})["success"]
    post.assert_not_called()


def test_uncertain_steal_does_not_retry_or_finish_the_session(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    _, post = steal_fixture(plugin, monkeypatch)
    original = post.side_effect

    def uncertain(url, **kwargs):
        if kwargs["data"]["action"] == "steal_vegetable":
            raise requests.ReadTimeout("lost response")
        return original(url, **kwargs)

    post.side_effect = uncertain
    plugin._steal_task()
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["get_victim_farm", "steal_vegetable"]
    assert "结果不明" in plugin.get_data("last_steal_result")
    assert plugin._run_activity == ""
    assert plugin._steal_target == {}


def test_maturity_waits_for_busy_lock_but_steal_patrol_skips_it(plugin):
    plugin.init_plugin({"enabled": True, "auto_steal": True})
    plugin._farm_task = Mock()
    plugin._steal_once = Mock()
    entered = threading.Event()
    with plugin._run_lock:
        steal = threading.Thread(target=plugin._steal_task)
        steal.start()
        steal.join(2)
        plugin._steal_once.assert_not_called()
        assert not steal.is_alive()
        assert plugin.get_data("last_steal_run") is None
        harvest = threading.Thread(target=lambda: (entered.set(), plugin._harvest_task()))
        harvest.start()
        assert entered.wait(2)
        plugin._farm_task.assert_not_called()
        assert harvest.is_alive()
    harvest.join(2)
    assert not harvest.is_alive()
    plugin._farm_task.assert_called_once_with(reschedule=True)


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
                        "config": {"auto_steal": True, "steal_crops": ["玉米"], "steal_cron": "*/15 * * * *",
                                   "steal_refresh_count": 3}}
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

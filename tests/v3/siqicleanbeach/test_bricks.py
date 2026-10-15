"""No credentials, no site traffic: test complete task and persisted config with mocks."""
import ast
import copy
import json
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup

from .test_plugin import CODE, _plugin_class


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("Live network forbidden")))
    monkeypatch.setattr(time, "sleep", Mock())
    # Session mock forwards to each test's mocked transport, never real network.
    def session():
        return SimpleNamespace(post=lambda *a, **kw: requests.post(*a, **kw),
                               get=lambda *a, **kw: requests.get(*a, **kw), close=Mock())
    monkeypatch.setattr(requests, "Session", Mock(side_effect=session))


@pytest.fixture
def plugin():
    class Base:
        update_config = Mock()
        post_message = Mock()

    cls = copy.deepcopy(_plugin_class())
    cls.bases = [ast.Name(id="Base", ctx=ast.Load())]
    for method in cls.body:
        if isinstance(method, ast.FunctionDef) and method.name == "run_once_command":
            method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    ns = dict(Base=Base, requests=requests, BeautifulSoup=BeautifulSoup, threading=threading,
              time=time, datetime=datetime, re=__import__("re"), Any=Any, Dict=Dict,
              List=List, Optional=Optional, Tuple=Tuple, Event=object,
              logger=Mock(), SiteOper=Mock(), NotificationType=SimpleNamespace(Plugin="plugin"),
              IntervalTrigger=Mock(), CronTrigger=Mock(), EventType=SimpleNamespace(PluginAction="action"))
    exec(compile(module, str(CODE), "exec"), ns)
    p = ns["SiQiCleanBeach"]()
    p._SiQiCleanBeach__get_site_cookie = Mock(return_value="")
    p._cookie = "c_secure_pass=secret-cookie"
    p._auto_brick = True
    p.update_config = Mock()
    p.post_message = Mock()
    p._test_logger = ns["logger"]
    p._test_site_oper = ns["SiteOper"]
    p._test_interval = ns["IntervalTrigger"]
    p._test_cron = ns["CronTrigger"]
    return p


def state(daily=0, moved=None, **changes):
    data = dict(success=True, daily_bricks=daily, last_brick_time=0,
                last_daily_reset="server-day", server_now=2_000_000, next_brick_reset_ts=2_050_000)
    if moved is not None:
        data["bricks_moved"] = moved
    data.update(changes)
    return data


def response(data=None, status=200, text="", location=""):
    result = Mock(status_code=status, text=text, headers={"Location": location})
    result.json = Mock(return_value=data) if data is not None else Mock(side_effect=ValueError())
    return result


def posts(monkeypatch, *responses):
    post = Mock(side_effect=responses)
    monkeypatch.setattr(requests, "post", post)
    return post


def move(p):
    return p._SiQiCleanBeach__move_bricks(p._cookie)


def test_single_request_reads_increment(plugin, monkeypatch):
    post = posts(monkeypatch, response(state(43)), response(state(50, 7)))
    result = move(plugin)
    assert result["success"] and result["bricks_moved"] == 7 and result["daily_bricks"] == 50
    assert [c.kwargs["data"] for c in post.call_args_list] == [{"action": "sync_game_state"}, {"action": "move_brick"}]
    assert all(c.kwargs["verify"] and not c.kwargs["allow_redirects"] for c in post.call_args_list)


def test_limit_is_normal_skip(plugin, monkeypatch):
    post = posts(monkeypatch, response(state(50)))
    assert move(plugin)["success"]
    assert post.call_count == 1


def test_serial_multiple_requests(plugin, monkeypatch):
    post = posts(monkeypatch, response(state()), response(state(20, 20)), response(state(40, 20)), response(state(50, 10)))
    result = move(plugin)
    assert result["bricks_moved"] == 50 and result["success"]
    assert post.call_count == 4 and time.sleep.call_count == 2


@pytest.mark.parametrize("change", [dict(bricks_moved=0), dict(daily_bricks=0), dict(bricks_moved=2), dict(last_daily_reset="next-day"), dict(server_now=1_999_999)])
def test_no_progress_or_inconsistent_response_stops(plugin, monkeypatch, change):
    post = posts(monkeypatch, response(state()), response(state(1, 1, **change)))
    assert not move(plugin)["success"]
    assert post.call_count == 2


@pytest.mark.parametrize("bad", [dict(success=True), state(daily_bricks="0"), state(server_now=True), state(next_brick_reset_ts=0), state(last_daily_reset=None)])
def test_missing_or_invalid_sync_fields_no_write(plugin, monkeypatch, bad):
    post = posts(monkeypatch, response(bad))
    assert not move(plugin)["success"]
    assert post.call_count == 1


@pytest.mark.parametrize("bad,auth", [(response(text="成功"), False), (response(status=500), False),
                                    (response(status=401), True), (response(status=403), True),
                                    (response(status=302, location="login.php"), True),
                                    (response(text='<form action="login.php"><input type="password"></form>'), True),
                                    (response(dict(success=False, message="Cookie失效")), True),
                                    (response(dict(success=False, message="业务失败")), False),
                                    (response(dict(success="true")), False), (response([1]), False)])
def test_http_json_auth_and_business_failures(plugin, monkeypatch, bad, auth):
    post = posts(monkeypatch, bad)
    result = move(plugin)
    assert not result["success"] and bool(result.get("auth_failed")) is auth
    assert post.call_count == 1


def test_failed_move_retains_service_daily_and_reset(plugin, monkeypatch):
    post = posts(monkeypatch, response(state(40)), response(state(50, success=False, message="限额")))
    result = move(plugin)
    assert result["success"] and result["daily_bricks"] == 50 and result["bricks_moved"] == 0
    assert post.call_count == 2


@pytest.mark.parametrize("after", [state(7), state(), dict(success=False, message="同步失败"), dict(success=False, message="未登录")])
def test_timeout_queries_state_and_never_retries(plugin, monkeypatch, after):
    post = posts(monkeypatch, response(state()), requests.Timeout(), response(after))
    result = move(plugin)
    assert post.call_count == 3
    assert post.call_args_list[-1].kwargs["data"] == {"action": "sync_game_state"}
    assert result["bricks_moved"] == (7 if after.get("daily_bricks") == 7 else 0)
    posts(monkeypatch, response(state(7)))
    assert "等待" in move(plugin)["message"]
    # Reload retains ambiguous-write protection.
    plugin._update_stats()
    plugin.init_plugin(plugin.update_config.call_args.args[0])
    posts(monkeypatch, response(state(7)))
    assert "等待" in move(plugin)["message"]


def test_service_reset_unlocks_uncertain_request(plugin, monkeypatch):
    plugin._stats["brick_uncertain_reset"] = "old-day"
    posts(monkeypatch, response(state()), response(state(50, 50)))
    assert move(plugin)["success"]


def test_cooldown_uses_server_time(plugin, monkeypatch):
    plugin._stats["brick_last_run_server"] = 1_999_000
    post = posts(monkeypatch, response(state()))
    assert "冷却" in move(plugin)["message"]
    assert post.call_count == 1
    # Server reset alone does not override the configured cooldown.
    posts(monkeypatch, response(state(last_daily_reset="new-day", server_now=2_100_000, next_brick_reset_ts=2_150_000)),
          response(state(50, 50, last_daily_reset="new-day", server_now=2_100_001, next_brick_reset_ts=2_150_000)))
    assert move(plugin)["bricks_moved"] == 50


def test_beach_cooldown_does_not_block_bricks_and_inventory(plugin, monkeypatch):
    post = posts(monkeypatch, response(dict(success=False, message="沙滩冷却中")), response(state()), response(state(50, 50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='''<div class="inventory-grid"><div class="inventory-item"><div class="item-name">砖块</div><div class="item-count">83</div></div></div>''')))
    result = plugin.run_clean_task()
    assert result["status"] == "completed" and result["data"]["brick"]["bricks_moved"] == 50
    assert plugin._inventory["砖块"]["count"] == 83 and plugin._stats["inventory_refreshed"]
    assert "清理：沙滩冷却中" in plugin.post_message.call_args.kwargs["text"]
    assert "本次50块" in plugin.post_message.call_args.kwargs["text"]
    record = plugin._stats["history"][-1]
    assert record["clean"]["message"] == "沙滩冷却中" and record["brick"]["daily_bricks"] == 50
    assert record["brick_inventory"] == 83 and post.call_count == 3
    assert not plugin._lock.locked()


@pytest.mark.parametrize("failure_at", ["enter", "collect", "sync", "move"])
def test_auth_failure_stops_later_requests(plugin, monkeypatch, failure_at):
    sequence = []
    if failure_at != "enter":
        sequence += [response(dict(success=True))]
    if failure_at in {"sync", "move"}:
        sequence += [response(dict(success=True, collected=2))]
    if failure_at == "move":
        sequence += [response(state())]
    sequence += [response(status=401)]
    post = posts(monkeypatch, *sequence)
    get = Mock(side_effect=AssertionError("No later requests after auth failure"))
    monkeypatch.setattr(requests, "get", get)
    assert plugin.run_clean_task()["status"] == "auth_failed"
    assert post.call_count == len(sequence)
    get.assert_not_called()


def test_cached_inventory_not_reported_as_refreshed(plugin, monkeypatch):
    plugin._inventory = {"砖块": {"name": "砖块", "count": 9, "icon": "🧱"}}
    plugin._stats["last_update"] = 123
    posts(monkeypatch, response(dict(success=False, message="业务失败")), response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(status=500)))
    result = plugin.run_clean_task()
    assert not result["data"]["inventory_refreshed"] and plugin._stats["last_update"] == 123
    assert "缓存，非本次刷新" in result["message"]
    page = json.dumps(plugin.get_page(), ensure_ascii=False)
    assert "砖块" in page and "缓存，非本次刷新" in page


def test_old_config_and_every_save_path(plugin):
    plugin.init_plugin({"enabled": True, "inventory": {"砖块": {"count": 12}}})
    assert not plugin._auto_brick and plugin._brick_cooldown_minutes == 1440
    assert plugin._inventory["砖块"]["count"] == 12
    plugin._queue_manual_run = Mock(return_value=True)
    plugin.init_plugin(dict(auto_brick=True, brick_cooldown_minutes=30, run_once=True))
    assert plugin.update_config.call_args.args[0]["auto_brick"] is True
    assert plugin.update_config.call_args.args[0]["brick_cooldown_minutes"] == 30
    plugin._update_stats()
    assert plugin.update_config.call_args.args[0]["auto_brick"] is True
    form, defaults = plugin.get_form()
    assert defaults["auto_brick"] is True and defaults["brick_cooldown_minutes"] == 30
    assert '"model": "auto_brick"' in json.dumps(form)


def test_default_disabled_preserves_clean_task(plugin, monkeypatch):
    plugin._auto_brick = False
    post = posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=3)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    result = plugin.run_clean_task()
    assert result["data"]["trash"] == 3 and result["data"]["brick"]["message"] == "未开启"
    assert plugin._stats["clean_result"] == "收集3个垃圾"
    assert post.call_count == 2


def test_response_never_saves_cookie_in_message(plugin, monkeypatch):
    posts(monkeypatch, response(dict(success=False, message="Cookie secret-cookie 失效")))
    result = move(plugin)
    assert "secret-cookie" not in str(result)


def test_lock_released_on_unexpected_exception(plugin):
    plugin._SiQiCleanBeach__enter_beach = Mock(side_effect=RuntimeError("secret-cookie"))
    result = plugin.run_clean_task()
    assert result["status"] == "error" and not plugin._lock.locked()
    assert "secret-cookie" not in str(result)


def test_one_brick_per_request_is_bounded(plugin, monkeypatch):
    post = posts(monkeypatch, response(state()), *(response(state(i, 1)) for i in range(1, 51)))
    result = move(plugin)
    assert result["success"] and result["bricks_moved"] == 50
    assert post.call_count == 51 and time.sleep.call_count == 49


def test_missing_move_fields_stops_and_persists_guard(plugin, monkeypatch):
    post = posts(monkeypatch, response(state()), response(dict(success=True)))
    result = move(plugin)
    assert not result["success"] and "字段" in result["message"]
    assert post.call_count == 2 and plugin._stats["brick_uncertain_reset"] == "server-day"


def test_partial_progress_remains_visible_after_failure(plugin, monkeypatch):
    posts(monkeypatch, response(state()), response(state(10, 10)), response(dict(success=False, message="服务端业务失败")))
    result = move(plugin)
    assert not result["success"] and result["bricks_moved"] == 10 and result["daily_bricks"] == 10


def test_timeout_crossing_reset_waits_for_new_day_reset(plugin, monkeypatch):
    posts(monkeypatch, response(state(45)), requests.Timeout(), response(state(5, last_daily_reset="next-day")))
    result = move(plugin)
    assert result["bricks_moved"] == 0 and result["daily_bricks"] == 5
    assert plugin._stats["brick_uncertain_reset"] == "next-day"


def test_missing_cookie_no_requests(plugin):
    plugin._cookie = ""
    assert plugin.run_clean_task()["status"] == "auth_failed"


def test_non_json_beach_does_not_claim_success(plugin, monkeypatch):
    plugin._auto_brick = False
    post = posts(monkeypatch, response(text="收集了20个垃圾，成功"))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    result = plugin.run_clean_task()
    assert result["data"]["trash"] == 0 and result["status"] == "partial"
    assert post.call_count == 1


def test_legacy_beach_status_json_still_collects(plugin, monkeypatch):
    plugin._auto_brick = False
    posts(monkeypatch, response(dict(status="success")), response(dict(status="success", data={"collected": 4})))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    assert plugin.run_clean_task()["data"]["trash"] == 4


def test_sync_timeout_can_recover_with_one_query_retry(plugin, monkeypatch):
    post = posts(monkeypatch, requests.ReadTimeout(), response(state(50)))
    result = move(plugin)
    assert result["success"] and post.call_count == 2
    assert all(c.kwargs["data"] == {"action": "sync_game_state"} for c in post.call_args_list)
    assert time.sleep.call_count == 1
    assert all(c.kwargs["timeout"] == (10, 30) for c in post.call_args_list)


def test_both_sync_timeouts_do_not_send_move_or_mark_uncertain_write(plugin, monkeypatch):
    post = posts(monkeypatch, requests.ConnectTimeout(), requests.ReadTimeout())
    result = move(plugin)
    assert not result["success"] and result["message"] == "搬砖前状态同步超时，未发送搬砖请求"
    assert post.call_count == 2 and "brick_uncertain_reset" not in plugin._stats
    logs = str(plugin._test_logger.mock_calls)
    assert "sync_game_state" in logs and "ReadTimeout" in logs and "耗时" in logs
    assert "secret-cookie" not in logs


def test_write_timeout_only_retries_followup_query(plugin, monkeypatch):
    post = posts(monkeypatch, response(state()), requests.ReadTimeout(), requests.ReadTimeout(), response(state(8)))
    result = move(plugin)
    actions = [c.kwargs["data"]["action"] for c in post.call_args_list]
    assert actions == ["sync_game_state", "move_brick", "sync_game_state", "sync_game_state"]
    assert result["bricks_moved"] == 8 and result["recovered_from_sync"]
    assert post.call_args_list[1].kwargs["timeout"] == (10, 30)
    assert plugin._stats["brick_uncertain_reset"] == "server-day"


def test_failed_followup_query_not_reported_as_synced(plugin, monkeypatch):
    posts(monkeypatch, response(state()), requests.ReadTimeout(), requests.ReadTimeout(), requests.ReadTimeout())
    result = move(plugin)
    assert "状态同步失败" in result["message"] and "结果仍不确定" in result["message"]
    assert result["bricks_moved"] == 0


def test_site_ua_used_for_post_and_inventory(plugin, monkeypatch):
    plugin._test_site_oper.return_value.get_by_domain.return_value = SimpleNamespace(cookie="c_secure_pass=site-secret", ua="Configured browser UA")
    real_get_cookie = type(plugin)._SiQiCleanBeach__get_site_cookie.__get__(plugin)
    assert real_get_cookie() == "c_secure_pass=site-secret"
    post = posts(monkeypatch, response(state(50)))
    get = Mock(return_value=response(text='<div class="inventory-grid"></div>'))
    monkeypatch.setattr(requests, "get", get)
    move(plugin)
    plugin._SiQiCleanBeach__fetch_inventory(plugin._cookie)
    assert post.call_args.kwargs["headers"]["user-agent"] == get.call_args.kwargs["headers"]["user-agent"] == "Configured browser UA"


def test_browser_ua_fallback_present_on_post(plugin, monkeypatch):
    post = posts(monkeypatch, response(state(50)))
    move(plugin)
    assert post.call_args.kwargs["headers"]["user-agent"].startswith("Mozilla/5.0")


def test_live_browser_state_fixture_passes_validation(plugin):
    observed = {"success": True, "daily_bricks": 0, "last_brick_time": 0,
                "last_daily_reset": "2026-10-13", "server_now": 1791884577,
                "next_brick_reset_ts": 1791907200}
    assert plugin._SiQiCleanBeach__valid_brick_state(observed, sync=True)


def test_whole_task_uses_one_session_for_clean_sync_moves_and_inventory(plugin, monkeypatch):
    session = Mock()
    session.post.side_effect = [response(dict(success=True)), response(dict(success=True, collected=2)),
                                response(state(48)), response(state(49, 1)), response(state(50, 1))]
    session.get.return_value = response(text='<div class="inventory-grid"></div>')
    create = Mock(return_value=session)
    monkeypatch.setattr(requests, "Session", create)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Must use task session")))
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("Must use task session")))
    result = plugin.run_clean_task()
    assert result["status"] == "completed" and result["data"]["brick"]["bricks_moved"] == 2
    create.assert_called_once_with()
    assert session.post.call_count == 5 and session.get.call_count == 1
    assert all(c.kwargs["timeout"] == (10, 30) for c in session.post.call_args_list)
    assert session.get.call_args.kwargs["timeout"] == (10, 30)
    session.close.assert_called_once_with()
    assert plugin._session is None and not plugin._lock.locked()


def test_session_closed_and_lock_released_after_transport_failure(plugin, monkeypatch):
    session = Mock()
    session.post.side_effect = RuntimeError("secret-cookie")
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    result = plugin.run_clean_task()
    assert result["status"] == "error"
    session.close.assert_called_once_with()
    assert plugin._session is None and not plugin._lock.locked()
    assert "secret-cookie" not in str(plugin._test_logger.mock_calls)


def test_missing_cookie_never_opens_session(plugin):
    plugin._cookie = ""
    assert plugin.run_clean_task()["status"] == "auth_failed"
    requests.Session.assert_not_called()

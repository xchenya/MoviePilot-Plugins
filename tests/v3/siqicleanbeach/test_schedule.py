"""Server-day scheduling, independent beach cooldown, and legacy compatibility."""
import json
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup

from .test_bricks import plugin, no_network, posts, response, state, move


def html(last=1800, interval=7200, server=2000):
    return f'''<script>let gameData = {{lastBeachTime: {last}, beachInterval: {interval},
    serverTimeOffset: {server} - Math.floor(Date.now() / 1000), inventory: {{}} }};</script>
    <div class="inventory-grid"></div>'''


def test_new_install_auto_and_old_config_unchanged(plugin):
    plugin.init_plugin({})
    assert plugin._schedule_mode == "auto" and not plugin._auto_brick
    plugin.init_plugin({"enabled": True, "auto_brick": True, "brick_cooldown_minutes": 1440})
    assert plugin._schedule_mode == "interval"
    plugin.init_plugin({"schedule_mode": "cron", "cron": "5 0 * * *"})
    assert plugin._cron == "5 0 * * *" and plugin._schedule_mode == "cron"


def test_auto_schedules_only_earliest_due_without_periodic_checks(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "auto_brick": True,
                        "check_interval_minutes": 60,
                        "stats": {"due_schedule_version": 1, "beach_due_at": 1600, "brick_due_at": 4600}})
    assert plugin.get_service() == []
    plugin._test_interval.assert_not_called()
    job = plugin._scheduler.add_job.call_args
    assert job.kwargs["trigger"] == "date" and job.kwargs["run_date"].timestamp() == 1600
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    requests.Session.assert_not_called()
    plugin.update_config.assert_not_called()
    plugin.post_message.assert_not_called()


def test_fixed_time_is_cron_not_auto_poll(plugin):
    plugin._enabled, plugin._schedule_mode = True, "cron"
    plugin._cron = "5 0 * * *"
    service = plugin.get_service()[0]
    plugin._test_cron.from_crontab.assert_called_once_with("5 0 * * *")
    assert service["kwargs"] == {"scheduled": True}


@pytest.mark.parametrize("mode", ["auto", "cron"])
def test_server_reset_overrides_old_1440_minute_block_in_new_modes(plugin, monkeypatch, mode):
    plugin._schedule_mode = mode
    plugin._stats["brick_last_run_server"] = 1_999_900
    posts(monkeypatch, response(state()), response(state(50, 50)))
    assert move(plugin)["bricks_moved"] == 50


def test_beach_time_uses_server_relative_delay_not_local_date(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 100)
    plugin._SiQiCleanBeach__read_beach_cooldown(BeautifulSoup(html(), "html.parser"))
    assert plugin._stats["beach_due_at"] == 7115
    assert plugin._stats["beach_cooldown_refreshed"]


@pytest.mark.parametrize("markup", ["<script>unknown()</script>", html(last=3000), html(interval=0),
                                    html(server=0), html().replace("2000 - Math.floor(Date.now() / 1000)", "12"),
                                    html().replace("beachInterval: 7200", "beachInterval: 7200 * 2")])
def test_unknown_or_bad_bootstrap_not_guessed(plugin, markup):
    plugin._SiQiCleanBeach__read_beach_cooldown(BeautifulSoup(markup, "html.parser"))
    assert "beach_due_at" not in plugin._stats


def test_auto_beach_waits_while_bricks_run_and_records_reset(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats["beach_due_at"] = 8000
    post = posts(monkeypatch, response(state(49)), response(state(50, 1)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    result = plugin.run_clean_task(scheduled=True)
    assert result["data"]["clean"]["skipped"]
    assert result["data"]["brick"]["bricks_moved"] == 1
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["sync_game_state", "move_brick"]
    assert plugin._stats["brick_due_at"] == 51015
    assert plugin._stats["beach_due_at"] == 8015


def test_auto_brick_waits_while_beach_runs(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=999, brick_due_at=8000)
    post = posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=3)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    result = plugin.run_clean_task(scheduled=True)
    assert result["data"]["trash"] == 3 and plugin._stats["brick_due_at"] == 8000
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["enter_beach", "collect_all_trash"]


def test_manual_run_still_checks_site_even_before_cached_due(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=4600, brick_due_at=4600)
    post = posts(monkeypatch, response(dict(success=False, message="冷却中")), response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    assert plugin.run_clean_task()["status"] == "completed"
    assert post.call_count == 2


def test_missing_beach_fields_queries_later_without_blind_entry(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)
    plugin._schedule_mode, plugin._auto_brick = "auto", False
    post = posts(monkeypatch)
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    plugin.run_clean_task(scheduled=True)
    assert plugin._stats["beach_due_at"] == 1300
    assert "等待重查" in plugin._stats["beach_due_source"]
    post.assert_not_called()


def test_due_times_survive_every_save_and_reload(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats.update(due_schedule_version=1, beach_due_at=4600, brick_due_at=4600)
    plugin._update_stats()
    saved = plugin.update_config.call_args.args[0]
    plugin.init_plugin(saved)
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    form, defaults = plugin.get_form()
    assert defaults["schedule_mode"] == "auto"
    assert form is None
    assert "站点冷却" in plugin.get_stats_api()["data"]["display"]["schedule"]
    saved["run_once"] = True
    plugin._queue_manual_run = Mock(return_value=True)
    plugin.init_plugin(saved)
    assert plugin.update_config.call_args.args[0]["schedule_mode"] == "auto"
    assert plugin.update_config.call_args.args[0]["stats"]["brick_due_at"] == 4600


def test_uncertain_write_protection_still_blocks_in_auto(plugin, monkeypatch):
    plugin._schedule_mode = "auto"
    plugin._stats["brick_uncertain_reset"] = "server-day"
    post = posts(monkeypatch, response(state(1)))
    assert not move(plugin)["success"] and post.call_count == 1


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, -1, "tomorrow", 10**400])
def test_bad_cached_dates_do_not_crash_page_or_stall_scheduler(plugin, monkeypatch, invalid):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=invalid, brick_due_at=invalid)
    assert "异常" in plugin._SiQiCleanBeach__due_text("brick_due_at")
    plugin.get_stats_api()
    post = posts(monkeypatch, response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    assert post.call_count == 1 and not plugin._lock.locked()
    assert post.call_args.kwargs["data"]["action"] == "sync_game_state"


@pytest.mark.parametrize("remaining", [0, -1, 172801, 10**400])
def test_abnormal_server_reset_never_reaches_write(plugin, monkeypatch, remaining):
    post = posts(monkeypatch, response(state(next_brick_reset_ts=2_000_000 + remaining)))
    result = move(plugin)
    assert not result["success"] and "字段" in result["message"]
    assert post.call_count == 1


@pytest.mark.parametrize("remaining", [295, 50000])
def test_slow_inventory_does_not_shift_server_reset(plugin, monkeypatch, remaining):
    clock = [1000]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin._schedule_mode = "auto"
    plugin._stats["beach_due_at"] = 999
    posts(monkeypatch, response(dict(success=False, message="冷却中")), response(state(50, next_brick_reset_ts=2_000_000 + remaining)))

    def inventory(*args, **kwargs):
        clock[0] += 45
        return response(text=html())

    monkeypatch.setattr(requests, "get", inventory)
    plugin.run_clean_task(scheduled=True)
    assert plugin._stats["brick_due_at"] == 1000 + remaining + 15


def test_stopping_task_does_not_send_more_bricks_or_invent_uncertain_write(plugin, monkeypatch):
    def post(*args, **kwargs):
        action = kwargs["data"]["action"]
        if action == "enter_beach":
            return response(dict(success=False, message="冷却中"))
        if action == "sync_game_state":
            return response(state())
        assert action == "move_brick"
        plugin.stop_service()
        return response(state(1, 1))

    transport = Mock(side_effect=post)
    monkeypatch.setattr(requests, "post", transport)
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("No requests after stopping")))
    result = plugin.run_clean_task()
    assert result["status"] == "cancelled" and result["data"]["brick"]["bricks_moved"] == 1
    assert transport.call_count == 3 and "brick_uncertain_reset" not in plugin._stats
    assert plugin._session is None and not plugin._lock.locked()


def test_reloading_cancels_collection_and_keeps_fresh_runtime_state(plugin, monkeypatch):
    def enter(*args, **kwargs):
        plugin._stats["history"] = [{"result": "new-runtime-record"}]
        plugin._stats["brick_uncertain_reset"] = "latest-safety-marker"
        plugin.init_plugin({"enabled": False, "stats": {"history": [], "brick_uncertain_reset": "stale"}})
        return response(dict(success=True))

    post = Mock(side_effect=enter)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("No requests after reload")))
    result = plugin.run_clean_task()
    assert result["status"] == "cancelled" and post.call_count == 1
    assert plugin._stats["history"][0]["result"] == "new-runtime-record"
    assert plugin._stats["brick_uncertain_reset"] == "latest-safety-marker"
    assert not plugin._lock.locked()


def test_disabled_queued_schedule_does_not_request_site(plugin):
    plugin._enabled = False
    assert plugin.run_clean_task(scheduled=True)["status"] == "disabled"
    requests.Session.assert_not_called()


def test_non_whitelisted_server_clock_expression_is_rejected(plugin):
    markup = html().replace("Math.floor(Date.now() / 1000)", "Math.floor(Date.now() / 1000) + 600")
    plugin._SiQiCleanBeach__read_beach_cooldown(BeautifulSoup(markup, "html.parser"))
    assert "beach_due_at" not in plugin._stats


@pytest.mark.parametrize("bad_item", [
    '<div class="item-name">砖块</div><div class="item-count">未知</div>',
    '<div class="item-name">砖块</div><div class="item-count">-5</div>',
    '<div class="item-name">砖块</div>',
    '<div class="item-count">22</div>',
    '<div class="item-name">木材</div><div class="item-count">22</div>',
])
def test_partial_or_bad_inventory_never_overwrites_cache(plugin, monkeypatch, bad_item):
    plugin._auto_brick = False
    plugin._inventory = {"砖块": {"name": "砖块", "count": 42, "icon": "🧱"}}
    plugin._stats["last_update"] = 123
    posts(monkeypatch, response(dict(success=False, message="冷却中")))
    markup = f'''<div class="inventory-grid"><div class="inventory-item">
    <div class="item-name">木材</div><div class="item-count">114</div></div>
    <div class="inventory-item">{bad_item}</div></div>'''
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=markup)))
    result = plugin.run_clean_task()
    assert result["data"]["inventory_refreshed"] is False
    assert plugin._inventory["砖块"]["count"] == 42 and "木材" not in plugin._inventory
    assert plugin._stats["last_update"] == 123


def test_stopping_queued_manual_task_is_not_cleared_by_worker_start(plugin, monkeypatch):
    queued = {}

    def deferred_thread(*, target, kwargs, daemon):
        queued.update(target=target, kwargs=kwargs)
        return Mock(start=lambda: plugin.stop_service())

    monkeypatch.setattr(threading, "Thread", deferred_thread)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Queued stopped task must not write")))
    assert plugin._queue_manual_run()
    assert queued["target"](**queued["kwargs"])["status"] == "cancelled"
    assert not plugin._lock.locked()


def test_non_finite_legacy_minutes_fall_back_without_crashing(plugin):
    plugin.init_plugin({"interval_minutes": float("inf"), "brick_cooldown_minutes": float("inf")})
    assert plugin._interval_minutes == 121


def test_stopped_service_cannot_restart_from_already_queued_schedule(plugin):
    plugin.stop_service()
    assert plugin.run_clean_task(scheduled=True)["status"] == "disabled"
    requests.Session.assert_not_called()


def test_bad_reset_in_failed_sync_cannot_overflow_final_scheduler(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats["beach_due_at"] = 999
    posts(monkeypatch, response(dict(success=False, message="冷却中")),
          response(state(50, success=False, next_brick_reset_ts=10**400)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    assert plugin.run_clean_task(scheduled=True)["status"] == "partial"
    assert plugin._stats["brick_due_at"] == 1300 and not plugin._lock.locked()


@pytest.mark.parametrize("value", [None, "60", 0, -3, "bad", float("inf")])
def test_obsolete_check_interval_does_not_delay_initial_sync(plugin, monkeypatch, value):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "check_interval_minutes": value})
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 1015
    plugin._test_interval.assert_not_called()


def test_obsolete_interval_controls_are_removed_from_all_save_paths_and_form(plugin):
    plugin._queue_manual_run = Mock(return_value=True)
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "check_interval_minutes": 25, "run_once": True})
    assert "check_interval_minutes" not in plugin.update_config.call_args.args[0]
    plugin._update_stats()
    saved = plugin.update_config.call_args.args[0]
    assert "check_interval_minutes" not in saved
    plugin.init_plugin(saved)
    form, defaults = plugin.get_form()
    assert "check_interval_minutes" not in defaults
    assert '"model": "check_interval_minutes"' not in json.dumps(form)
    assert '"model": "brick_cooldown_minutes"' not in json.dumps(form)
    assert plugin.get_stats_api()["data"]["display"]["schedule"] == "按站点冷却"


@pytest.mark.parametrize("separate_results", [False, True])
def test_panel_shows_compact_dates_and_result_without_changing_saved_details(plugin, separate_results):
    plugin._schedule_mode = "auto"
    due = datetime(2026, 10, 15, 18, 15, 34, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    brief = "清理：沙滩冷却中，请稍候！；搬砖：已达每日上限，正常跳过"
    legacy = "旧配置执行结果"
    plugin._stats.update(beach_due_at=due, brick_due_at=due, last_result=legacy)
    if separate_results:
        plugin._stats.update(clean_result="沙滩冷却中，请稍候！", brick_result="已达每日上限，正常跳过",
                             last_result=brief + "；本次0块，今日50/50，库存2001（本次已刷新）")
    saved_result = plugin._stats["last_result"]
    info = plugin.get_stats_api()["data"]["display"]
    assert info["schedule"] == "按站点冷却"
    assert info["beach_next"] == info["brick_next"] == "2026-10-15 18:15"
    assert info["last_result"] == (brief if separate_results else legacy)
    assert plugin._stats["last_result"] == saved_result
    assert "18:15:34（约" in plugin._SiQiCleanBeach__due_text("beach_due_at")


def test_existing_auto_config_ignores_legacy_execution_interval(plugin):
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "interval_minutes": 121})
    plugin._test_interval.assert_not_called()
    assert plugin._interval_minutes == 121

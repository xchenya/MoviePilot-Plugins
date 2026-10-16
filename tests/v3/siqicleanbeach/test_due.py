"""One-shot scheduling and the current collected_items contract; no live site actions."""
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED

from .test_bricks import plugin, no_network, posts, response, state
from .test_schedule import html


@pytest.mark.parametrize("payload,expected", [
    ({"collected_items": {"木材": 2, "瓶子": "3"}}, 5),
    ({"data": {"collected_items": {"塑料袋": 4}}}, 4),
    ({"collected_items": {}}, 0),
    ({"data": {}, "collected": 3}, 3),
    ({"collected": "5"}, 5),
    ({}, None),
    ({"collected_items": {"木材": -2}}, None),
    ({"collected_items": {"木材": True}}, None),
    ({"collected": False}, None),
])
def test_collection_success_is_separate_from_known_count(plugin, monkeypatch, payload, expected):
    plugin._auto_brick = False
    posts(monkeypatch, response({"success": True}), response({"success": True, **payload}))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    result = plugin.run_clean_task()
    assert result["status"] == "completed" and result["data"]["trash"] == expected
    assert plugin._stats["history"][-1]["status"] == "completed"
    if expected is None:
        assert "数量未知" in result["message"] and "收集0个" not in result["message"]
    assert "全部完成" in plugin.post_message.call_args.kwargs["text"]


def test_manual_normal_cooldowns_are_completed(plugin, monkeypatch):
    posts(monkeypatch, response(dict(success=False, message="沙滩冷却中，请稍候！")), response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    result = plugin.run_clean_task()
    assert result["status"] == "completed"
    assert result["data"]["clean"]["skipped"] and result["data"]["brick"]["skipped"]
    assert "全部完成" in plugin.post_message.call_args.kwargs["text"]


def test_actual_business_failure_still_reports_partial(plugin, monkeypatch):
    posts(monkeypatch, response(dict(success=True)), response(dict(success=False, message="背包已满")),
          response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    result = plugin.run_clean_task()
    assert result["status"] == "partial" and "背包已满" in result["message"]


def test_initial_sync_waits_silently_and_schedules_real_due_times(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    post = posts(monkeypatch, response(state(50)))
    get = Mock(return_value=response(text=html()))
    monkeypatch.setattr(requests, "get", get)
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    assert plugin._stats["beach_due_at"] == 8015 and plugin._stats["brick_due_at"] == 51015
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 8015
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["sync_game_state"]
    get.assert_called_once()
    plugin.post_message.assert_not_called()
    assert not plugin._stats["history"]


def test_unknown_beach_cooldown_retries_only_queries_with_backoff(plugin, monkeypatch):
    clock = [1000]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin._schedule_mode, plugin._auto_brick = "auto", False
    post = posts(monkeypatch)
    get = Mock(return_value=response(text='<div class="inventory-grid"></div>'))
    monkeypatch.setattr(requests, "get", get)
    for delay in (300, 900, 1800, 3600, 3600):
        plugin.run_clean_task(scheduled=True)
        assert plugin._stats["beach_due_at"] == clock[0] + delay
        clock[0] += delay
    post.assert_not_called()
    assert get.call_count == 5


@pytest.mark.parametrize("reply", [response(status=401), response(status=403),
                                  response(text='<form action="login.php"><input type="password"></form>')])
def test_initial_cookie_failure_blocks_all_writes_and_pauses_timer(plugin, monkeypatch, reply):
    plugin._schedule_mode = "auto"
    post = posts(monkeypatch)
    monkeypatch.setattr(requests, "get", Mock(return_value=reply))
    assert plugin.run_clean_task(scheduled=True)["status"] == "auth_failed"
    assert plugin._auth_blocked
    assert plugin.run_clean_task(scheduled=True)["status"] == "disabled"
    post.assert_not_called()
    plugin._test_scheduler.assert_not_called()


def test_confirmed_entry_falls_back_to_two_hours_when_inventory_times_out(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode, plugin._auto_brick = "auto", False
    plugin._stats["beach_due_at"] = 999
    posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected_items={"木材": 2})))
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.ReadTimeout()))
    result = plugin.run_clean_task(scheduled=True)
    assert result["status"] == "completed" and not result["data"]["inventory_refreshed"]
    assert plugin._stats["beach_due_at"] == 8215
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 8215


def test_preflight_inventory_is_not_reported_as_post_write_refresh(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    posts(monkeypatch, response(state(49)), response(state(50, 1)))
    monkeypatch.setattr(requests, "get", Mock(side_effect=[response(text=html()), requests.ReadTimeout()]))
    result = plugin.run_clean_task(scheduled=True)
    assert not result["data"]["inventory_refreshed"] and "缓存，非本次刷新" in result["message"]


def test_migration_syncs_once_and_preserves_uncertain_write_guard(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "auto_brick": True,
                        "check_interval_minutes": 60, "brick_cooldown_minutes": 1440,
                        "stats": {"beach_due_at": 8000, "brick_due_at": 90000,
                                  "brick_uncertain_reset": "server-day"}})
    assert "beach_due_at" not in plugin._stats and "brick_due_at" not in plugin._stats
    assert plugin._stats["brick_uncertain_reset"] == "server-day"
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 1015


def test_stop_reload_and_old_callback_cannot_restart_task(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto"})
    scheduler = plugin._scheduler
    old_callback = scheduler.add_job.call_args
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto"})
    scheduler.shutdown.assert_called_once_with(wait=False)
    old_callback.args[0](*old_callback.kwargs["args"])
    requests.Session.assert_not_called()
    scheduler = plugin._scheduler
    callback = scheduler.add_job.call_args
    plugin.stop_service()
    scheduler.shutdown.assert_called_once_with(wait=False)
    callback.args[0](*callback.kwargs["args"])
    assert plugin._scheduler is None
    requests.Session.assert_not_called()


def test_busy_due_job_rearms_locally_without_site_access(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=999, brick_due_at=9000)
    with plugin._lock:
        plugin._SiQiCleanBeach__run_due_job(plugin._schedule_generation)
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 1030
    requests.Session.assert_not_called()


def test_overdue_restart_plans_within_five_minutes_without_catchup_storm(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    plugin.init_plugin({"enabled": True, "schedule_mode": "auto", "auto_brick": True,
                        "stats": {"due_schedule_version": 1, "beach_due_at": 500, "brick_due_at": 100}})
    plugin._scheduler.add_job.assert_called_once()
    assert plugin._scheduler.add_job.call_args.kwargs["run_date"].timestamp() == 1015
    assert plugin._SiQiCleanBeach__due_text("beach_due_at", compact=True) == datetime.fromtimestamp(1015, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    requests.Session.assert_not_called()


def test_midnight_reset_runs_once_without_waiting_24_hours(plugin, monkeypatch):
    server_now, reset = 2_000_000, 2_000_120
    clock = [server_now + 4 * 3600]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=clock[0] + 7200, brick_last_run_server=server_now - 10)
    post = posts(monkeypatch,
                 response(state(50, server_now=server_now, next_brick_reset_ts=reset)),
                 response(state(0, server_now=reset + 15, next_brick_reset_ts=reset + 86400,
                                last_daily_reset="next-day")),
                 response(state(50, 50, server_now=reset + 16, next_brick_reset_ts=reset + 86400,
                                last_daily_reset="next-day")))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    assert plugin._stats["brick_due_at"] == clock[0] + 120 + 15
    clock[0] += 135
    assert plugin.run_clean_task(scheduled=True)["data"]["brick"]["bricks_moved"] == 50
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["sync_game_state", "sync_game_state", "move_brick"]


def test_real_scheduler_callback_rearms_next_date_and_shuts_down(plugin, monkeypatch):
    done = threading.Event()
    globals_ = plugin._SiQiCleanBeach__schedule_next.__func__.__globals__
    monkeypatch.setitem(globals_, "BackgroundScheduler", BackgroundScheduler)
    plugin._schedule_mode, plugin._auto_brick = "auto", False
    plugin._stats["beach_due_at"] = time.time() - 1
    posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected_items={"木材": 3})))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    try:
        plugin._SiQiCleanBeach__schedule_next()
        plugin._scheduler.add_listener(lambda event: done.set(), EVENT_JOB_EXECUTED)
        # Advance just this local deadline; all HTTP remains mocked.
        plugin._scheduler.reschedule_job("siqi_due", trigger="date",
                                         run_date=datetime.now(timezone.utc) + timedelta(milliseconds=50))
        assert done.wait(3)
        with plugin._lock:
            next_job = plugin._scheduler.get_job("siqi_due")
            assert next_job is not None and next_job.next_run_time.timestamp() > time.time() + 7200
        assert plugin._stats["history"][-1]["status"] == "completed"
    finally:
        plugin.stop_service()
    assert plugin._scheduler is None

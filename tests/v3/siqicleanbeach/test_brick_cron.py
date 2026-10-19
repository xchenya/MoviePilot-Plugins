"""Independent brick Cron, bounded safe retries, and durable server-day success display."""
import copy
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

import pytest
import requests

from .test_bricks import plugin, no_network, posts, response, state
from .test_schedule import html


def stamp(hour, minute=0, day=16):
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()


def config(mode="auto", **extra):
    return {"enabled": True, "auto_brick": True, "schedule_mode": mode,
            "cookie": "c_secure_pass=fixture-cookie",
            "brick_cron": "0 10,16 * * *", **extra}


def today_state(now, daily=0, moved=None):
    return state(daily, moved, server_now=int(now), next_brick_reset_ts=int(stamp(0, day=17)),
                 last_daily_reset="2026-10-16")


@pytest.mark.parametrize("hour,minute,expected", [(9, 50, stamp(10)), (10, 0, stamp(16)),
                                                (15, 59, stamp(16)), (16, 0, stamp(10, day=17))])
def test_cron_has_two_daily_slots_in_host_timezone(plugin, monkeypatch, hour, minute, expected):
    monkeypatch.setattr(time, "time", lambda: stamp(hour, minute))
    plugin.init_plugin(config())
    assert plugin._stats["brick_due_at"] == expected
    assert plugin._SiQiCleanBeach__due_text("brick_due_at", compact=True) == datetime.fromtimestamp(
        expected, ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    requests.Session.assert_not_called()


def test_clean_task_does_not_run_bricks_before_independent_cron(plugin, monkeypatch):
    now = stamp(9, 50)
    monkeypatch.setattr(time, "time", lambda: now)
    plugin.init_plugin(config())
    plugin._stats["beach_due_at"] = now - 1
    post = posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=5)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html(last=int(now), server=int(now)))))
    assert plugin.run_clean_task(scheduled=True)["status"] == "completed"
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["enter_beach", "collect_all_trash"]
    assert plugin._stats["brick_due_at"] == stamp(10)


@pytest.mark.parametrize("mode", ["cron", "interval"])
def test_independent_cron_runs_bricks_without_running_fixed_time_cleaning(plugin, monkeypatch, mode):
    clock = [stamp(9, 50)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin.init_plugin(config(mode))
    job = plugin._scheduler.add_job.call_args
    assert job.kwargs["run_date"].timestamp() == stamp(10)
    clock[0] = stamp(10)
    post = posts(monkeypatch, response(today_state(clock[0])), response(today_state(clock[0], 50, 50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    job.args[0](*job.kwargs["args"])
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["sync_game_state", "move_brick"]
    assert plugin._stats["brick_due_at"] == stamp(16)
    assert "10:00 搬砖成功，本次50块，今日50/50" in plugin._SiQiCleanBeach__brick_today_result()
    assert "搬砖下次执行时间：2026-10-16 16:00" in plugin.post_message.call_args.kwargs["text"]


def test_success_at_ten_is_preserved_after_cleaning_and_sixteen_limit_skip(plugin, monkeypatch):
    clock = [stamp(9, 50)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin.init_plugin(config())
    plugin._stats["beach_due_at"] = stamp(18)
    clock[0] = stamp(10)
    post = posts(monkeypatch, response(today_state(clock[0])), response(today_state(clock[0], 50, 50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    plugin.run_clean_task(scheduled=True)
    success = copy.deepcopy(plugin._stats["brick_success"])
    clock[0] = stamp(12)
    plugin._stats["beach_due_at"] = clock[0] - 1
    posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=5)))
    plugin.run_clean_task(scheduled=True)
    assert plugin._stats["brick_success"] == success
    assert "10:00 搬砖成功" in plugin._SiQiCleanBeach__brick_today_result()
    info = plugin.get_stats_api()["data"]["display"]
    assert "10:00 搬砖成功" in info["brick_today_result"] and "等待" not in info["brick_today_result"]
    clock[0] = stamp(16)
    plugin._stats["beach_due_at"] = stamp(18)
    post = posts(monkeypatch, response(today_state(clock[0], 50)))
    plugin.post_message.reset_mock()
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    assert plugin._stats["brick_success"] == success and post.call_count == 1
    plugin.post_message.assert_not_called()
    assert plugin._stats["brick_due_at"] == stamp(10, day=17)
    assert "10:00 搬砖成功" in plugin._SiQiCleanBeach__brick_today_result()
    clock[0] = stamp(0, day=17)
    assert plugin._SiQiCleanBeach__brick_today_result() == "今日暂无成功搬砖记录"


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_query_failure_retries_exactly_configured_count_then_next_cron(plugin, monkeypatch, limit):
    clock = [stamp(9, 50)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin.init_plugin(config("cron", brick_retry_limit=limit))
    clock[0] = stamp(10)
    plugin._SiQiCleanBeach__sync_game_state = Mock(return_value={"success": False, "message": "状态查询失败"})
    post = posts(monkeypatch)
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    for attempt in range(limit + 1):
        assert plugin.run_clean_task(scheduled=True, brick_only=True)["status"] == "partial"
        if attempt < limit:
            assert plugin._stats["brick_retry_count"] == attempt + 1
            assert plugin._stats["brick_due_at"] == clock[0] + (300, 900)[attempt]
            clock[0] = plugin._stats["brick_due_at"]
    assert plugin._stats["brick_due_at"] == stamp(16)
    assert plugin._stats["brick_retry_count"] == 0
    assert plugin._SiQiCleanBeach__sync_game_state.call_count == limit + 1
    post.assert_not_called()


def test_retry_succeeds_and_returns_to_cron(plugin, monkeypatch):
    clock = [stamp(9, 50)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin.init_plugin(config())
    plugin._stats["beach_due_at"] = stamp(18)
    clock[0] = stamp(10)
    post = posts(monkeypatch, response(dict(success=False, message="稍后再查")),
                 response(today_state(stamp(10, 5))), response(today_state(stamp(10, 5), 50, 50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html(last=int(stamp(16)), server=int(stamp(16))))))
    plugin.run_clean_task(scheduled=True)
    assert plugin._stats["brick_due_at"] == stamp(10, 5)
    clock[0] = stamp(10, 5)
    assert plugin.run_clean_task(scheduled=True)["status"] == "completed"
    assert post.call_count == 3 and plugin._stats["brick_retry_count"] == 0
    assert plugin._stats["brick_due_at"] == stamp(16)


def test_write_timeout_is_synchronized_without_scheduling_another_write_retry(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(10))
    plugin._brick_cron, plugin._schedule_mode = "0 10,16 * * *", "auto"
    plugin._stats.update(beach_due_at=stamp(18), brick_due_at=stamp(10))
    post = posts(monkeypatch, response(today_state(stamp(10))), requests.ReadTimeout(),
                 response(today_state(stamp(10), 1)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    plugin.run_clean_task(scheduled=True)
    assert post.call_count == 3 and plugin._stats["brick_due_at"] == stamp(16)
    assert plugin._stats["brick_retry_count"] == 0
    assert plugin._stats["brick_uncertain_reset"] == "2026-10-16"
    assert "brick_success" not in plugin._stats


def test_confirmed_business_failure_can_retry_after_fresh_state_sync(plugin, monkeypatch):
    clock = [stamp(10)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin._brick_cron, plugin._schedule_mode = "0 10,16 * * *", "auto"
    plugin._stats.update(beach_due_at=stamp(18), brick_due_at=stamp(10))
    failed = {**today_state(stamp(10)), "success": False, "message": "暂时繁忙"}
    post = posts(monkeypatch, response(today_state(stamp(10))), response(failed),
                 response(today_state(stamp(10, 5))), response(today_state(stamp(10, 5), 50, 50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    assert plugin.run_clean_task(scheduled=True)["status"] == "partial"
    assert plugin._stats["brick_due_at"] == stamp(10, 5) and "brick_uncertain_reset" not in plugin._stats
    clock[0] = stamp(10, 5)
    assert plugin.run_clean_task(scheduled=True)["status"] == "completed"
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == [
        "sync_game_state", "move_brick", "sync_game_state", "move_brick"]
    assert "10:05 搬砖成功" in plugin._SiQiCleanBeach__brick_today_result()


@pytest.mark.parametrize("expr", ["bad", "0 10 * *", "0 0 31 2 *"])
def test_invalid_brick_cron_pauses_only_bricks(plugin, monkeypatch, expr):
    monkeypatch.setattr(time, "time", lambda: stamp(9))
    plugin.init_plugin(config(brick_cron=expr))
    plugin._stats["beach_due_at"] = stamp(9) - 1
    post = posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=2)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    assert plugin.run_clean_task(scheduled=True)["status"] == "completed"
    assert "Cron 无效" in plugin._SiQiCleanBeach__due_text("brick_due_at", compact=True)
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["enter_beach", "collect_all_trash"]


def test_fields_retry_deadline_and_success_survive_all_save_paths(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(10, 2))
    plugin._queue_manual_run = Mock(return_value=True)
    old_success = {**today_state(stamp(8), 50, 50), "_received_at": stamp(8)}
    plugin.init_plugin(config(brick_retry_limit=2, run_once=True,
                              stats={"history": [{"brick": old_success}]}))
    assert "08:00 搬砖成功" in plugin._SiQiCleanBeach__brick_today_result()
    assert plugin.update_config.call_args.args[0]["brick_cron"] == "0 10,16 * * *"
    plugin._stats.update(brick_due_at=stamp(10, 5), brick_retry_count=1)
    plugin._update_stats()
    saved = copy.deepcopy(plugin.update_config.call_args.args[0])
    plugin.init_plugin(saved)
    assert plugin._stats["brick_due_at"] == stamp(10, 5) and plugin._stats["brick_retry_count"] == 1
    form, defaults = plugin.get_form()
    assert defaults["brick_cron"] == "0 10,16 * * *" and defaults["brick_retry_limit"] == 2
    assert form is None
    assert "08:00 搬砖成功" in plugin._SiQiCleanBeach__brick_today_result()


def test_changing_cron_discards_old_midnight_deadline_and_retry(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(9))
    plugin.init_plugin(config(stats={"due_schedule_version": 1, "brick_due_at": stamp(0, day=17),
                                    "brick_retry_policy": 1, "brick_retry_count": 1}))
    assert plugin._stats["brick_due_at"] == stamp(10) and plugin._stats["brick_retry_count"] == 0


def test_regular_slot_takes_priority_over_later_retry(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(9, 59))
    plugin._brick_cron = "0 10,16 * * *"
    plugin._SiQiCleanBeach__plan_brick(dict(success=False, message="查询失败"))
    assert plugin._stats["brick_due_at"] == stamp(10) and plugin._stats["brick_retry_count"] == 0


def test_default_retry_exhaustion_waits_for_next_server_day_instead_of_looping(plugin, monkeypatch):
    clock = [stamp(10)]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    plugin._SiQiCleanBeach__plan_brick(dict(success=False))
    assert plugin._stats["brick_due_at"] == stamp(10, 5) and plugin._stats["brick_retry_count"] == 1
    clock[0] = stamp(10, 5)
    plugin._SiQiCleanBeach__plan_brick(dict(success=False))
    assert plugin._stats["brick_due_at"] == stamp(0, day=17) + 15
    assert plugin._stats["brick_retry_count"] == 0


def test_disabling_pending_retry_and_host_timezone_change_recalculate_deadline(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(10, 2))
    saved = config(brick_retry_limit=0, stats={"due_schedule_version": 1, "brick_retry_policy": 1,
                   "brick_schedule_cron": "0 10,16 * * *", "brick_schedule_timezone": "Asia/Shanghai",
                   "brick_due_at": stamp(10, 5), "brick_retry_count": 1})
    plugin.init_plugin(saved)
    assert plugin._stats["brick_due_at"] == stamp(16) and plugin._stats["brick_retry_count"] == 0
    plugin._update_stats()
    saved = copy.deepcopy(plugin.update_config.call_args.args[0])
    plugin._SiQiCleanBeach__next_brick_time.__func__.__globals__["settings"].TZ = "UTC"
    plugin.init_plugin(saved)
    assert plugin._stats["brick_due_at"] == stamp(18)


def test_limit_known_without_success_time_is_not_invented(plugin, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: stamp(10))
    plugin._stats.update(daily_bricks=50, brick_day_reset_at=stamp(0, day=17))
    assert plugin._SiQiCleanBeach__brick_today_result() == "今日已达上限（成功时间未知）"


@pytest.mark.parametrize("value,expected", [(None, 1), (0, 0), (-2, 0), ("3", 3), (99, 10), ("bad", 1)])
def test_retry_limit_defaults_and_bounds(plugin, value, expected):
    plugin.init_plugin(config(enabled=False, brick_retry_limit=value))
    assert plugin._brick_retry_limit == expected

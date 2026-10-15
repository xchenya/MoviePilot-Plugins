"""Server-day scheduling, independent beach cooldown, and legacy compatibility."""
import json
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
    assert plugin._schedule_mode == "interval" and plugin._brick_cooldown_minutes == 1440
    plugin.init_plugin({"schedule_mode": "cron", "cron": "5 0 * * *"})
    assert plugin._cron == "5 0 * * *" and plugin._schedule_mode == "cron"


def test_auto_trigger_checks_locally_once_per_minute(plugin):
    plugin._enabled, plugin._schedule_mode = True, "auto"
    service = plugin.get_service()[0]
    plugin._test_interval.assert_called_once_with(minutes=1)
    assert service["kwargs"] == {"scheduled": True}
    plugin._stats.update(beach_due_at=10**12, brick_due_at=10**12)
    assert service["func"](**service["kwargs"])["status"] == "waiting"
    requests.Session.assert_not_called()
    plugin.update_config.assert_not_called()
    plugin.post_message.assert_not_called()


def test_fixed_time_is_cron_not_auto_poll(plugin):
    plugin._enabled, plugin._schedule_mode = True, "cron"
    plugin._cron = "5 0 * * *"
    service = plugin.get_service()[0]
    plugin._test_cron.from_crontab.assert_called_once_with("5 0 * * *")
    assert service["kwargs"] == {}


@pytest.mark.parametrize("mode", ["auto", "cron"])
def test_server_reset_overrides_old_1440_minute_block_in_new_modes(plugin, monkeypatch, mode):
    plugin._schedule_mode = mode
    plugin._stats["brick_last_run_server"] = 1_999_900
    posts(monkeypatch, response(state()), response(state(50, 50)))
    assert move(plugin)["bricks_moved"] == 50


def test_beach_time_uses_server_relative_delay_not_local_date(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 100)
    plugin._SiQiCleanBeach__read_beach_cooldown(BeautifulSoup(html(), "html.parser"))
    assert plugin._stats["beach_due_at"] == 7105
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
    assert plugin._stats["brick_due_at"] == 51005
    assert plugin._stats["beach_due_at"] == 8005


def test_auto_brick_waits_while_beach_runs(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)
    plugin._schedule_mode = "auto"
    plugin._stats["brick_due_at"] = 8000
    post = posts(monkeypatch, response(dict(success=True)), response(dict(success=True, collected=3)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    result = plugin.run_clean_task(scheduled=True)
    assert result["data"]["trash"] == 3 and plugin._stats["brick_due_at"] == 8000
    assert [c.kwargs["data"]["action"] for c in post.call_args_list] == ["enter_beach", "collect_all_trash"]


def test_manual_run_still_checks_site_even_before_cached_due(plugin, monkeypatch):
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=10**12, brick_due_at=10**12)
    post = posts(monkeypatch, response(dict(success=False, message="冷却中")), response(state(50)))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text=html())))
    assert plugin.run_clean_task()["status"] == "completed"
    assert post.call_count == 2


def test_missing_beach_fields_falls_back_with_honest_source(plugin, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1000)
    plugin._schedule_mode, plugin._auto_brick = "auto", False
    posts(monkeypatch, response(dict(success=False, message="冷却中")))
    monkeypatch.setattr(requests, "get", Mock(return_value=response(text='<div class="inventory-grid"></div>')))
    plugin.run_clean_task(scheduled=True)
    assert plugin._stats["beach_due_at"] == 8260
    assert "回退" in plugin._stats["beach_due_source"]


def test_due_times_survive_every_save_and_reload(plugin):
    plugin._schedule_mode = "auto"
    plugin._stats.update(beach_due_at=10**12, brick_due_at=10**12)
    plugin._update_stats()
    saved = plugin.update_config.call_args.args[0]
    plugin.init_plugin(saved)
    assert plugin.run_clean_task(scheduled=True)["status"] == "waiting"
    form, defaults = plugin.get_form()
    assert defaults["schedule_mode"] == "auto"
    assert "站点冷却" in json.dumps(form, ensure_ascii=False)
    saved["run_once"] = True
    plugin._queue_manual_run = Mock(return_value=True)
    plugin.init_plugin(saved)
    assert plugin.update_config.call_args.args[0]["schedule_mode"] == "auto"
    assert plugin.update_config.call_args.args[0]["stats"]["brick_due_at"] == 10**12


def test_uncertain_write_protection_still_blocks_in_auto(plugin, monkeypatch):
    plugin._schedule_mode = "auto"
    plugin._stats["brick_uncertain_reset"] = "server-day"
    post = posts(monkeypatch, response(state(1)))
    assert not move(plugin)["success"] and post.call_count == 1

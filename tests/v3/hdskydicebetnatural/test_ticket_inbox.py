"""HDSky reward-mailbox regression tests with HTML fixtures and zero network."""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/hdskydicebetnatural/__init__.py"
PARSER = ROOT / "plugins.v3/hdskydicebetnatural/ticket_inbox.py"


def _parser():
    name = "hdsky_inbox_parsing_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, PARSER)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return sys.modules[name]


def _class_method(name):
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    plugin = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "HdskyDiceBetNatural")
    return next(n for n in plugin.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _methods(*names):
    parser = _parser()
    cls = ast.ClassDef(
        name="HdskyTicketUnderTest", bases=[], keywords=[],
        body=[_class_method(name) for name in names], decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = {
        "parse_boxes": parser.parse_boxes,
        "parse_mailbox": parser.parse_mailbox,
        "parse_award_message": parser.parse_award_message,
        "TicketInboxError": parser.TicketInboxError,
        "time": time, "datetime": datetime, "timedelta": timedelta,
        "Dict": Dict, "List": List, "Any": Any, "Optional": Optional, "Tuple": Tuple,
        "logger": SimpleNamespace(info=Mock(), warning=Mock(), error=Mock()),
    }
    exec(compile(module, "<ticket-inbox-methods>", "exec"), namespace)
    return namespace["HdskyTicketUnderTest"]


TODAY = "2026-10-21"


def nav():
    return """<div id="pmboxmenu"><ul>
      <li><a href="/messages.php">收件箱</a></li>
      <li><a href="/messages.php?action=viewmailbox&box=3">抽奖收件箱</a></li>
      <li><a href="/messages.php?action=viewmailbox&box=4">论坛投注</a></li>
    </ul></div>"""


def row(mid, day=TODAY, subject=None):
    subject = subject or f"管理员在您的帖子#{mid}评分"
    return f"""<tr><td class="rowfollow">已读</td>
      <td class="rowfollow"><a href="messages.php?action=viewmessage&amp;id={mid}">{subject}</a></td>
      <td class="rowfollow">系统</td><td class="rowfollow nowrap">{day} 09:45:00</td>
      <td class="rowfollow"><input name="messages[]" value="{mid}"></td></tr>"""


def listing(rows="", next_link=""):
    return f"""<html><body>{nav()}<form action="/messages.php" method="post">
       <table><tr><th>主题</th></tr>{rows}</table></form>{next_link}</body></html>"""


def detail(reason="观影随机续期奖励", day=TODAY):
    return f"""<html><table><tr><td class="rowhead">日期</td>
      <td class="rowfollow">{day} 10:00:00</td></tr>
      <tr><td colspan="2">管理员已为您的帖子评分，评分理由：{reason}</td></tr></table></html>"""


def fixture():
    data = {
        "/messages.php?action=viewmailbox&box=1&page=0": listing(
            row(1001) + row(1002) + row(990, "2026-10-20")
        ),
        "/messages.php?action=viewmailbox&box=3&page=0": listing(
            row(1001) + row(1003)
        ),
        "/messages.php?action=viewmailbox&box=4&page=0": listing(
            row(800, "2026-10-20")
        ),
        "/messages.php?action=viewmessage&id=1001": detail(),
        "/messages.php?action=viewmessage&id=1002": detail("兑奖"),
        "/messages.php?action=viewmessage&id=1003": detail(),
    }
    return data


def host(data):
    cls = _methods("_refresh_today_tickets", "_scan_ticket_mailboxes")
    p = cls()
    p.data = {"tickets_by_day": {TODAY: 0, "2026-10-20": 1}}
    p._today_str = lambda: TODAY
    p._now_str = lambda: TODAY + " 10:30:00"
    p._get = Mock(side_effect=lambda path: data.get(path))
    p._is_cancelled = lambda: False
    p._wait = lambda seconds: False
    p.get_data = lambda key: p.data.get(key)
    p.save_data = lambda key, value: p.data.__setitem__(key, value)
    p.TICKET_SCAN_MAX_PAGES = 10
    p.TICKET_SCAN_MAX_MESSAGES = 100
    p.TICKET_CACHE_SECONDS = 300
    p._max_daily_tickets = None
    p._daily_ticket_limit_reached = lambda: False
    p.TICKET_AWARD_FOLDERS = ("抽奖", "论坛投注", "观影", "奖励", "投注")
    p.LOG_TAG = "[test]"
    return p


def test_daily_award_count_comes_from_inbox_and_archive_not_local_bets():
    p = host(fixture())
    assert p._refresh_today_tickets() is True
    assert p.data["tickets_by_day"][TODAY] == 2
    status = p.data["ticket_inbox_status"]
    assert status["verified"] is True
    assert status["reward_ids"] == ["1001", "1003"]
    assert status["boxes"] == ["收件箱", "抽奖收件箱", "论坛投注"]


def test_repeated_scan_is_cached_and_no_duplicate_awards():
    p = host(fixture())
    assert p._refresh_today_tickets()
    seen_calls = p._get.call_count
    assert p._refresh_today_tickets()
    assert p._get.call_count == seen_calls
    assert p.data["tickets_by_day"][TODAY] == 2


def test_missing_archive_fails_closed_without_overwriting_previous_count():
    pages = fixture()
    pages.pop("/messages.php?action=viewmailbox&box=3&page=0")
    p = host(pages)
    p.data["tickets_by_day"][TODAY] = 2
    p.data["ticket_inbox_status"] = {
        "date": TODAY, "verified": True, "reward_ids": ["1001", "1003"], "checked_ts": 0
    }
    assert p._refresh_today_tickets() is False
    assert p.data["tickets_by_day"][TODAY] == 2
    assert p.data["ticket_inbox_status"]["verified"] is False
    assert p.data["ticket_inbox_status"]["reward_ids"] == ["1001", "1003"]


def test_fresh_rescan_after_failure_uses_confirmed_ids():
    pages = fixture()
    p = host(pages)
    p.data["ticket_inbox_status"] = {
        "date": TODAY, "verified": False, "reward_ids": ["9999"], "checked_ts": 0
    }
    assert p._refresh_today_tickets()
    assert p.data["tickets_by_day"][TODAY] == 3


def test_unparseable_mailbox_or_html_error_never_becomes_zero():
    p = host({"/messages.php?action=viewmailbox&box=1&page=0": "<h1>登录或网页结构改变</h1>"})
    assert p._refresh_today_tickets() is False
    assert p.data["ticket_inbox_status"]["verified"] is False
    assert p.data["tickets_by_day"][TODAY] == 0  # stale legacy value, NOT verified


def test_missing_message_date_fails_closed():
    pages = fixture()
    pages["/messages.php?action=viewmailbox&box=1&page=0"] = listing(row(1010, "未知日期"))
    pages["/messages.php?action=viewmessage&id=1010"] = "<div>观影随机续期奖励</div>"
    p = host(pages)
    assert not p._refresh_today_tickets()
    assert "日期" in p.data["ticket_inbox_status"]["error"]


def test_incomplete_pagination_fails_closed():
    page = listing(row(1001), "<a href='/messages.php?action=viewmailbox&amp;box=1&amp;page=1'>下一页</a>")
    data = fixture()
    data["/messages.php?action=viewmailbox&box=1&page=0"] = page
    p = host(data)
    assert not p._refresh_today_tickets()
    assert p.data["ticket_inbox_status"]["verified"] is False


def test_invalid_reward_text_and_old_messages_not_counted():
    p = host(fixture())
    assert p._refresh_today_tickets()
    assert p.data["tickets_by_day"][TODAY] == 2
    assert p._get.call_args is not None
    assert "/messages.php?action=viewmessage&id=990" not in [
        args[0] for args, _ in p._get.call_args_list
    ]


def test_parser_mailbox_dates_and_archives():
    mod = _parser()
    assert mod.parse_boxes(listing()) == {3: "抽奖收件箱", 4: "论坛投注"}
    res = mod.parse_mailbox(listing(row(12), "<a href='/messages.php?action=viewmailbox&box=1&page=1'>next</a>"),
                            box=1, page=0, today=TODAY)
    assert res.valid and res.has_next and res.entries[0].day == TODAY


def test_detail_requires_explicit_award_reason_not_only_lottery():
    mod = _parser()
    assert mod.parse_award_message(detail(), today=TODAY) == (TODAY, True)
    assert mod.parse_award_message(detail("兑奖"), today=TODAY) == (TODAY, False)
    assert mod.parse_award_message("<p>抽奖成功，但未获得观影随机续期奖励</p>", today=TODAY)[1] is False


def test_run_internal_quota_fails_closed_on_unverified_inbox():
    fn = _class_method("_run_internal")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {}
    exec(compile(module, "<run-internal>", "exec"), namespace)
    fake = SimpleNamespace(
        _is_cancelled=lambda: False, _load_site_auth=lambda: (True, "ok"),
        _ensure_username=lambda: True, _username="test", LOG_TAG="[test]",
        _humanize=False, _sync_pending_results=lambda: None,
        _daily_ticket_limit_reached=lambda: False,
        _ticket_count_ready=lambda: False, _max_daily_tickets=3,
    )
    # logger belongs to the compiled function's globals.
    namespace["logger"] = SimpleNamespace(info=Mock())
    assert "暂停本轮下注" in namespace["_run_internal"](fake)


def test_successful_independent_scan_marks_cap_and_stops_further_scans():
    p = host(fixture())
    p._max_daily_tickets = 2
    p._ticket_check_interval = 60
    p._notify_daily_limit_stop = Mock()
    p._daily_ticket_limit_reached = lambda: (
        (p.data.get("ticket_limit_reached") or {}).get("date") == p._today_str()
    )
    assert p._refresh_today_tickets() is True
    assert p.data["tickets_by_day"][TODAY] == 2
    assert p.data["ticket_limit_reached"] == {
        "date": TODAY, "count": 2, "limit": 2,
    }
    p._notify_daily_limit_stop.assert_called_once_with("tickets", 2, 2)
    count = p._get.call_count
    assert p._refresh_today_tickets() is True
    assert p._get.call_count == count


def test_new_day_clears_effect_of_yesterday_cap_without_extra_network():
    p = host(fixture())
    p._max_daily_tickets = 3
    p.data["ticket_limit_reached"] = {
        "date": "2026-10-20", "count": 3, "limit": 3,
    }
    # The old marker is not today's marker. Today can be checked independently.
    p._daily_ticket_limit_reached = lambda: (
        (p.data.get("ticket_limit_reached") or {}).get("date") == p._today_str()
    )
    assert p._refresh_today_tickets() is True
    assert p.data["tickets_by_day"][TODAY] == 2

"""HDSky reward-mailbox regression tests with HTML fixtures and zero network."""
from __future__ import annotations

import ast
import hashlib
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
    method_names = list(names)
    if any(name in method_names for name in ("_refresh_today_tickets", "_daily_ticket_limit_reached", "_verified_ticket_count")) and "_ticket_source_identity" not in method_names:
        method_names.append("_ticket_source_identity")
    cls = ast.ClassDef(
        name="HdskyTicketUnderTest", bases=[], keywords=[],
        body=[_class_method(name) for name in method_names], decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = {
        "parse_boxes": parser.parse_boxes,
        "parse_mailbox": parser.parse_mailbox,
        "parse_award_message": parser.parse_award_message,
        "parse_helper_reward_count": parser.parse_helper_reward_count,
        "TicketInboxError": parser.TicketInboxError,
        "hashlib": hashlib,
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
    p._helper_cookie = ""
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
        "source": "inbox", "source_identity": "",
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


def test_helper_dashboard_reward_count_parser():
    mod = _parser()
    assert mod.parse_helper_reward_count("<table><tr><td>今日随机奖励3</td></tr></table>") == 3
    assert mod.parse_helper_reward_count("<table><tr><td>今日随机奖励</td><td>2</td></tr></table>") == 2
    assert mod.parse_helper_reward_count("<p>今日随机奖励：0</p>") == 0
    with pytest.raises(mod.TicketInboxError):
        mod.parse_helper_reward_count("<html><title>登录</title><p>请登录</p></html>")
    with pytest.raises(mod.TicketInboxError):
        mod.parse_helper_reward_count("<html><p>Emby 订阅正常</p></html>")


def test_helper_scan_uses_bearer_token_and_reads_api_json_without_logging_it():
    fn = _class_method("_scan_helper_reward_count")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    calls = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"success": True, "data": {"todayRandomRewardCount": 3}}

    class FakeRequestUtils:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def get_res(self, **kwargs):
            calls.append(("get", kwargs))
            return FakeResponse()

    namespace = {
        "RequestUtils": FakeRequestUtils,
        "TicketInboxError": _parser().TicketInboxError,
        "parse_helper_reward_response": _parser().parse_helper_reward_response,
        "logger": SimpleNamespace(warning=Mock()),
        "re": re,
    }
    exec(compile(module, "<helper-scan>", "exec"), namespace)
    token = "eyJhbGciOi-test-access-token"
    fake = SimpleNamespace(
        _helper_cookie=token,
        _proxies=lambda: None, _ua="Test-UA", DEFAULT_UA="Test-UA",
        HELPER_REWARD_URL="https://helper.hdsky.me/api/user/emby",
        LOG_TAG="[test]",
    )
    assert namespace["_scan_helper_reward_count"](fake) == 3
    options = calls[0][1]
    assert "cookies" not in options
    assert options["headers"]["Authorization"] == f"Bearer {token}"
    assert calls[1][1]["url"] == "https://helper.hdsky.me/api/user/emby"
    assert calls[1][1]["allow_redirects"] is False
    assert token not in str(namespace["logger"].warning.call_args_list)


def test_helper_scan_rejects_main_site_cookie_with_specific_diagnostic():
    fn = _class_method("_scan_helper_reward_count")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {
        "RequestUtils": Mock(),
        "TicketInboxError": _parser().TicketInboxError,
        "parse_helper_reward_response": _parser().parse_helper_reward_response,
        "logger": SimpleNamespace(warning=Mock()),
        "re": re,
    }
    exec(compile(module, "<helper-scan>", "exec"), namespace)
    fake = SimpleNamespace(
        _helper_cookie="c_secure_pass=main-site-secret; cf_clearance=clearance",
        _proxies=lambda: None, _ua="UA", DEFAULT_UA="UA",
        HELPER_REWARD_URL="https://helper.hdsky.me/api/user/emby", LOG_TAG="[test]",
    )
    with pytest.raises(_parser().TicketInboxError, match="要求 Bearer accessToken"):
        namespace["_scan_helper_reward_count"](fake)
    namespace["RequestUtils"].assert_not_called()


def test_helper_scan_fails_closed_on_401_redirect_or_bad_status():
    fn = _class_method("_scan_helper_reward_count")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    class FakeResponse:
        status_code = 302
        def json(self):
            return {"success": False}
    class FakeRequestUtils:
        status = 302
        def __init__(self, **kwargs): pass
        def get_res(self, **kwargs):
            response = FakeResponse()
            response.status_code = self.status
            return response
    namespace = {
        "RequestUtils": FakeRequestUtils,
        "TicketInboxError": _parser().TicketInboxError,
        "parse_helper_reward_response": _parser().parse_helper_reward_response,
        "logger": SimpleNamespace(warning=Mock()),
        "re": re,
    }
    exec(compile(module, "<helper-scan>", "exec"), namespace)
    fake = SimpleNamespace(
        _helper_cookie="opaque-access-token", _proxies=lambda: None,
        _ua="UA", DEFAULT_UA="UA", HELPER_REWARD_URL="https://helper.hdsky.me/api/user/emby",
        LOG_TAG="[test]",
    )
    with pytest.raises(_parser().TicketInboxError, match="需要重新登录"):
        namespace["_scan_helper_reward_count"](fake)
    FakeRequestUtils.status = 401
    with pytest.raises(_parser().TicketInboxError, match="HTTP 401"):
        namespace["_scan_helper_reward_count"](fake)
    FakeRequestUtils.status = 500
    with pytest.raises(_parser().TicketInboxError, match="HTTP 500"):
        namespace["_scan_helper_reward_count"](fake)


def test_helper_api_reward_parser_validates_success_and_count():
    mod = _parser()
    assert mod.parse_helper_reward_response({"success": True, "data": {"todayRandomRewardCount": 3}}) == 3
    assert mod.parse_helper_reward_response({"success": True, "data": {"todayRandomRewardCount": 0}}) == 0
    with pytest.raises(mod.TicketInboxError, match="未返回成功状态"):
        mod.parse_helper_reward_response({"success": False, "message": "error"})
    with pytest.raises(mod.TicketInboxError, match="未返回今日随机奖励计数"):
        mod.parse_helper_reward_response({"success": True, "data": {}})
    with pytest.raises(mod.TicketInboxError, match="负数"):
        mod.parse_helper_reward_response({"success": True, "data": {"todayRandomRewardCount": -1}})


def test_helper_cookie_source_takes_precedence_and_does_not_scan_inbox():
    p = host(fixture())
    p._helper_cookie = "session=helper-account"
    p._scan_helper_reward_count = Mock(return_value=1)
    p._scan_ticket_mailboxes = Mock(side_effect=AssertionError("inbox must not be scanned when helper Cookie is configured"))
    assert p._refresh_today_tickets() is True
    assert p.data["tickets_by_day"][TODAY] == 1
    assert p.data["ticket_inbox_status"]["source"] == "helper"
    assert p.data["ticket_inbox_status"]["source_identity"]
    p._scan_helper_reward_count.assert_called_once()
    p._scan_ticket_mailboxes.assert_not_called()


def test_changing_helper_cookie_invalidates_old_verified_count():
    p = host(fixture())
    p._helper_cookie = ""
    p._scan_ticket_mailboxes = Mock(return_value=(2, {"1", "2"}, {"1", "2"}, ["收件箱"]))
    assert p._refresh_today_tickets()
    assert p.data["ticket_inbox_status"]["source"] == "inbox"
    p._helper_cookie = "session=other-account"
    p._scan_helper_reward_count = Mock(return_value=1)
    assert p._refresh_today_tickets()
    assert p.data["tickets_by_day"][TODAY] == 1
    assert p.data["ticket_inbox_status"]["source"] == "helper"


def test_helper_parser_distinguishes_cookie_auth_from_markup_change():
    mod = _parser()
    with pytest.raises(mod.TicketInboxError, match="Cookie 未通过认证或已过期"):
        mod.parse_helper_reward_count(
            "<html><title>HDSky Self Service</title><body><p>请先登录</p></body></html>"
        )
    with pytest.raises(mod.TicketInboxError, match="未识别到已登录的 Emby 订阅页面"):
        mod.parse_helper_reward_count(
            "<html><title>HDSky Self Service</title><body><p>应用载入中</p></body></html>"
        )
    with pytest.raises(mod.TicketInboxError, match="页面结构变化"):
        mod.parse_helper_reward_count(
            "<html><title>HDSky Self Service</title><body><p>主站用户 UID 123</p><p>Emby 订阅</p><p>奖励数据暂不可用</p></body></html>"
        )


def test_helper_parser_reads_counter_when_dashboard_layout_changes():
    mod = _parser()
    page = """<html><title>HDSky Self Service</title><body>
      <section><span>主站用户</span><span>UID 109798</span></section>
      <section><h2>Emby 订阅</h2><div class="stat"><span>今日随机奖励</span><strong>3</strong></div></section>
    </body></html>"""
    assert mod.parse_helper_reward_count(page) == 3

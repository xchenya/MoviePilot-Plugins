"""HDSky reward-mailbox regression tests with HTML fixtures and zero network."""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
import re
import sys
import threading
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



def _auth_module():
    name = "dice_helper_auth_contract"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "plugins.v3/hdskydicebetnatural/helper_auth.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


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


def _methods(*names, extra=None):
    parser = _parser()
    method_names = list(names)
    if any(name in method_names for name in ("_refresh_today_tickets", "_daily_ticket_limit_reached", "_verified_ticket_count", "_scan_helper_reward_count")):
        for dep in ("_ticket_source_identity", "_helper_user_id", "_helper_jwt_payload"):
            if dep not in method_names:
                method_names.append(dep)
    if "_scan_helper_reward_count" in method_names:
        for dep in ("_helper_token_expiring", "_refresh_helper_access_token", "_helper_reward_api_get", "_persist_helper_tokens"):
            if dep not in method_names:
                method_names.append(dep)
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
        "parse_helper_reward_response": parser.parse_helper_reward_response,
        "TicketInboxError": parser.TicketInboxError,
        "HelperLoginError": _auth_module().HelperLoginError,
        "hashlib": hashlib, "base64": base64, "json": json, "re": re,
        "time": time, "datetime": datetime, "timedelta": timedelta,
        "Dict": Dict, "List": List, "Any": Any, "Optional": Optional, "Tuple": Tuple,
        "logger": SimpleNamespace(info=Mock(), warning=Mock(), error=Mock()),
    }
    namespace.update(extra or {})
    exec(compile(module, "<ticket-inbox-methods>", "exec"), namespace)
    result = namespace["HdskyTicketUnderTest"]
    def initialize(self):
        self.data = {}
        self._config = {}
        self.get_data = lambda key: self.data.get(key)
        self.save_data = lambda key, value: self.data.__setitem__(key, value)
        self._helper_auth = _auth_module().HelperLogin(self)
    result.__init__ = initialize
    return result


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
        _continue_on_ticket_failure=False,
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


def _jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "header." + body + ".signature"


def test_helper_scan_uses_bearer_access_token_when_fresh():
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"success": True, "data": {"todayRandomRewardCount": 3}}
    class FakeRequestUtils:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def get_res(self, **kwargs):
            calls.append(("get", kwargs))
            return Response()
    cls = _methods(
        "_scan_helper_reward_count", "_helper_token_expiring", "_helper_reward_api_get",
        extra={"RequestUtils": FakeRequestUtils},
    )
    p = cls()
    p._helper_cookie = "opaque-fresh-access-token"
    p._helper_refresh_token = "opaque-refresh-token"
    p._proxies = lambda: None
    p._ua = "Test-UA"
    p.DEFAULT_UA = "Test-UA"
    p.HELPER_REWARD_URL = "https://helper.hdsky.me/api/user/emby"
    p.LOG_TAG = "[test]"
    assert p._scan_helper_reward_count() == 3
    assert calls[0][1]["headers"]["Authorization"] == "Bearer opaque-fresh-access-token"
    assert calls[1][1]["url"] == p.HELPER_REWARD_URL
    assert calls[1][1]["allow_redirects"] is False


def test_expired_access_token_refreshes_and_persists_rotated_tokens():
    old_access = _jwt({"userId": 109798, "exp": 1})
    new_access = _jwt({"userId": 109798, "exp": int(time.time()) + 900})
    calls = []
    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload
        def json(self):
            return self._payload
    class FakeRequestUtils:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def post_res(self, **kwargs):
            calls.append(("post", kwargs))
            return Response(200, {"success": True, "data": {
                "accessToken": new_access, "refreshToken": "rotated-refresh-token",
            }})
        def get_res(self, **kwargs):
            calls.append(("get", kwargs))
            return Response(200, {"success": True, "data": {"todayRandomRewardCount": 3}})
    cls = _methods(
        "_scan_helper_reward_count", "_helper_jwt_payload", "_helper_user_id",
        "_helper_token_expiring", "_refresh_helper_access_token", "_helper_reward_api_get",
        "_persist_helper_tokens",
        extra={"RequestUtils": FakeRequestUtils},
    )
    p = cls()
    p._helper_cookie = old_access
    p._helper_refresh_token = "original-refresh-token"
    p._config = {"enabled": True, "helper_cookie": old_access,
                 "helper_refresh_token": "original-refresh-token", "site_id": 49}
    p.config_saves = []
    p.update_config = lambda value: (p.config_saves.append(dict(value)) or True)
    p._proxies = lambda: None
    p._ua = "Test-UA"
    p.DEFAULT_UA = "Test-UA"
    p.HELPER_REWARD_URL = "https://helper.hdsky.me/api/user/emby"
    p.HELPER_REFRESH_URL = "https://helper.hdsky.me/api/user/refresh"
    p.LOG_TAG = "[test]"
    assert p._scan_helper_reward_count() == 3
    post = next(args for kind, args in calls if kind == "post")
    assert post["url"] == p.HELPER_REFRESH_URL
    assert post["json"] == {"refreshToken": "original-refresh-token"}
    get_init = next(args for kind, args in reversed(calls) if kind == "init")
    assert get_init["headers"]["Authorization"] == f"Bearer {new_access}"
    get = next(args for kind, args in calls if kind == "get")
    assert p._helper_cookie == new_access
    assert p._helper_refresh_token == "rotated-refresh-token"
    assert p.data["helper_credentials"]["access_token"] == new_access
    assert p.data["helper_credentials"]["refresh_token"] == "rotated-refresh-token"
    assert not p._config["helper_cookie"]
    assert not p._config["helper_refresh_token"]
    assert not p.config_saves
    # The account identity remains stable when the access token rotates.
    assert p._ticket_source_identity()[1] == __import__("hashlib").sha256(b"user:109798").hexdigest()[:16]


def test_expired_access_token_without_refresh_token_fails_actionably():
    cls = _methods("_scan_helper_reward_count", "_helper_jwt_payload", "_helper_token_expiring")
    p = cls()
    p._helper_cookie = _jwt({"userId": 109798, "exp": 1})
    p._helper_refresh_token = ""
    with pytest.raises(_parser().TicketInboxError, match="请补填 Emby 订阅 Refresh Token"):
        p._scan_helper_reward_count()


def test_refresh_token_failure_does_not_log_token_values():
    calls = []
    class Response:
        status_code = 401
        def json(self):
            return {"success": False, "message": "expired"}
    class FakeRequestUtils:
        def __init__(self, **kwargs): pass
        def post_res(self, **kwargs):
            calls.append(kwargs)
            return Response()
    cls = _methods("_refresh_helper_access_token", extra={"RequestUtils": FakeRequestUtils})
    p = cls()
    p._helper_refresh_token = "refresh-secret-value"
    p._proxies = lambda: None
    p._ua = "UA"
    p.DEFAULT_UA = "UA"
    p.HELPER_REFRESH_URL = "https://helper.hdsky.me/api/user/refresh"
    p.LOG_TAG = "[test]"
    with pytest.raises(_parser().TicketInboxError, match="Refresh Token 已失效") as exc:
        p._refresh_helper_access_token()
    assert "refresh-secret-value" not in str(exc.value)
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


def test_nested_layout_rows_do_not_hide_first_messages_reception_date():
    # Same five-cell mailbox inside NexusPHP's outer layout tables.
    html = '<table><tr><td><table><tr><td>' + listing(row(1001) + row(1002)) + '</td></tr></table></td></tr></table>'
    parsed = _parser().parse_mailbox(html, box=1, page=0, today=TODAY)
    assert [(entry.mid, entry.day) for entry in parsed.entries] == [("1001", TODAY), ("1002", TODAY)]


def test_absolute_date_tooltip_wins_over_relative_label():
    html = listing(row(1001, '<span title="2026-10-20 23:59:00">刚刚</span>'))
    parsed = _parser().parse_mailbox(html, box=1, page=0, today=TODAY)
    assert parsed.entries[0].day == "2026-10-20"


def test_date_is_not_taken_from_subject_or_site_footer():
    html = listing(row(1001, '未知日期')).replace('评分通知', TODAY) + '<footer>' + TODAY + '</footer>'
    parsed = _parser().parse_mailbox(html, box=1, page=0, today=TODAY)
    assert parsed.entries[0].day is None

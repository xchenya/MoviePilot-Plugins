"""Offline contract and failure-injection tests. No live site writes are allowed."""
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests


def html(uid="7", balance=1000000, remaining=1000, **overrides):
    """Synthetic fixture based on the inspected inline state and login header."""
    state = {"enabledDraw": True, "enabledPool": True, "costPerDraw": 20000,
             "maxDrawCount": 100, "dailyDrawRemaining": remaining, "items": []}
    state.update(overrides)
    buttons = "".join(f'<button class="omnibot-draw-trigger" data-draw-count="{n}">{n}抽</button>'
                      for n in (1, 10, 20, 50, 100))
    return (f'<table id="info_block"><tr><td><a href="userdetails.php?id={uid}">测试用户</a>'
            f'<a href="logout.php">退出</a><a href="mybonus.php">使用</a>: {balance:,.1f}'
            '</td></tr></table><script>window.qqbotLotteryState = '
            + json.dumps(state) + ';</script>' + buttons)


class FakeSession:
    """A stateful, in-memory site simulator; receipts follow frontend field names."""

    def __init__(self, balance=1000000, remaining=1000, uid="7", reward=0):
        self.balance, self.remaining, self.uid, self.reward = balance, remaining, uid, reward
        self.posts, self.gets, self.before = [], [], []
        self.status, self.failure, self.transform, self.after_post = 200, None, None, None
        self.closed = False
        self.page_overrides = {}

    def get(self, url, **kwargs):
        """Generate a fresh page without touching the network."""
        self.gets.append((url, kwargs))
        text = html(self.uid, self.balance, self.remaining, **self.page_overrides)
        return SimpleNamespace(status_code=200, content=text.encode(), text=text)

    def post(self, url, **kwargs):
        """Settle a simulated draw, optionally losing its response afterwards."""
        count = int(kwargs["data"]["count"])
        self.posts.append((url, kwargs))
        self.before.append(self.balance)
        if count > self.remaining or count * 20000 > self.balance:
            raise AssertionError("plugin exceeded site quota or balance")
        self.remaining -= count
        self.balance += count * (self.reward - 20000)
        data = {"ok": True, "draw_count": count, "total_cost": count * 20000, "total_compensated_bonus": 0,
                "user_bonus_after": self.balance, "summary_text": "测试结果",
                "results": [{"prize_name": "魔力", "content": f"{self.reward} 魔力值", "is_compensated": False,
                             "comp_bonus": 0} for _ in range(count)]}
        if self.after_post:
            self.after_post()
        if self.failure:
            raise self.failure
        if self.transform:
            data = self.transform(data)
        return SimpleNamespace(status_code=self.status, content=b"{}", json=lambda: data)

    def close(self):
        """Record session cleanup."""
        self.closed = True


def connect(plugin, session, monkeypatch):
    """Replace only transport creation, preserving production request logic."""
    monkeypatch.setattr(plugin, "_session", lambda config: session)
    plugin._cancel.wait = Mock(return_value=False)
    return session


def saved(module, plugin):
    """Read and validate the real persisted ledger."""
    return module.storage.load(plugin._path())


def test_observed_page_contract(module):
    snap = module.parse_page(html(remaining=999))
    assert (snap.uid, snap.balance, snap.cost, snap.remaining) == ("7", 1000000, 20000, 999)
    assert snap.ready and snap.batches == (100, 50, 20, 10, 1)


@pytest.mark.parametrize("changes", [{"enabledDraw": "true"}, {"costPerDraw": 0},
                                    {"maxDrawCount": -1}, {"dailyDrawRemaining": 0.5}])
def test_unknown_or_invalid_state_stops(module, changes):
    with pytest.raises(module.LotteryError):
        module.parse_page(html(**changes))


def test_login_balance_and_current_user_are_required(module):
    for page in (html().replace("logout.php", "login.php"), html().replace("mybonus.php", "other.php"),
                 html().replace("userdetails.php?id=7", "https://evil.invalid/userdetails.php?id=7")):
        with pytest.raises(module.LotteryError):
            module.parse_page(page)
    page = '<a href="userdetails.php?id=999">其他用户</a>' + html()
    assert module.parse_page(page).uid == "7"


def test_credentials_fixed_host_and_session_settings(module, plugin):
    session = plugin._session({"use_proxy": False})
    assert session.trust_env is False
    assert session.cookies.get("session", domain="www.tangpt.top") == "fixture-secret"
    assert "Cookie" not in session.headers
    assert "X-Requested-With" not in session.headers and "Origin" not in session.headers
    assert session.headers["User-Agent"] == "fixture-UA"
    assert session.get_adapter(module.DRAW_URL).max_retries.total == 0
    session.close()
    module.site_fixture.url = "https://tangpt.top.evil.invalid"
    with pytest.raises(module.LotteryError):
        plugin._session({"use_proxy": False})


def test_scheduled_batches_tail_and_daily_idempotence(module, plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "daily_target": 12, "interval": 5})
    site = connect(plugin, FakeSession(), monkeypatch)
    plugin.run()
    assert [int(p[1]["data"]["count"]) for p in site.posts] == [10, 1, 1]
    assert all(url == module.DRAW_URL and args["allow_redirects"] is False for url, args in site.posts)
    assert site.closed
    plugin.run()
    state = saved(module, plugin)
    daily = state["days"]["7:" + plugin._day()]
    assert len(site.posts) == 3 and daily["draws"] == daily["attempted"] == 12
    assert daily["spent"] == 240000 and sum(daily["prizes"].values()) == 12
    assert state["pending"] is None
    assert "fixture-secret" not in plugin._path().read_text()


@pytest.mark.parametrize("balance,remaining,expected", [(150000, 1000, 2), (1000000, 11, 11),
                                                        (100000, 1000, 0), (1000000, 0, 0)])
def test_balance_reserve_and_remaining(module, plugin, monkeypatch, balance, remaining, expected):
    site = connect(plugin, FakeSession(balance=balance, remaining=remaining), monkeypatch)
    plugin.run()
    assert sum(int(p[1]["data"]["count"]) for p in site.posts) == expected
    assert all(before - int(p[1]["data"]["count"]) * 20000 >= 100000 for before, p in zip(site.before, site.posts))


@pytest.mark.parametrize("overrides", [{"enabledDraw": False}, {"enabledPool": False}, {"costPerDraw": 20001}])
def test_closed_activity_or_price_increase_does_not_draw(plugin, monkeypatch, overrides):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.page_overrides = overrides
    plugin.run()
    assert not site.posts


def test_timeout_freezes_restarts_and_no_later_network(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.failure = requests.ReadTimeout("do not log sensitive URL")
    plugin.run()
    assert len(site.posts) == 1
    state = saved(module, plugin)
    assert state["pending"]["count"] == 10
    assert state["days"]["7:" + plugin._day()]["attempted"] == 10
    assert state["days"]["7:" + plugin._day()]["draws"] == 0
    assert "do not log" not in json.dumps(state)
    restarted = module.TangptLottery()
    restarted.init_plugin({"enabled": True})
    connect(restarted, site, monkeypatch)
    restarted.run()
    assert len(site.posts) == len(site.gets) == 1
    assert restarted.notifications[-1]["text"].endswith("不会自动重发。")


@pytest.mark.parametrize("status", [302, 401, 403, 419, 422, 429, 500, 524])
def test_http_failures_never_retry(module, plugin, monkeypatch, status):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.status = status
    plugin.run()
    plugin.run()
    assert len(site.posts) == 1 and saved(module, plugin)["pending"]


@pytest.mark.parametrize("transform", [lambda d: {"message": "failed"}, lambda d: {**d, "draw_count": 9},
                                        lambda d: {**d, "total_cost": 1}, lambda d: {**d, "user_bonus_after": float("nan")}])
def test_malformed_receipt_preserves_pending(module, plugin, monkeypatch, transform):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.transform = transform
    plugin.run()
    assert saved(module, plugin)["pending"] and len(site.posts) == 1


def test_missing_prizes_do_not_lose_confirmed_settlement(module, plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "daily_target": 10})
    site = connect(plugin, FakeSession(reward=5000), monkeypatch)
    site.transform = lambda data: {**data, "results": []}
    plugin.run()
    daily = saved(module, plugin)["days"]["7:" + plugin._day()]
    assert daily["draws"] == 10 and daily["change"] == -150000
    assert daily["prizes"] == {"奖品明细缺失，请核对站点": 10}


def test_persistence_before_post_and_failed_settlement(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    real_save = module.storage.save

    def fail_intent(path, state):
        if state["pending"]:
            raise module.LotteryError("disk failure")
        real_save(path, state)

    monkeypatch.setattr(module.storage, "save", fail_intent)
    plugin.run()
    assert not site.posts

    def fail_receipt(path, state):
        if state["pending"] is None and any(day["draws"] for day in state["days"].values()):
            raise module.LotteryError("disk failure")
        real_save(path, state)

    monkeypatch.setattr(module.storage, "save", fail_receipt)
    plugin.run()
    assert len(site.posts) == 1 and saved(module, plugin)["pending"]
    plugin.run()
    assert len(site.posts) == 1


def test_corrupt_state_is_not_silently_reset(module, plugin, monkeypatch):
    plugin._path().write_text('{"version": 1, "pending": null, "days": {"7:2026-10-20": {}}, "history": []}')
    site = connect(plugin, FakeSession(), monkeypatch)
    plugin.run()
    assert not site.posts and not site.gets
    assert "恢复备份" in plugin.notifications[-1]["text"]


def test_one_shots_reset_and_diagnostic_has_priority(module, monkeypatch):
    plugin = module.TangptLottery()
    plugin.init_plugin({"diagnose_only": True, "run_once": True})
    assert not plugin.saved_config["diagnose_only"] and not plugin.saved_config["run_once"]
    jobs = plugin.get_service()
    assert len(jobs) == 1 and jobs[0]["id"].endswith(".Once")
    site = connect(plugin, FakeSession(), monkeypatch)
    jobs[0]["func"]()
    jobs[0]["func"]()
    assert len(site.gets) == 1 and not site.posts
    assert not plugin.get_state()


def test_cron_is_shanghai_and_bad_config_or_failed_reset_stops(module, monkeypatch):
    plugin = module.TangptLottery()
    plugin.init_plugin({"enabled": True})
    assert str(plugin.get_service()[0]["trigger"].timezone) == "Asia/Shanghai"
    plugin.init_plugin({"enabled": True, "cron": "invalid"})
    assert not plugin.get_service() and not plugin.get_state()
    monkeypatch.setattr(plugin, "update_config", lambda _: False)
    plugin.init_plugin({"run_once": True})
    assert not plugin.get_service()


def test_ack_only_preserves_quota_and_requires_original_account(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.failure = requests.ReadTimeout()
    plugin.run()
    site.failure = None
    site.uid = "8"
    plugin.init_plugin({"acknowledge_pending": True, "run_once": True})
    plugin.run(once=True)
    assert saved(module, plugin)["pending"]
    site.uid = "7"
    plugin.init_plugin({"acknowledge_pending": True, "run_once": True})
    plugin.run(once=True)
    state = saved(module, plugin)
    assert state["pending"] is None and len(site.posts) == 1
    assert state["days"]["7:" + plugin._day()]["attempted"] == 10
    plugin.init_plugin({"enabled": True, "daily_target": 10})
    plugin.run()
    assert len(site.posts) == 1


def test_stop_or_reload_records_inflight_success_without_another_post(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    generation = plugin._generation
    site.after_post = lambda: plugin.init_plugin({"enabled": True, "daily_target": 20})
    plugin.run()
    assert len(site.posts) == 1 and saved(module, plugin)["days"]["7:" + plugin._day()]["draws"] == 10
    plugin.run(generation=generation)
    plugin.stop_service()
    plugin.run()
    assert len(site.posts) == 1 and not plugin.get_service()


def test_account_switch_or_midnight_stops_remaining_batches(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.after_post = lambda: setattr(site, "uid", "8")
    plugin.run()
    assert len(site.posts) == 1
    plugin.init_plugin({"enabled": True, "daily_target": 30})
    site.uid = "7"
    next_day = (datetime.now(module.LOCAL_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    site.after_post = lambda: monkeypatch.setattr(plugin, "_day", lambda: next_day)
    plugin._cancel.wait = Mock(return_value=False)
    plugin.run()
    assert len(site.posts) == 2


def test_file_lock_prevents_hot_reload_overlap(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    with module.storage.exclusive(plugin._path().with_suffix(".lock")) as acquired:
        assert acquired
        plugin.run()
    assert not site.posts and not site.gets


def test_notification_failure_and_detail_page_never_draw(module, plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "daily_target": 10})
    site = connect(plugin, FakeSession(), monkeypatch)
    monkeypatch.setattr(plugin, "post_message", Mock(side_effect=RuntimeError("notification down")))
    plugin.run()
    plugin.run()
    before = (len(site.gets), len(site.posts))
    assert plugin.get_page()
    assert (len(site.gets), len(site.posts)) == before and len(site.posts) == 1


def test_ui_is_daily_account_scoped_and_escapes_prizes(module):
    from app.plugins.tangptlottery.ui import page
    one = {**module.storage.empty_day(), "attempted": 1, "draws": 1, "prizes": {"<img src=x onerror=alert(1)>": 1}}
    state = {"active_uid": "7", "days": {"7:2026-10-20": one, "8:2026-10-20": {**one, "spent": 999999}},
             "snapshot": {"uid": "7", "day": "2026-10-19", "remaining": 321}, "history": []}
    rendered = json.dumps(page(state, "2026-10-20"), ensure_ascii=False)
    assert "&lt;img" in rendered and "<img" not in rendered
    assert "999,999" not in rendered and "约 321" not in rendered
    assert "今日目标已占用 1 次" in rendered


@pytest.mark.parametrize("balance_markup", [
    '<span><a href="mybonus.php">使用</a></span>：<b>1,000,000.0</b>',
    '<a href="mybonus.php">使用：<span>1,000,000.0</span></a>',
    '<font>魔力值</font> [<a href="mybonus.php">使用</a>: <span>1,000,000.0</span>]',
    '<a href="mybonus.php">使用</a><span>：<b>1,000,000.0</b></span>',
    '<div>当前魔力：<strong>1,000,000.0</strong></div>',
])
def test_balance_theme_variants_are_not_cookie_failures(module, balance_markup):
    page = html().replace('<a href="mybonus.php">使用</a>: 1,000,000.0', balance_markup)
    snap = module.parse_page(page)
    assert snap.uid == "7" and snap.balance == 1000000


def test_alternative_header_and_logout_order_keep_account_identity(module):
    page = html().replace('<table id="info_block">', '<table class="theme-header">')
    page = '<a href="userdetails.php?id=999">排行榜用户</a>' + page
    assert module.parse_page(page).uid == "7"
    original = '<a href="userdetails.php?id=7">测试用户</a><a href="logout.php">退出</a>'
    swapped = '<a href="logout.php">退出</a><a href="userdetails.php?id=7">测试用户</a>'
    assert module.parse_page(page.replace(original, swapped)).uid == "7"


def test_missing_balance_reports_parser_error_without_asking_to_refresh_cookie(module):
    page = html().replace('<a href="mybonus.php">使用</a>: 1,000,000.0', '')
    with pytest.raises(module.LotteryError, match="已识别登录账号，但未读到魔力余额") as error:
        module.parse_page(page)
    assert "更新" not in str(error.value)


@pytest.mark.parametrize("quota,remaining", [
    ("今天还可以抽 987 次", 987),
    ("今日还可以抽 0 次", 0),
    ("剩余抽奖次数：12", 12),
    ("今天最多可抽奖 1,000 次，当前已抽 21 次", 979),
])
def test_text_fallback_reads_actual_quota_not_reference_hardcoded_limit(module, quota, remaining):
    page = re.sub(r"<script>.*?</script>", "", html()) + f'<p>单次消耗：<b>20,000</b> 魔力</p><p>{quota}</p>'
    snap = module.parse_page(page)
    assert (snap.cost, snap.remaining, snap.source) == (20000, remaining, "页面文字")
    assert snap.ready and snap.batches == (100, 50, 20, 10, 1)
    assert not module.parse_page(page.replace('<button ', '<button disabled ')).ready
    with pytest.raises(module.LotteryError, match="未读到站点剩余"):
        module.parse_page(page.replace(quota, ""))


@pytest.mark.parametrize("page,expected", [
    ('<form action="takelogin.php"><input type="password"></form>', "明确返回登录提示"),
    ('<h1>请先登录</h1>', "明确返回登录提示"),
    ('<title>Just a moment...</title><form id="challenge-form"></form>', "浏览器验证"),
    ('<h1>Service unavailable</h1>', "页面解析失败"),
])
def test_login_challenge_and_unknown_pages_are_distinct(module, page, expected):
    with pytest.raises(module.LotteryError, match=expected):
        module.parse_page(page)
    # Frontend error messages embedded in scripts are not evidence of failed login.
    assert module.parse_page(html() + '<script>var error = "Cookie失效，请先登录";</script>').uid == "7"


def test_canonical_site_cookie_wins_and_empty_record_falls_back(module, plugin, monkeypatch):
    canonical = SimpleNamespace(url="https://www.tangpt.top", cookie="c_secure_pass=www-secret", ua="canonical-UA")
    alias = SimpleNamespace(url="https://tangpt.top", cookie="c_secure_pass=alias-secret", ua="alias-UA")
    calls = []

    def get_site(domain):
        calls.append(domain)
        return canonical if domain == "www.tangpt.top" else alias

    monkeypatch.setattr(module, "SiteOper", lambda: SimpleNamespace(get_by_domain=get_site))
    with plugin._session({"use_proxy": False}) as session:
        assert session.cookies.get("c_secure_pass", domain="www.tangpt.top") == "www-secret"
        assert session.headers["User-Agent"] == "canonical-UA"
        assert calls == ["www.tangpt.top"]
    canonical.cookie = "  "
    with plugin._session({"use_proxy": True}) as session:
        assert session.cookies.get("c_secure_pass", domain="www.tangpt.top") == "alias-secret"
        assert session.proxies["https"] == "http://proxy.invalid:8080"
        assert "tangpt.top" in session.credential_source


def test_manual_credentials_work_without_site_and_do_not_leak(module, plugin, monkeypatch, caplog):
    monkeypatch.setattr(module, "SiteOper", lambda: SimpleNamespace(get_by_domain=lambda _: None))
    config = {"use_proxy": False, "cookie": "Cookie: c_secure_uid=abc==; c_secure_pass= manual-secret ;", "user_agent": "manual-UA"}
    with caplog.at_level("INFO"), plugin._session(config) as session:
        assert session.cookies.get("c_secure_uid", domain="www.tangpt.top") == "abc=="
        assert session.cookies.get("c_secure_pass", domain="www.tangpt.top") == "manual-secret"
        assert session.headers["User-Agent"] == "manual-UA"
        assert session.credential_source == "手动 Cookie"
        prepared = session.prepare_request(requests.Request("GET", "https://other.invalid/"))
        assert "Cookie" not in prepared.headers
    assert "manual-secret" not in caplog.text and "abc==" not in caplog.text
    config["user_agent"] = ""
    with plugin._session(config) as session:
        assert "Chrome/" in session.headers["User-Agent"] and session.verify is True
    config["cookie"] = "not a cookie"
    with pytest.raises(module.LotteryError, match="未配置可用 Cookie"):
        plugin._session(config)


def test_manual_cookie_has_priority_over_site_cookie(module, plugin):
    config = {"use_proxy": False, "cookie": "c_secure_pass=manual-secret"}
    with plugin._session(config) as session:
        assert session.cookies.get("c_secure_pass", domain="www.tangpt.top") == "manual-secret"
        assert session.cookies.get("session", domain="www.tangpt.top") is None
        assert session.headers["User-Agent"] == "fixture-UA"


def test_page_and_draw_use_separate_browser_headers(plugin, monkeypatch):
    plugin.init_plugin({"enabled": True, "daily_target": 10})
    site = connect(plugin, FakeSession(), monkeypatch)
    plugin.run()
    get_headers, post_headers = site.gets[0][1]["headers"], site.posts[0][1]["headers"]
    assert "X-Requested-With" not in get_headers and "Origin" not in get_headers
    assert get_headers["Sec-Fetch-Mode"] == "navigate" and get_headers["Referer"] == "https://www.tangpt.top/"
    assert post_headers["X-Requested-With"] == "XMLHttpRequest"
    assert post_headers["Sec-Fetch-Mode"] == "cors"
    assert post_headers["Content-Type"] == "application/x-www-form-urlencoded; charset=UTF-8"


@pytest.mark.parametrize("status,location,message", [
    (401, "", "401 登录认证失败"),
    (403, "", "403 访问被拒"),
    (302, "/login.php?returnto=omnibot_lottery.php", "跳转到登录页"),
    (302, "https://other.invalid/secret-token", "重定向"),
    (502, "", "请核对网络"),
])
def test_read_failures_are_diagnostic_and_never_draw(module, plugin, monkeypatch, status, location, message):
    plugin.init_plugin({"diagnose_only": True})
    site = connect(plugin, FakeSession(), monkeypatch)
    site.get = Mock(return_value=SimpleNamespace(status_code=status, content=b"", headers={"Location": location}))
    plugin.run(once=True)
    state = saved(module, plugin)
    assert message in state["last"]["message"] and not site.posts
    assert "secret-token" not in json.dumps(state)


def test_tls_failure_is_not_cookie_expiry(module, plugin, monkeypatch):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.get = Mock(side_effect=requests.exceptions.SSLError("sensitive network details"))
    plugin.run()
    assert "TLS 证书" in saved(module, plugin)["last"]["message"]
    assert "sensitive network details" not in plugin._path().read_text() and not site.posts


@pytest.mark.parametrize("ok", [False, None, "true", 1])
def test_non_success_json_never_commits_success_even_with_settlement_fields(module, plugin, monkeypatch, ok):
    site = connect(plugin, FakeSession(), monkeypatch)
    site.transform = lambda data: {**data, "ok": ok, "message": "private upstream message"}
    plugin.run()
    state = saved(module, plugin)
    assert state["pending"] and state["days"]["7:" + plugin._day()]["draws"] == 0
    assert "private upstream message" not in json.dumps(state)

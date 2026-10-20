"""Offline contract and failure-injection tests. No live site writes are allowed."""
import json
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
        data = {"draw_count": count, "total_cost": count * 20000, "total_compensated_bonus": 0,
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
    assert session.headers["Referer"] == module.PAGE_URL
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

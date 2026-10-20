"""Failure-injection and quota tests using the observed site contract."""
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
import requests


def html(remaining=500, balance=1000000, uid="123", ready=True):
    """Synthetic page: constants match frontend fields, no real credentials."""
    return f'''<html><span id="lw-balance">{balance:,}</span><script>
var CSRF = "0123456789abcdef0123456789abcdef";
var STORAGE_KEY = 'luckywheel-pending-{uid}';
var COST = 1000; var GAME_READY = {str(ready).lower()};
var MULTI_COUNTS = [3,10];
var DAILY = {{"limit":500,"remaining":{remaining}}};
</script></html>'''


def response(payload=None, status=200, text="", headers=None):
    """A minimal requests response with optional invalid JSON."""
    obj = SimpleNamespace(status_code=status, text=text, content=text.encode(), headers=headers or {})
    obj.json = Mock(side_effect=payload if isinstance(payload, Exception) else None, return_value=payload)
    return obj


class Wheel:
    """Fake server keeps idempotency receipts and actual purchase count."""

    def __init__(self, remaining=500, balance=1000000):
        self.remaining, self.balance = remaining, balance
        self.calls, self.purchases, self.receipts = [], [], {}
        self.uid, self.ready = "123", True
        self.fail_after_purchase = False
        self.get = Mock(side_effect=self.fetch)
        self.post = Mock(side_effect=self.spin)
        self.close = Mock()

    def fetch(self, *args, **kwargs):
        return response(text=html(self.remaining, self.balance, self.uid, self.ready))

    def spin(self, url, data, **kwargs):
        self.calls.append(copy.deepcopy(data))
        key = data["request_key"]
        if key not in self.receipts:
            count = int(data.get("count", 1))
            assert self.remaining >= count
            self.remaining -= count
            self.balance -= count * 1000
            payload = {"ret": 0, "data": {"count": count, "bonus": f"{self.balance:,}",
                        "daily": {"limit": 500, "remaining": self.remaining},
                        "labels": ["工分500", "谢谢参与"], "indices": [0] * count,
                        "items": [{"label": "工分500", "count": count}]}}
            if count == 1:
                payload["data"]["index"] = 0
            self.receipts[key] = payload
            self.purchases.append(count)
            if self.fail_after_purchase:
                self.fail_after_purchase = False
                raise requests.Timeout("sensitive transport text")
        return response(copy.deepcopy(self.receipts[key]))


def connect(plugin, wheel=None):
    wheel = wheel or Wheel()
    plugin._session = Mock(return_value=wheel)
    return wheel


def saved(plugin, module):
    return module.storage.load(plugin._path())


def test_parse_current_contract(module):
    p = module.parse_page(html(0, 21740991.4))
    assert p.balance == 21740991.4 and p.remaining == 0 and p.batches == [10, 3, 1]
    assert p.uid == "123" and p.cost == 1000


@pytest.mark.parametrize("text", ["<form action='takelogin.php'></form>", html().replace('var DAILY', 'var NOPE'),
                                  html().replace('"remaining":500', '"remaining":501'),
                                  html().replace("var COST = 1000", "var COST = 0")])
def test_invalid_pages_fail_closed(module, text):
    with pytest.raises(module.WheelError):
        module.parse_page(text)


def test_normal_target_and_idempotent_repeated_cron(plugin, module):
    wheel = connect(plugin)
    plugin.run()
    plugin.run()
    assert wheel.purchases == [10, 10]
    assert sum(wheel.purchases) == 20
    s = saved(plugin, module)
    assert s["pending"] is None and s["history"][0]["draws"] == 20
    assert s["history"][1]["draws"] == 0
    assert len(plugin.notifications) == 2
    assert "工分500 ×20" in plugin.notifications[0]["text"]
    assert "fixture-secret" not in json.dumps(s) + json.dumps(plugin.notifications)


def test_manual_draws_and_tail_batches(plugin, module):
    wheel = connect(plugin, Wheel(remaining=493))
    plugin.init_plugin({"enabled": True, "daily_target": 25, "interval": 3})
    plugin._cancel.wait = Mock(return_value=False)
    plugin.run()
    assert wheel.purchases == [10, 3, 3, 1, 1]
    assert 500 - wheel.remaining == 25


def test_reserve_and_small_affordable_batch(plugin, module):
    wheel = connect(plugin, Wheel(balance=12000))
    plugin.run()
    assert wheel.purchases == [1, 1] and wheel.balance == 10000
    assert saved(plugin, module)["last"]["status"] == "已停止"


@pytest.mark.parametrize("remaining,ready", [(0, True), (500, False)])
def test_site_limit_and_activity_disabled(plugin, module, remaining, ready):
    wheel = connect(plugin, Wheel(remaining=remaining))
    wheel.ready = ready
    plugin.run()
    assert not wheel.calls


def test_timeout_after_commit_retries_same_order(plugin, module):
    wheel = connect(plugin)
    wheel.fail_after_purchase = True
    plugin.run()
    assert wheel.purchases == [10, 10]
    assert wheel.calls[0]["request_key"] == wheel.calls[1]["request_key"]
    assert wheel.calls[0]["count"] == wheel.calls[1]["count"]
    assert saved(plugin, module)["last"]["draws"] == 20
    assert not saved(plugin, module)["pending"]


def test_restart_recovers_pending_even_with_zero_quota(plugin, module):
    wheel = connect(plugin, Wheel(remaining=10))
    plugin.init_plugin({"enabled": True, "daily_target": 500, "retries": 0})
    plugin._cancel.wait = Mock(return_value=False)
    wheel.fail_after_purchase = True
    plugin.run()
    pending = saved(plugin, module)["pending"]
    assert pending and wheel.remaining == 0
    second = module.PtlgsLuckyWheel()
    second.init_plugin({"enabled": True, "daily_target": 500, "retries": 0})
    second._cancel.wait = Mock(return_value=False)
    connect(second, wheel)
    second.run()
    assert len(wheel.purchases) == 1
    assert wheel.calls[-1]["request_key"] == pending["key"]
    assert saved(second, module)["last"]["draws"] == 10
    assert saved(second, module)["pending"] is None


@pytest.mark.parametrize("kind", ["429", "ret8", "invalid_json", "500"])
def test_throttle_and_unknown_errors_are_bounded(plugin, module, kind):
    wheel = connect(plugin)
    payload = {"ret": 8, "msg": "频繁"} if kind == "ret8" else ValueError("bad json")
    status = int(kind) if kind.isdigit() else 200
    wheel.post = Mock(return_value=response(payload, status=status, headers={"Retry-After": "40"}))
    plugin.run()
    assert wheel.post.call_count == 4
    keys = {c.kwargs["data"]["request_key"] for c in wheel.post.call_args_list}
    assert len(keys) == 1
    assert saved(plugin, module)["pending"]
    waits = [call.args[0] for call in plugin._cancel.wait.call_args_list]
    assert len(waits) == 3 and min(waits) >= 30


@pytest.mark.parametrize("ret", [1, 2, 3, 5, 6, 7])
def test_definite_rejection_stops_without_retries(plugin, module, ret):
    wheel = connect(plugin)
    wheel.post = Mock(return_value=response({"ret": ret, "msg": "private site text"}))
    plugin.run()
    assert wheel.post.call_count == 1
    assert not saved(plugin, module)["pending"]
    assert "private site text" not in plugin.notifications[0]["text"]


def test_rejection_after_timeout_does_not_forget_ambiguous_order(plugin, module):
    wheel = connect(plugin)
    wheel.post = Mock(side_effect=[requests.Timeout(), response({"ret": 1})])
    plugin.run()
    assert saved(plugin, module)["pending"]["uncertain"] is True
    assert wheel.post.call_count == 2


def test_persist_failure_prevents_post(plugin, module, monkeypatch):
    wheel = connect(plugin)
    monkeypatch.setattr(module.storage, "save", Mock(side_effect=module.WheelError("disk failure")))
    plugin.run()
    assert not wheel.calls


def test_corrupt_state_never_becomes_fresh_run(plugin, module):
    wheel = connect(plugin)
    plugin._path().write_text("broken json")
    plugin.run()
    assert not wheel.calls and not wheel.get.called
    assert "状态文件无法读取" in plugin.notifications[0]["text"]


def test_cancel_after_success_preserves_confirmed_result(plugin, module):
    wheel = connect(plugin)
    spin = wheel.spin

    def stop(*args, **kwargs):
        answer = spin(*args, **kwargs)
        plugin.stop_service()
        return answer

    wheel.post = Mock(side_effect=stop)
    plugin.run()
    s = saved(plugin, module)
    assert s["last"]["draws"] == 10 and s["pending"] is None
    assert wheel.purchases == [10]


def test_cancel_backoff_retains_order(plugin, module):
    wheel = connect(plugin)
    wheel.post = Mock(side_effect=requests.Timeout())
    plugin._cancel.wait = Mock(return_value=True)
    plugin.run()
    assert wheel.post.call_count == 1 and saved(plugin, module)["pending"]


def test_reload_generation_cannot_execute_old_job(plugin, module):
    wheel = connect(plugin)
    old_job = plugin.get_service()[0]["func"]
    plugin.init_plugin({"enabled": True})
    old_job()
    assert not wheel.get.called


def test_once_and_diagnose_dont_need_daily_enable(plugin, module):
    wheel = connect(plugin)
    plugin.init_plugin({"run_once": True, "diagnose_only": True})
    assert plugin.saved_config["run_once"] is False
    assert plugin.saved_config["diagnose_only"] is False
    job = plugin.get_service()[0]
    job["func"]()
    job["func"]()
    assert wheel.get.call_count == 1 and not wheel.post.called
    assert saved(plugin, module)["last"]["status"] == "诊断成功"


def test_timezone_cron_and_no_silent_fallback(plugin, module):
    trigger = plugin.get_service()[0]["trigger"]
    next_run = trigger.get_next_fire_time(None, datetime(2026, 10, 20, 7, 59, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert (next_run.hour, next_run.minute) == (8, 5)
    plugin.init_plugin({"enabled": True, "cron": "bad"})
    assert not plugin.get_state() and plugin.get_service() == []
    assert "配置无效" in json.dumps(plugin.get_page(), ensure_ascii=False)


def test_uncertain_order_account_and_age_guard(plugin, module):
    wheel = connect(plugin)
    wheel.post = Mock(side_effect=requests.Timeout())
    plugin._config["retries"] = 0
    plugin.run()
    s = saved(plugin, module)
    s["pending"]["created"] = time.time() - 901
    module.storage.save(plugin._path(), s)
    wheel.post.reset_mock()
    plugin.run()
    assert not wheel.post.called
    assert "15 分钟" in saved(plugin, module)["last"]["message"]
    s["pending"]["created"] = time.time()
    module.storage.save(plugin._path(), s)
    wheel.uid = "456"
    plugin.run()
    assert not wheel.post.called
    assert "其他账号" in saved(plugin, module)["last"]["message"]


def test_acknowledge_never_spins_or_clears_daily_ledger(plugin, module):
    wheel = connect(plugin)
    wheel.fail_after_purchase = True
    plugin._config["retries"] = 0
    plugin.run()
    state = saved(plugin, module)
    state["days"]["123:" + plugin._day()] = {"site_used": 10}
    module.storage.save(plugin._path(), state)
    plugin.init_plugin({"acknowledge_pending": True, "run_once": True})
    wheel.post.reset_mock()
    plugin.get_service()[0]["func"]()
    assert not wheel.post.called
    assert saved(plugin, module)["pending"] is None
    assert saved(plugin, module)["days"] == state["days"]


def test_two_instances_same_data_path_cannot_overlap(plugin, module):
    wheel = connect(plugin)
    entered, release = threading.Event(), threading.Event()
    fetch = wheel.fetch

    def wait_for_release(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return fetch(*args, **kwargs)

    wheel.get = Mock(side_effect=wait_for_release)
    other = module.PtlgsLuckyWheel()
    other.init_plugin({"enabled": True, "diagnose_only": True})
    other_wheel = connect(other)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(plugin.run)
        assert entered.wait(5)
        other.run()
        assert not other_wheel.get.called
        release.set()
        future.result(timeout=5)


def test_notification_failure_does_not_repeat_spins(plugin, module):
    wheel = connect(plugin)
    plugin.post_message = Mock(side_effect=RuntimeError("channel offline"))
    plugin.run()
    plugin.run()
    assert wheel.purchases == [10, 10]


def test_credentials_origin_and_transport_options(plugin, module):
    session = plugin._session(plugin._config)
    assert not session.trust_env
    assert "Cookie" not in session.headers
    assert session.cookies.get("session", domain="ptlgs.org", path="/") == "fixture-secret"
    assert "fixture-secret" not in json.dumps(plugin.get_form())
    session.close()
    module.site_fixture.url = "https://ptlgs.org.evil.invalid"
    with pytest.raises(module.WheelError):
        plugin._session(plugin._config)


def test_success_missing_prizes_still_counts_confirmed_purchase(plugin, module):
    wheel = connect(plugin)
    spin = wheel.spin

    def no_items(*args, **kwargs):
        r = spin(*args, **kwargs)
        d = r.json()["data"]
        d.pop("indices", None)
        d.pop("items", None)
        return r

    wheel.post = Mock(side_effect=no_items)
    plugin.run()
    assert saved(plugin, module)["last"]["draws"] == 20
    assert "明细缺失" in next(iter(saved(plugin, module)["last"]["prizes"]))


def test_market_metadata_and_native_form(plugin, module):
    root = Path(__file__).resolve().parents[3]
    entry = json.loads((root / "package.v3.json").read_text())["PtlgsLuckyWheel"]
    assert entry["version"] == plugin.plugin_version
    assert entry["system_version"] == ">=3.0.0"
    form = json.dumps(plugin.get_form(), ensure_ascii=False)
    assert "VCronField" in form and "VBtn" not in form
    assert plugin.get_api() == []


def test_restart_keeps_original_batch_when_settings_change(plugin, module):
    wheel = connect(plugin)
    plugin._config["retries"] = 0
    wheel.fail_after_purchase = True
    plugin.run()
    original = saved(plugin, module)["pending"]
    plugin.init_plugin({"enabled": True, "batch": 1, "daily_target": 10})
    plugin._cancel.wait = Mock(return_value=False)
    plugin.run()
    assert wheel.purchases == [10]
    assert wheel.calls[-1]["count"] == "10"
    assert wheel.calls[-1]["request_key"] == original["key"]


def test_cross_day_does_not_replay_old_order(plugin, module):
    wheel = connect(plugin)
    plugin._config["retries"] = 0
    wheel.fail_after_purchase = True
    plugin.run()
    state = saved(plugin, module)
    state["pending"]["day"] = "2000-01-01"
    module.storage.save(plugin._path(), state)
    wheel.post.reset_mock()
    plugin.run()
    assert not wheel.post.called and saved(plugin, module)["pending"]


def test_cross_day_during_success_stops_next_batch(plugin, module):
    wheel = connect(plugin)
    spin = wheel.spin

    def roll_day(*args, **kwargs):
        r = spin(*args, **kwargs)
        plugin._day = lambda: "2099-01-01"
        return r

    wheel.post = Mock(side_effect=roll_day)
    plugin.run()
    assert wheel.purchases == [10]
    assert saved(plugin, module)["last"]["message"].startswith("站点已跨日")


def test_success_with_invalid_count_keeps_order(plugin, module):
    wheel = connect(plugin)
    wheel.post = Mock(return_value=response({"ret": 0, "data": {"count": 3}}))
    plugin.run()
    assert wheel.post.call_count == 1 and saved(plugin, module)["pending"]


def test_long_retry_after_does_not_retry_early(plugin, module):
    wheel = connect(plugin)
    wheel.post = Mock(return_value=response(status=429, headers={"Retry-After": "1200"}))
    plugin.run()
    assert wheel.post.call_count == 1 and not plugin._cancel.wait.called


def test_authenticated_redirect_is_not_followed(plugin, module):
    wheel = connect(plugin)
    wheel.get = Mock(return_value=response(status=302))
    plugin.run()
    assert not wheel.post.called
    assert wheel.get.call_args.kwargs["allow_redirects"] is False
    assert wheel.close.called


def test_state_is_durable_before_first_request(plugin, module):
    wheel = connect(plugin)
    spin = wheel.spin

    def assert_saved(url, data, **kwargs):
        pending = saved(plugin, module)["pending"]
        assert pending["key"] == data["request_key"]
        assert pending["count"] == int(data.get("count", 1))
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (10, 30)
        return spin(url, data, **kwargs)

    wheel.post = Mock(side_effect=assert_saved)
    plugin.run()
    assert wheel.purchases == [10, 10]


def test_persisted_local_quota_survives_stale_site_page(plugin, module):
    wheel = connect(plugin)
    plugin.run()
    wheel.get = Mock(return_value=response(text=html(remaining=500)))
    plugin.run()
    assert wheel.purchases == [10, 10]


def test_count_rewards_with_aggregate_items_and_index_zero(module):
    assert module.rewards({"items": [{"label": "A", "count": 7}, {"label": "B", "count": 3}]}, 10) == {"A": 7, "B": 3}
    assert module.rewards({"labels": ["A", "B"], "index": 0}, 1) == {"A": 1}


def test_notification_uses_actual_balance_change_not_prize_label(plugin, module):
    wheel = connect(plugin)
    plugin._config["daily_target"] = 1
    spin = wheel.spin

    def taxed_reward(*args, **kwargs):
        r = spin(*args, **kwargs)
        d = r.json()["data"]
        d["labels"] = ["工分1000"]
        d["bonus"] = wheel.balance + 950
        return r

    wheel.post = Mock(side_effect=taxed_reward)
    plugin.run()
    result = saved(plugin, module)["last"]
    assert result["spent"] == 1000 and result["change"] == -50
    assert "工分变化 -50.0" in plugin.notifications[0]["text"]


@pytest.mark.parametrize("fails", [False, True])
def test_diagnosis_alone_is_one_shot_and_cannot_replay_after_reload(plugin, module, fails):
    wheel = connect(plugin)
    if fails:
        wheel.get = Mock(side_effect=requests.Timeout())
    plugin.init_plugin({"diagnose_only": True})
    assert plugin.get_state()
    assert plugin.saved_config["diagnose_only"] is False
    job = plugin.get_service()[0]["func"]
    job()
    job()
    assert wheel.get.call_count == 1 and not wheel.post.called
    assert not plugin.get_state()
    assert saved(plugin, module)["last"]["status"] == ("异常停止" if fails else "诊断成功")
    plugin.init_plugin(plugin.saved_config)
    assert plugin.get_service() == []


def test_diagnosis_does_not_disable_subsequent_cron_draws(plugin, module):
    wheel = connect(plugin)
    plugin.init_plugin({"enabled": True, "diagnose_only": True, "daily_target": 10})
    jobs = {job["id"].split(".")[-1]: job["func"] for job in plugin.get_service()}
    jobs["Once"]()
    assert not wheel.post.called
    jobs["Daily"]()
    jobs["Once"]()
    assert wheel.purchases == [10]


def test_diagnosis_reset_failure_blocks_execution(plugin):
    wheel = connect(plugin)
    plugin.update_config = Mock(return_value=False)
    plugin.init_plugin({"enabled": True, "diagnose_only": True})
    plugin.run(once=True)
    plugin.run()
    assert plugin.get_service() == [] and not wheel.get.called
    assert "复位失败" in plugin._error


def card_text(page, title):
    """Read the visible card, not incidental numbers elsewhere in the page."""
    def walk(node):
        yield node
        for child in node.get("content", []):
            yield from walk(child)

    for root in page:
        for node in walk(root):
            if node.get("component") == "VCard" and node["content"][0].get("text") == title:
                return [child["text"] for child in walk(node) if "text" in child]
    raise AssertionError(f"Missing card: {title}")


def test_daily_panel_accumulates_runs_and_survives_diagnosis_and_noop(plugin, module):
    wheel = connect(plugin)
    plugin.run()
    plugin._config["daily_target"] = 30
    plugin.run()
    plugin.run()  # Already at target: latest invocation has zero draws.
    plugin.init_plugin({"diagnose_only": True})
    plugin.get_service()[0]["func"]()
    assert saved(plugin, module)["last"]["draws"] == 0
    page = plugin.get_page()
    assert card_text(page, "今日抽奖（插件）")[-1] == "30 抽"
    assert card_text(page, "今日消耗工分")[-1] == "30,000"
    assert card_text(page, "站点今日剩余")[-1] == "470 抽"
    prizes = card_text(page, "今日奖品统计")
    assert "工分500" in prizes and "30" in prizes
    assert wheel.purchases == [10, 10, 10]


def test_daily_panel_rollover_is_read_only_and_keeps_history(plugin, module):
    wheel = connect(plugin)
    plugin._day = lambda: "2099-01-01"
    plugin.run()
    reads = wheel.get.call_count
    plugin._day = lambda: "2099-01-02"
    page = plugin.get_page()
    assert card_text(page, "今日抽奖（插件）")[-1] == "0 抽"
    assert card_text(page, "站点今日剩余")[-1] == "待检查"
    assert "工分500" not in card_text(page, "今日奖品统计")
    previous = card_text(page, "历史每日统计")
    assert "2099-01-01 · 20 抽" in previous and "工分500" in previous
    assert wheel.get.call_count == reads and wheel.purchases == [10, 10]
    wheel.remaining = 500
    plugin._config["daily_target"] = 10
    plugin.run()
    assert card_text(plugin.get_page(), "今日抽奖（插件）")[-1] == "10 抽"
    assert saved(plugin, module)["days"]["123:2099-01-01"]["draws"] == 20


def test_daily_panel_uses_active_account_and_migrates_single_legacy_account(plugin, module):
    wheel = connect(plugin)
    plugin.run()
    state = saved(plugin, module)
    state.pop("active_uid")
    state.pop("snapshot")
    module.storage.save(plugin._path(), state)
    assert card_text(plugin.get_page(), "今日抽奖（插件）")[-1] == "20 抽"
    state["days"]["456:" + plugin._day()] = {"draws": 7, "prizes": {"另一账号奖品": 7}}
    module.storage.save(plugin._path(), state)
    assert card_text(plugin.get_page(), "今日抽奖（插件）")[-1] == "—"
    wheel.uid = "456"
    plugin.init_plugin({"diagnose_only": True})
    plugin.get_service()[0]["func"]()
    page = plugin.get_page()
    assert card_text(page, "今日抽奖（插件）")[-1] == "7 抽"
    assert "另一账号奖品" in card_text(page, "今日奖品统计")
    assert "工分500" not in card_text(page, "今日奖品统计")


def test_daily_panel_keeps_manual_draws_separate_and_rejects_stale_quota(plugin, module):
    wheel = connect(plugin, Wheel(remaining=490))
    plugin.run()
    assert card_text(plugin.get_page(), "今日抽奖（插件）")[-1] == "10 抽"
    assert card_text(plugin.get_page(), "站点今日剩余")[-1] == "480 抽"
    wheel.get = Mock(return_value=response(text=html(remaining=500)))
    plugin.init_plugin({"diagnose_only": True})
    plugin.get_service()[0]["func"]()
    assert card_text(plugin.get_page(), "站点今日剩余")[-1] == "480 抽"


def test_diagnosis_crossing_reset_does_not_misdate_quota(plugin, module):
    wheel = connect(plugin)
    plugin._day = Mock(side_effect=["2099-01-01", "2099-01-02"])
    plugin.init_plugin({"diagnose_only": True})
    plugin.get_service()[0]["func"]()
    state = saved(plugin, module)
    assert "snapshot" not in state and state["last"]["status"] == "异常停止"
    assert not wheel.post.called

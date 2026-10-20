"""Real-page-shaped fixtures and cash-accounting regressions; no live draws."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests


def owned_html(name, until):
    return f'<div><div><img title="{name}"></div><div><span>过期时间: {until}</span></div></div>'


def shop_html(name, price, kind="medal"):
    return f'<div class="{kind}-info"><h3>{name}</h3><div><span>价格:</span><span>{price}</span></div></div>'


def pending(module, config=None, count=1):
    cfg = {**module.PtlgsLuckyWheel.defaults(), "auto_rewards": False, **(config or {})}
    now = module.reward_summary.expiry("2026-10-20 15:00")
    return {"count": count, "cost": 1000, "before": 100000, "created": now,
            "reward_context": module.reward_summary.context(cfg, now)}


def test_profile_expiry_not_worn_header_or_shop_availability(module):
    summary = module.reward_summary
    html = '<img title="二周年限定勋章">' + owned_html("二周年限定勋章（抽奖）", "永久有效")
    html += owned_html("黑丝娘☆卡牌", "2026-10-21 11:02")
    html += owned_html("二周年限定-头像框（抽奖）", "永久有效")
    parsed = summary.parse_reward_page(html)
    assert parsed.holdings == {"anniversary_medal": None, "anniversary_frame": None,
                               "heisiniang": summary.expiry("2026-10-21 11:02")}
    assert summary.parse_reward_page('<img title="黑丝娘☆卡牌"><button>已经购买</button>').holdings == {}
    complete = summary.parse_reward_page('<td id="outer"><h2>勋章</h2><h2>头像框</h2></td>')
    assert complete.holdings == {key: 0 for key in summary.SPECIAL}
    truncated = summary.parse_reward_page('<td id="outer"><h2>勋章</h2><h2>头像框</h2>')
    assert truncated.holdings == {}


def test_prices_do_not_match_regular_anniversary_editions(module):
    html = shop_html("二周年限定勋章", "500,000") + shop_html("二周年限定勋章（抽奖）", "50,000")
    html += shop_html("二周年限定", "100,000", "avatarframe")
    html += shop_html("二周年限定-头像框（抽奖）", "25,000", "avatarframe")
    html += shop_html("黑丝娘☆卡牌", "100")
    assert module.reward_summary.parse_reward_page(html).prices == {
        "anniversary_medal": 50000, "anniversary_frame": 25000, "heisiniang": 100}


def test_notification_merges_traffic_vip_and_points_without_double_counting(module):
    record = {"draws": 450, "spent": 450000, "change": -362100.4,
              "prizes": {"上传 1G": 61, "上传 5G": 30, "下载量 1G": 54, "工分500": 57,
                         "工分1000": 36, "VIP 1天": 8, "VIP 3天": 2, "谢谢参与": 90,
                         "黑丝娘的献礼": 4, "二周年限定-头像框": 2},
              "reward_accounting": {"covered": 450, "points": 87899.6, "estimated": True,
                  "converted": {"黑丝娘的献礼": {"count": 4, "points": 200, "estimated": True},
                                "二周年限定-头像框": {"count": 2, "points": 25000, "estimated": True}}}}
    text = "\n".join(module.reward_summary.reward_lines(record))
    assert "上传 +211 GB · 下载 +54 GB" in text
    assert "工分回流（余额口径） +87,899.6" in text and "25,200.0 工分（已计入" in text
    assert "VIP 14 天" in text
    assert all(label not in text for label in ["工分500", "工分1000", "谢谢参与", "黑丝娘的献礼", "二周年限定-头像框"])


def test_taxed_credit_uses_receipt_not_label_or_passive_income(module):
    p = pending(module)
    audit = module.reward_summary.accounting({"bonus": 99951.2, "bonus_gained": 950}, {"工分1000": 1}, p)
    record = {"draws": 1, "spent": 1000, "change": -48.8, "prizes": {"工分1000": 1}, "reward_accounting": audit}
    assert module.reward_summary.reward_lines(record) == ["奖励工分 +950.0"]


def test_same_batch_first_grant_then_duplicates_and_no_expiry_renewal(module):
    s = module.reward_summary
    p = pending(module, count=3)
    audit = s.accounting({"bonus": 97100}, {"黑丝娘的献礼": 3}, p)
    assert audit["converted"]["黑丝娘的献礼"]["count"] == 2
    until = p["reward_context"]["holdings"]["heisiniang"]
    assert until == p["created"] + 7 * 86400
    p["created"] += 60
    second = s.accounting({"bonus": 97150}, {"黑丝娘的献礼": 3}, p)
    assert second["converted"]["黑丝娘的献礼"]["count"] == 3
    assert p["reward_context"]["holdings"]["heisiniang"] == until
    p["created"] = until
    expired = s.accounting({"bonus": 97100}, {"黑丝娘的献礼": 3}, p)
    assert expired["converted"]["黑丝娘的献礼"]["count"] == 2


def test_explicit_compensation_overrides_manual_missing_ownership_without_renewing(module):
    p = pending(module)
    audit = module.reward_summary.accounting({"bonus": 99050, "bonus_gained": 50, "detail": "already_has"},
                                             {"黑丝娘的献礼": 1}, p)
    assert audit["converted"]["黑丝娘的献礼"] == {"count": 1, "points": 50, "estimated": False}
    assert "new_holdings" not in p["reward_context"]


def test_explicit_zero_credit_overrides_stale_owned_config(module):
    p = pending(module, {"owned_rewards": ["anniversary_frame"]})
    audit = module.reward_summary.accounting({"bonus": 99000, "bonus_gained": 0}, {"二周年限定-头像框": 1}, p)
    assert audit["converted"] == {}


def test_unknown_ownership_is_not_assumed_to_be_already_owned(module):
    p = pending(module, {"auto_rewards": True}, count=3)
    audit = module.reward_summary.accounting({"bonus": 97000}, {"黑丝娘的献礼": 3}, p)
    assert audit["converted"] == {}


@pytest.mark.parametrize("bad", ["not a date", "永久有效", "2026-99-99 12:00", ""])
def test_manual_black_card_requires_a_finite_expiry(plugin, bad):
    plugin.init_plugin({"enabled": True, "auto_rewards": False, "owned_rewards": ["heisiniang"], "heisiniang_until": bad})
    assert plugin._error and not plugin.get_service()


def test_context_reads_each_auxiliary_page_once_and_uses_auto_expiry(plugin, module):
    s = module.reward_summary
    config = {**plugin.defaults(), "owned_rewards": ["heisiniang"], "heisiniang_until": "2099-01-01 00:00"}
    pages = [owned_html("黑丝娘☆卡牌", "2026-10-19 11:02"), shop_html("黑丝娘☆卡牌", "101.1"), ""]
    session = Mock()
    session.get.side_effect = [SimpleNamespace(status_code=200, content=p.encode(), text=p) for p in pages]
    ctx = plugin._reward_context(session, SimpleNamespace(uid="123"), config, plugin._cancel, {})
    assert session.get.call_count == 3
    assert ctx["holdings"]["heisiniang"] == s.expiry("2026-10-19 11:02")
    p = pending(module, count=3); p["reward_context"] = ctx
    audit = s.accounting({"bonus": 97101.2}, {"黑丝娘的献礼": 3}, p)
    assert audit["converted"]["黑丝娘的献礼"]["points"] == 101.2  # 50.55 rounds half up per draw.
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)


def test_aux_failure_keeps_manual_fallback_and_does_not_retry(plugin, module):
    session = Mock(); session.get.side_effect = requests.Timeout()
    config = {**plugin.defaults(), "owned_rewards": ["anniversary_frame"]}
    ctx = plugin._reward_context(session, SimpleNamespace(uid="123"), config, plugin._cancel, {})
    assert session.get.call_count == 3 and ctx["holdings"]["anniversary_frame"] is None


def test_today_in_history_and_old_records_do_not_recompute_ownership(plugin, module):
    day = plugin._day()
    state = {"version": 1, "pending": None, "history": [], "active_uid": "123",
             "days": {"123:" + day: {"draws": 3, "spent": 3000, "change": -3000,
                                      "prizes": {"二周年限定-头像框": 3}}}}
    module.storage.save(plugin._path(), state)
    plugin.init_plugin({"owned_rewards": ["anniversary_frame"]})
    import json
    rendered = json.dumps(plugin.get_page(), ensure_ascii=False)
    assert day + "（今日） · 3 抽" in rendered
    assert "二周年限定-头像框 ×3" in rendered
    assert "重复奖品 3 次" not in rendered
    assert module.storage.load(plugin._path()) == state


def test_partial_legacy_summary_does_not_hide_old_points(module):
    record = {"draws": 20, "spent": 20000, "change": -18000, "prizes": {"工分500": 4},
              "reward_accounting": {"covered": 10, "points": 500, "estimated": False}}
    assert module.reward_summary.reward_lines(record) == ["工分回流（余额口径） +2,000.0"]

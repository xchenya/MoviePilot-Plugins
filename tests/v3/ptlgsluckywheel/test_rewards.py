"""Receipt accounting and display regressions; no live draws or auxiliary pages."""
import json

import pytest


def pending(count=1):
    return {"count": count, "cost": 1000, "before": 100000}


def test_notification_merges_traffic_vip_and_points_without_guessing_duplicates(module):
    record = {"draws": 450, "spent": 450000, "change": -362100.4,
              "prizes": {"上传 1G": 61, "上传 5G": 30, "下载量 1G": 54, "工分500": 57,
                         "工分1000": 36, "VIP 1天": 8, "VIP 3天": 2, "谢谢参与": 90,
                         "黑丝娘的献礼": 4, "二周年限定-头像框": 2}}
    text = "\n".join(module.reward_summary.reward_lines(record))
    assert "上传 +211 GB · 下载 +54 GB" in text
    assert "工分回流（余额口径） +87,899.6" in text
    assert "VIP 14 天" in text
    assert "其他命中：黑丝娘的献礼 ×4 · 二周年限定-头像框 ×2" in text
    assert all(label not in text for label in ["工分500", "工分1000", "谢谢参与", "重复奖品"])


def test_taxed_credit_uses_single_receipt_not_label_or_passive_income(module):
    audit = module.reward_summary.accounting({"bonus": 99951.2, "bonus_gained": 950}, {"工分1000": 1}, pending())
    record = {"draws": 1, "spent": 1000, "change": -48.8, "prizes": {"工分1000": 1}, "reward_accounting": audit}
    assert module.reward_summary.reward_lines(record) == ["奖励工分 +950.0"]


def test_explicit_duplicate_credit_is_included_once(module):
    audit = module.reward_summary.accounting({"bonus": 99050, "bonus_gained": 50, "detail": "already_has"},
                                             {"黑丝娘的献礼": 1}, pending())
    assert audit["converted"] == {"黑丝娘的献礼": {"count": 1, "points": 50}}
    record = {"draws": 1, "spent": 1000, "change": -950, "prizes": {"黑丝娘的献礼": 1}, "reward_accounting": audit}
    assert module.reward_summary.reward_lines(record) == ["奖励工分 +50.0", "重复奖品 1 次 → 50.0 工分（已计入合计）"]


def test_new_special_prize_is_not_inferred_to_be_a_conversion(module):
    audit = module.reward_summary.accounting({"bonus": 99000, "bonus_gained": 0}, {"二周年限定-头像框": 1}, pending())
    assert audit["converted"] == {} and audit["points"] == 0 and not audit["estimated"]


@pytest.mark.parametrize("bad", [None, "invalid", float("nan"), -1, True])
def test_bad_optional_credit_keeps_confirmed_purchase_and_uses_balance(module, bad):
    audit = module.reward_summary.accounting({"bonus": 99050, "bonus_gained": bad, "detail": "already_has"},
                                             {"黑丝娘的献礼": 1}, pending())
    assert audit["converted"] == {} and audit["points"] == 50 and audit["estimated"]


def test_batch_does_not_assume_single_credit_fields_are_per_batch(module):
    audit = module.reward_summary.accounting({"bonus": 97100, "bonus_gained": 50, "detail": "already_has"},
                                             {"黑丝娘的献礼": 3}, pending(count=3))
    assert audit["converted"] == {} and audit["points"] == 100 and audit["estimated"]


def test_today_in_history_and_old_records_keep_original_hits(plugin, module):
    day = plugin._day()
    state = {"version": 1, "pending": None, "history": [], "active_uid": "123",
             "days": {"123:" + day: {"draws": 3, "spent": 3000, "change": -3000,
                                      "prizes": {"二周年限定-头像框": 3}}}}
    module.storage.save(plugin._path(), state)
    rendered = json.dumps(plugin.get_page(), ensure_ascii=False)
    assert day + "（今日） · 3 抽" in rendered
    assert "二周年限定-头像框 ×3" in rendered
    assert "重复奖品 3 次" not in rendered
    assert module.storage.load(plugin._path()) == state


def test_partial_legacy_summary_does_not_hide_old_points(module):
    record = {"draws": 20, "spent": 20000, "change": -18000, "prizes": {"工分500": 4},
              "reward_accounting": {"covered": 10, "points": 500, "estimated": False}}
    assert module.reward_summary.reward_lines(record) == ["工分回流（余额口径） +2,000.0"]


def test_no_ownership_or_expiry_configuration(plugin):
    form, defaults = plugin.get_form()
    rendered = json.dumps(form)
    for name in ("auto_rewards", "owned_rewards", "heisiniang_until"):
        assert name not in defaults and name not in rendered

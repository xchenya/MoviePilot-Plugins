"""Summarize confirmed receipts without ownership lookups or price estimates."""
from __future__ import annotations

import re

from .protocol import WheelError, number


def accounting(data, won, pending):
    """Use observed single-draw credit fields; balance changes cover other receipts."""
    count = pending["count"]
    # bonus is the account balance, not a prize value. The credit field has only
    # been confirmed for single draws, so do not assume batch-level semantics.
    estimated = True
    points = round(number(data["bonus"]) - pending["before"] + pending["cost"] * count, 1)
    if count == 1 and "bonus_gained" in data:
        try:
            points, estimated = number(data["bonus_gained"]), False
        except WheelError:
            pass  # Optional metadata must never invalidate a confirmed purchase.
    result = {"covered": count, "points": points, "estimated": estimated, "converted": {}}
    if (not estimated and points > 0 and data.get("detail") == "already_has"
            and len(won) == 1 and sum(won.values()) == 1):
        label = next(iter(won))
        result["converted"][label] = {"count": 1, "points": points}
    return result


def merge_accounting(target, source):
    """Increment only after a confirmed receipt, alongside the existing daily ledger."""
    target["covered"] = target.get("covered", 0) + source["covered"]
    target["points"] = round(target.get("points", 0) + source["points"], 1)
    target["estimated"] = target.get("estimated", False) or source["estimated"]
    for label, item in source["converted"].items():
        old = target.setdefault("converted", {}).setdefault(label, {"count": 0, "points": 0})
        old["count"] += item["count"]
        old["points"] = round(old["points"] + item["points"], 1)


def reward_lines(record):
    """Compact notification/page summary; retained raw labels remain separately inspectable."""
    prizes = record.get("prizes") or {}
    audit = record.get("reward_accounting") or {}
    converted = audit.get("converted") or {}
    upload = download = vip = 0
    others = []
    for label, count in prizes.items():
        if label == "谢谢参与" or re.fullmatch(r"工分\s*[\d,.]+", label):
            continue
        transfer = re.fullmatch(r"(上传|下载)(?:量)?\s*(\d+(?:\.\d+)?)\s*(G|GB|GiB|T|TB|TiB|M|MB|MiB)", label, re.I)
        if transfer:
            gib = float(transfer[2]) * count * {"G": 1, "T": 1024, "M": 1 / 1024}[transfer[3][0].upper()]
            if transfer[1] == "上传":
                upload += gib
            else:
                download += gib
            continue
        days = re.fullmatch(r"VIP\s*(\d+)\s*天", label, re.I)
        if days:
            vip += int(days[1]) * count
            continue
        left = max(0, count - converted.get(label, {}).get("count", 0))
        if left:
            others.append((label, left))
    lines = []
    traffic = ([f"上传 +{upload:g} GB"] if upload else []) + ([f"下载 +{download:g} GB"] if download else [])
    if traffic:
        lines.append(" · ".join(traffic))
    if record.get("draws", 0):
        exact = audit.get("covered") == record["draws"] and not audit.get("estimated", True)
        # Partial old/new histories use the complete balance-based total, not just new receipts.
        points = audit["points"] if exact else round(record.get("spent", 0) + record.get("change", 0), 1)
        lines.append(f"{'奖励工分' if exact else '工分回流（余额口径）'} {points:+,.1f}")
    if converted:
        total = sum(v["points"] for v in converted.values())
        amount = sum(v["count"] for v in converted.values())
        lines.append(f"重复奖品 {amount} 次 → {total:,.1f} 工分（已计入合计）")
    if vip:
        lines.append(f"VIP {vip} 天")
    items = [f"{label} ×{count}" for label, count in sorted(others, key=lambda p: (-p[1], p[0]))]
    for index in range(0, len(items), 3):
        lines.append("其他命中：" + " · ".join(items[index:index + 3]))
    return lines

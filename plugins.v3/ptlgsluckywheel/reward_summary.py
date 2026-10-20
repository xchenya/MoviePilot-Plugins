"""Reward accounting: preserve landed labels and separately describe actual gains."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from .protocol import WheelError, number

SITE_ZONE = ZoneInfo("Asia/Shanghai")
SPECIAL = {
    "anniversary_medal": {"name": "二周年限定勋章（抽奖）", "label": "二周年限定勋章（虚拟）", "price": 50000},
    "anniversary_frame": {"name": "二周年限定-头像框（抽奖）", "label": "二周年限定-头像框", "price": 25000},
    "heisiniang": {"name": "黑丝娘☆卡牌", "label": "黑丝娘的献礼", "price": 100, "days": 7},
}


def special_key(label):
    """Do not confuse purchased anniversary editions with the lottery editions."""
    for key, item in SPECIAL.items():
        if label in (item["name"], item["label"]):
            return key
    if label.startswith("黑丝娘的献礼（黑丝娘☆卡牌"):
        return "heisiniang"
    return None


def expiry(value):
    """Site profile dates and the manual expiry field use Beijing time."""
    value = str(value).strip()
    if value == "永久有效":
        return None
    try:
        date = datetime.fromisoformat(value)
        return (date if date.tzinfo else date.replace(tzinfo=SITE_ZONE)).timestamp()
    except (ValueError, TypeError) as exc:
        raise WheelError("黑丝娘到期时间格式应为 YYYY-MM-DD HH:MM（北京时间）") from exc


class RewardHTML(HTMLParser):
    """Read small enclosing DIVs, not worn header icons or shop availability buttons."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.holdings, self.prices = {}, {}
        self.headings, self.seen_names = set(), set()
        self._heading = None
        self._outer_depth = 0
        self.profile_complete = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td":
            if self._outer_depth:
                self._outer_depth += 1
            elif attrs.get("id") == "outer":
                self._outer_depth = 1
        if tag == "h2":
            self._heading = []
        if tag == "div":
            self.stack.append({"names": set(), "text": [], "class": attrs.get("class", "")})
        if tag == "img" and attrs.get("title"):
            self.seen_names.add(attrs["title"])
            for block in self.stack:
                block["names"].add(attrs["title"])

    def handle_data(self, data):
        if self._heading is not None:
            self._heading.append(data)
        for block in self.stack:
            block["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self._heading is not None:
            self.headings.add("".join(self._heading).strip())
            self._heading = None
        if tag == "td" and self._outer_depth:
            self._outer_depth -= 1
            if not self._outer_depth and {"勋章", "头像框"} <= self.headings:
                self.profile_complete = True
        if tag != "div" or not self.stack:
            return
        block = self.stack.pop()
        text = " ".join(" ".join(block["text"]).split())
        names = block["names"]
        if len(names) == 1:
            name = next(iter(names))
            key = next((k for k, v in SPECIAL.items() if v["name"] == name), None)
            match = re.search(r"过期时间\s*[:：]\s*(永久有效|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", text)
            if key and match and key not in self.holdings:
                self.holdings[key] = expiry(match[1])
        if set(block["class"].split()) & {"medal-info", "avatarframe-info"}:
            for key, item in SPECIAL.items():
                # A full, exact heading prefix prevents the regular edition's price matching.
                if not text.startswith(item["name"] + " "):
                    continue
                match = re.search(r"(?:^|\s)价格\s*[:：]\s*([\d,]+(?:\.\d+)?)", text)
                if match:
                    self.prices[key] = number(match[1])


def parse_reward_page(text):
    parser = RewardHTML()
    parser.feed(text)
    if parser.profile_complete:
        for key, item in SPECIAL.items():
            if item["name"] not in parser.seen_names:
                parser.holdings[key] = 0
    return parser


def context(config, now):
    """Manual inputs are fallback observations, frozen into each pending order."""
    holdings = {} if config["auto_rewards"] else {key: 0 for key in SPECIAL}
    for key in config["owned_rewards"]:
        if key == "heisiniang":
            value = config.get("heisiniang_until")
            if value:
                holdings[key] = expiry(value)
        else:
            holdings[key] = None
    return {"holdings": holdings, "prices": {k: v["price"] for k, v in SPECIAL.items()},
            "observed_at": now}


def accounting(data, won, pending):
    """Prefer explicit credits; never infer cash from the printed prize amount."""
    count = pending["count"]
    # bonus is the account balance, not a prize value. Only bonus_gained is a credit.
    estimated = True
    points = round(number(data["bonus"]) - pending["before"] + pending["cost"] * count, 1)
    if "bonus_gained" in data:
        try:
            points, estimated = number(data["bonus_gained"]), False
        except WheelError:
            pass  # Optional metadata must never invalidate a confirmed purchase.
    result = {"covered": count, "points": points, "estimated": estimated, "converted": {}}
    ctx = pending.get("reward_context") or {"holdings": {}, "prices": {}}
    holdings = ctx["holdings"]
    for label, amount in won.items():
        key = special_key(label)
        if not key:
            continue
        known = key in holdings
        until = holdings.get(key)
        owned = known and (until is None or until > pending["created"])
        converted = amount if owned else max(0, amount - 1) if known else 0
        credit, inferred = None, True
        if count == 1 and data.get("detail") == "already_has" and "bonus_gained" in data:
            try:
                credit, converted, inferred = number(data["bonus_gained"]), 1, False
                known, owned = True, True
                if not SPECIAL[key].get("days"):
                    holdings[key] = None
                    ctx.setdefault("new_holdings", {})[key] = None
            except WheelError:
                pass
        elif count == 1 and "bonus_gained" in data and not estimated and points == 0:
            # An explicit zero credit for a special prize is a new grant, even if
            # the configured ownership was stale. Compensation does not renew expiry.
            known, owned, converted = True, False, 0
        if converted:
            if credit is None:
                price = ctx["prices"].get(key, SPECIAL[key]["price"])
                each = (Decimal(str(price)) / 2).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                credit = float(each * converted)
            result["converted"][label] = {"count": converted, "points": credit, "estimated": inferred}
        if known and not owned:
            days = SPECIAL[key].get("days")
            holdings[key] = pending["created"] + days * 86400 if days else None
            ctx.setdefault("new_holdings", {})[key] = holdings[key]
    return result


def merge_accounting(target, source):
    """Increment only after a confirmed receipt, alongside the existing daily ledger."""
    target["covered"] = target.get("covered", 0) + source["covered"]
    target["points"] = round(target.get("points", 0) + source["points"], 1)
    target["estimated"] = target.get("estimated", False) or source["estimated"]
    for label, item in source["converted"].items():
        old = target.setdefault("converted", {}).setdefault(label, {"count": 0, "points": 0, "estimated": False})
        old["count"] += item["count"]
        old["points"] = round(old["points"] + item["points"], 1)
        old["estimated"] = old["estimated"] or item["estimated"]


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
        prefix = "约 " if any(v.get("estimated") for v in converted.values()) else ""
        lines.append(f"重复奖品 {amount} 次 → {prefix}{total:,.1f} 工分（已计入，不重复相加）")
    items = ([f"VIP {vip} 天"] if vip else []) + [f"{label} ×{count}" for label, count in sorted(others, key=lambda p: (-p[1], p[0]))]
    for index in range(0, len(items), 3):
        lines.append(" · ".join(items[index:index + 3]))
    return lines

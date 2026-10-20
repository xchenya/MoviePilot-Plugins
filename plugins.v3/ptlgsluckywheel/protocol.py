"""PTLGS wheel's observed HTML/JSON contract; no execution of site JavaScript."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser


class WheelError(Exception):
    """A safe, user-facing error, never including credentials or response bodies."""


def number(value) -> float:
    """Parse finite nonnegative site amounts, including thousands separators."""
    if isinstance(value, bool):
        raise WheelError("站点数字格式异常")
    try:
        result = float(str(value).replace(",", ""))
    except (ValueError, TypeError) as exc:
        raise WheelError("站点数字格式异常") from exc
    if not math.isfinite(result) or result < 0:
        raise WheelError("站点数字格式异常")
    return result


def integer(value) -> int:
    """Reject fractional counts instead of silently rounding them."""
    result = number(value)
    if result != int(result):
        raise WheelError("站点次数格式异常")
    return int(result)


def daily_counts(data) -> tuple[int, int]:
    """Read the explicit daily limit and remaining count; zero is meaningful."""
    if not isinstance(data, dict) or not {"limit", "remaining"} <= data.keys():
        raise WheelError("无法读取站点今日剩余次数")
    limit, remaining = integer(data["limit"]), integer(data["remaining"])
    if remaining > limit:
        raise WheelError("站点今日次数不一致")
    return limit, remaining


class WheelHTML(HTMLParser):
    """Collect only inline scripts and the wheel balance DOM node."""

    def __init__(self):
        super().__init__()
        self.scripts, self.balance = [], []
        self._script = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._script = "src" not in attrs
        if self._depth:
            self._depth += 1
        elif attrs.get("id") == "lw-balance":
            self._depth = 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = False
        if self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._script:
            self.scripts.append(data)
        if self._depth:
            self.balance.append(data)


@dataclass
class Snapshot:
    """Validated state needed before opening a new draw order."""
    csrf: str
    uid: str
    cost: float
    balance: float
    limit: int
    remaining: int
    ready: bool
    batches: list[int]


def parse_page(text: str) -> Snapshot:
    """Read the current frontend constants, failing closed on contract changes."""
    parser = WheelHTML()
    parser.feed(text)
    code = "\n".join(parser.scripts)

    def raw(name):
        match = re.search(r"\b(?:var|let|const)\s+" + name + r"\s*=\s*", code)
        if not match:
            raise WheelError("页面未就绪或登录失效：缺少大转盘状态，请更新站点 Cookie")
        return code[match.end():]

    def literal(name):
        try:
            return json.JSONDecoder().raw_decode(raw(name))[0]
        except (ValueError, TypeError) as exc:
            raise WheelError("大转盘页面结构已变化，已停止抽奖") from exc

    token = re.match(r"['\"]([A-Za-z0-9_-]{16,256})['\"]", raw("CSRF"))
    account = re.match(r"['\"]luckywheel-pending-(\d+)['\"]", raw("STORAGE_KEY"))
    if not token or not account:
        raise WheelError("无法核对登录账号或 CSRF，已停止抽奖")
    ready = literal("GAME_READY")
    counts = literal("MULTI_COUNTS")
    if not isinstance(ready, bool) or not isinstance(counts, list):
        raise WheelError("大转盘状态格式异常")
    limit, remaining = daily_counts(literal("DAILY"))
    cost = number(literal("COST"))
    if cost <= 0 or not parser.balance:
        raise WheelError("无法读取抽奖消耗或工分余额")
    batches = sorted({1, *(integer(item) for item in counts)}, reverse=True)
    if any(item < 1 or item > 500 for item in batches):
        raise WheelError("站点连抽数量异常")
    return Snapshot(token[1], account[1], cost, number("".join(parser.balance).strip()),
                    limit, remaining, ready, batches)


def rewards(data: dict, count: int) -> dict[str, int]:
    """Count landed labels, never treat an aggregate item as a single draw."""
    labels = data.get("labels")
    indices = data.get("indices")
    if count == 1 and "index" in data:
        indices = [data["index"]]
    landed = []
    if isinstance(indices, list) and isinstance(labels, list) and len(indices) == count:
        for index in indices:
            i = integer(index)
            if i >= len(labels) or not isinstance(labels[i], str):
                raise WheelError("站点返回的奖品索引异常")
            landed.append(labels[i][:120])
    elif isinstance(data.get("items"), list):
        for item in data["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                raise WheelError("站点返回的奖品格式异常")
            amount = integer(item.get("count", 1))
            if amount > count:
                raise WheelError("站点奖品数量异常")
            landed.extend([item["label"][:120]] * amount)
    elif count == 1 and isinstance(data.get("label"), str):
        landed = [data["label"][:120]]
    if len(landed) != count:
        raise WheelError("抽奖已确认，但奖品明细未完整返回")
    return dict(Counter(landed))

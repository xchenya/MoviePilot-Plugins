"""Observed TangPT HTML/JSON contract; never execute remote JavaScript."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from lxml import etree

ORIGIN = "https://www.tangpt.top"
PAGE_URL = ORIGIN + "/omnibot_lottery.php"
DRAW_URL = ORIGIN + "/web/omnibot/lottery/draw"


class LotteryError(Exception):
    """Safe public error without response bodies, cookies or arbitrary URLs."""


def number(value) -> float:
    """Accept only finite, nonnegative amounts, including grouped digits."""
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise LotteryError("数字格式无效，已停止") from exc
    if isinstance(value, bool) or not math.isfinite(result) or result < 0:
        raise LotteryError("数字格式无效，已停止")
    return result


def integer(value) -> int:
    """Reject fractional counts instead of silently truncating them."""
    result = number(value)
    if result != int(result):
        raise LotteryError("次数必须为非负整数")
    return int(result)


@dataclass(frozen=True)
class Snapshot:
    """Validated login, price, balance and currently available site quota."""
    uid: str
    balance: float
    cost: float
    remaining: int
    ready: bool
    batches: tuple[int, ...]


def parse_page(text: str) -> Snapshot:
    """Read fresh server-rendered state and the signed-in account header."""
    root = etree.HTML(text)
    if root is None:
        raise LotteryError("抽奖页面为空，请检查站点连接")
    scripts = "\n".join(root.xpath("//script[not(@src)]/text()"))
    match = re.search(r"\bwindow\.qqbotLotteryState\s*=\s*", scripts)
    if not match:
        raise LotteryError("未找到抽奖状态，请更新站点 Cookie 或核对页面结构")
    try:
        state = json.JSONDecoder().raw_decode(scripts[match.end():])[0]
        if not isinstance(state, dict):
            raise ValueError()
        if any(type(state.get(key)) is not bool for key in ("enabledDraw", "enabledPool")):
            raise ValueError()
        cost = number(state["costPerDraw"])
        maximum = integer(state["maxDrawCount"])
        remaining = integer(state["dailyDrawRemaining"])
        if cost <= 0 or not 1 <= maximum <= 10000 or remaining > 100000:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise LotteryError("抽奖状态结构已变化，已停止") from exc

    headers = root.xpath("//*[@id='info_block']")
    if len(headers) != 1:
        raise LotteryError("无法核对登录账号，请检查 Cookie")
    uid, logged_in, balance_text = None, False, None
    for link in headers[0].xpath(".//a[@href]"):
        url = urlsplit(link.get("href"))
        if url.hostname and url.hostname not in ("www.tangpt.top", "tangpt.top"):
            continue
        path = url.path.rsplit("/", 1)[-1]
        if path == "logout.php":
            logged_in = True
        if path == "userdetails.php" and not logged_in:
            candidate = parse_qs(url.query).get("id", [""])[0]
            if candidate.isdigit():
                uid = candidate
        if path == "mybonus.php" and balance_text is None:
            balance_text = link.tail or ""
    balance_match = re.match(r"\s*[:：]\s*([\d,]+(?:\.\d+)?)", balance_text or "")
    if not logged_in or not uid or not balance_match:
        raise LotteryError("无法核对登录账号或魔力余额，请更新站点 Cookie")
    batches = {integer(value) for value in root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' omnibot-draw-trigger ')]/@data-draw-count")}
    batches = {n for n in batches if n in (1, 10, 20, 50, 100) and n <= maximum}
    if 1 not in batches:
        raise LotteryError("无法核对站点抽奖档位，已停止")
    return Snapshot(uid, number(balance_match[1]), cost, remaining,
                    state["enabledDraw"] and state["enabledPool"], tuple(sorted(batches, reverse=True)))


def receipt(data, pending: dict) -> dict:
    """Validate the frontend's bare JSON receipt before clearing a pending write."""
    if not isinstance(data, dict):
        raise LotteryError("抽奖回执格式异常，结果待核对")
    try:
        count = integer(data["draw_count"])
        spent = number(data["total_cost"])
        balance = number(data["user_bonus_after"])
        compensated = number(data["total_compensated_bonus"])
    except (KeyError, TypeError) as exc:
        raise LotteryError("抽奖回执缺少结算字段，结果待核对") from exc
    if count != pending["count"] or not math.isclose(spent, pending["cost"] * count, abs_tol=0.01):
        raise LotteryError("抽奖次数或扣费与请求不符，结果待核对")
    prizes = Counter()
    results = data.get("results")
    if isinstance(results, list) and len(results) == count:
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                prizes["奖品明细缺失，请核对站点"] += 1
                continue
            name = str(item.get("prize_name") or "奖品").strip()[:60]
            content = " ".join(item["content"].split())[:160]
            label = f"{name}：{content}"
            if item.get("is_compensated"):
                try:
                    label += f"（折算 {number(item['comp_bonus']):g} 魔力）"
                except (KeyError, LotteryError):
                    label += "（已折算）"
            prizes[label] += 1
    else:
        prizes["奖品明细缺失，请核对站点"] = count
    return {"draws": count, "spent": spent, "balance": balance, "compensated": compensated,
            "change": round(balance - pending["before"], 2), "prizes": dict(prizes)}

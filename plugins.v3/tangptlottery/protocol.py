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
    source: str = "内嵌状态"


def visible_text(node) -> str:
    """Join split DOM text without relying on the tail of a particular anchor."""
    return " ".join(" ".join(node.xpath(
        ".//text()[not(ancestor::script) and not(ancestor::style)]")).split())


def local_links(node):
    """Ignore external profile/logout links when identifying the current account."""
    for link in node.xpath(".//a[@href]"):
        try:
            url = urlsplit(link.get("href"))
            if (url.scheme not in ("", "http", "https")
                    or (url.hostname and url.hostname not in ("www.tangpt.top", "tangpt.top"))):
                continue
        except ValueError:
            continue
        yield link, url


def account_header(root):
    """Use the site header, or the nearest logout/profile container in other themes."""
    headers = root.xpath("//*[@id='info_block']")
    if not headers:
        for link, url in local_links(root):
            if url.path.rsplit("/", 1)[-1] != "logout.php":
                continue
            for parent in link.iterancestors():
                if parent.tag in ("body", "html"):
                    break
                ids = {parse_qs(candidate.query).get("id", [""])[0]
                       for _, candidate in local_links(parent)
                       if candidate.path.rsplit("/", 1)[-1] == "userdetails.php"}
                if len(ids) == 1 and next(iter(ids)).isdigit():
                    headers.append(parent)
                    break
    for header in headers:
        before_logout, profiles, logged_in = [], [], False
        for _, url in local_links(header):
            name = url.path.rsplit("/", 1)[-1]
            if name == "logout.php":
                logged_in = True
            elif name == "userdetails.php":
                uid = parse_qs(url.query).get("id", [""])[0]
                if uid.isdigit():
                    profiles.append(uid)
                    if not logged_in:
                        before_logout.append(uid)
        if logged_in:
            if before_logout:
                return header, before_logout[-1]
            if len(set(profiles)) == 1:
                return header, profiles[0]
    raise LotteryError("页面解析失败：未识别当前账号登录栏；不能据此判定 Cookie 失效")


AMOUNT = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def magic_balance(root, header) -> float:
    """Prefer the lottery balance label, then the header label and bonus anchor."""
    match = re.search(r"当前魔力\s*[:：]\s*" + AMOUNT, visible_text(root))
    if match:
        return number(match[1])
    match = re.search(r"魔力(?:值)?\s*(?:\[\s*[^\[\]:：]{0,40}\]?\s*)?[:：]\s*" + AMOUNT,
                      visible_text(header))
    if match:
        return number(match[1])
    for link, url in local_links(header):
        if url.path.rsplit("/", 1)[-1] != "mybonus.php":
            continue
        # Themes put the balance inside the anchor, in a span, or after its parent.
        match = re.search(r"[:：]\s*" + AMOUNT, visible_text(link))
        if not match:
            following = link.xpath("following::text()[not(ancestor::script) and not(ancestor::style)]")
            match = re.match(r"\s*[:：]\s*" + AMOUNT, " ".join(following[:8]))
        if match:
            return number(match[1])
    raise LotteryError("页面解析失败：已识别登录账号，但未读到魔力余额；不能据此判定 Cookie 失效")


def text_quota(text):
    """Read the actual remaining count; never assume a fixed daily allowance."""
    match = re.search(r"(?:今天|今日)还可以抽\s*([\d,]+)\s*次", text)
    if not match:
        match = re.search(r"(?:抽奖剩余次数|剩余抽奖次数|剩余次数)\s*[:：]?\s*([\d,]+)", text)
    if match:
        return integer(match[1])
    match = re.search(r"(?:今天|今日)最多可抽奖\s*([\d,]+)\s*次.{0,100}?当前已抽\s*([\d,]+)\s*次", text)
    if match:
        total, drawn = integer(match[1]), integer(match[2])
        if drawn <= total:
            return total - drawn
    raise LotteryError("页面解析失败：未读到站点剩余抽奖次数，未发起抽奖")


def parse_page(text: str) -> Snapshot:
    """Read fresh server-rendered state and the signed-in account header."""
    root = etree.HTML(text)
    if root is None:
        raise LotteryError("抽奖页面为空，请检查站点连接")
    plain = visible_text(root)
    title = " ".join(root.xpath("//title/text()"))
    if (root.xpath("//*[@id='challenge-form' or @id='cf-challenge-running']")
            or "just a moment" in title.lower() or "checking your browser" in plain.lower()):
        raise LotteryError("站点返回浏览器验证／风控页面；请核对 User-Agent 和访问网络，未判定 Cookie 失效")
    login_form = root.xpath("//form[.//input[@type='password']]")
    login_prompt = re.search(r"(?:请先登录|尚未登录|您还没有登录|Cookie\s*失效|非法访问)", plain, re.I)
    has_logout = any(url.path.rsplit("/", 1)[-1] == "logout.php" for _, url in local_links(root))
    if not has_logout and (login_form or login_prompt):
        raise LotteryError("站点明确返回登录提示：当前 Cookie 未获登录，请更新所用 Cookie")
    header, uid = account_header(root)
    balance = magic_balance(root, header)
    buttons = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' omnibot-draw-trigger ')]")
    try:
        batches = {integer(button.get("data-draw-count")) for button in buttons}
    except LotteryError as exc:
        raise LotteryError("页面解析失败：抽奖档位格式变化，未发起抽奖") from exc
    batches &= {1, 10, 20, 50, 100}
    if 1 not in batches:
        raise LotteryError("页面解析失败：未识别站点抽奖按钮，未发起抽奖")
    scripts = "\n".join(root.xpath("//script[not(@src)]/text()"))
    match = re.search(r"\bwindow\.qqbotLotteryState\s*=\s*", scripts)
    if not match:
        cost_match = re.search(r"单次消耗\s*[:：]?\s*" + AMOUNT, plain)
        if not cost_match or number(cost_match[1]) <= 0:
            raise LotteryError("页面解析失败：未读到单次抽奖费用，未发起抽奖")
        remaining = text_quota(plain)
        if remaining > 100000:
            raise LotteryError("页面解析失败：站点剩余次数超出合理范围")
        ready = any(button.get("disabled") is None and button.get("aria-disabled") != "true"
                    and button.get("data-draw-count") in {str(n) for n in batches} for button in buttons)
        return Snapshot(uid, balance, number(cost_match[1]), remaining, ready,
                        tuple(sorted(batches, reverse=True)), "页面文字")
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

    batches = {n for n in batches if n <= maximum}
    return Snapshot(uid, balance, cost, remaining,
                    state["enabledDraw"] and state["enabledPool"], tuple(sorted(batches, reverse=True)))


def receipt(data, pending: dict) -> dict:
    """Validate the frontend's bare JSON receipt before clearing a pending write."""
    if not isinstance(data, dict):
        raise LotteryError("抽奖回执格式异常，结果待核对")
    if data.get("ok") is not True:
        message = str(data.get("message") or data.get("msg") or "").lower()
        if any(word in message for word in ("cookie", "未登录", "请先登录", "非法访问", "auth")):
            raise LotteryError("抽奖接口返回登录／权限失败，请核对所用 Cookie；结果待核对，本次未重试")
        if any(word in message for word in ("次数不足", "最多可抽奖", "remaining")):
            raise LotteryError("抽奖接口返回次数限制；结果待核对，本次未重试")
        raise LotteryError("抽奖接口未确认成功（ok 不为 true）；结果待核对，本次未重试")
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

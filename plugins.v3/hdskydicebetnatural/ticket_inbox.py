"""Read-only parsers for HDSky/NexusPHP rating-award private messages.

No network activity is permitted in this module. Page parsing must fail closed
when a source date or pagination is ambiguous; missing mail is not the number 0.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?:日)?(?!\d)"
)
REWARD_TEXT = "观影随机续期奖励"
MESSAGE_LINK = re.compile(r"messages\.php\?[^\"'#\s]*action=viewmessage", re.I)


class TicketInboxError(ValueError):
    """Not enough reliable data to assert today's exact ticket count."""


@dataclass(frozen=True)
class InboxEntry:
    mid: str
    day: str | None
    subject: str


@dataclass(frozen=True)
class InboxPage:
    entries: tuple[InboxEntry, ...]
    has_next: bool
    valid: bool


def _day(text: str, today: str) -> str | None:
    m = DATE_RE.search(text or "")
    if m:
        y, month, day = map(int, m.groups())
        # Reject malformed dates; do not promote invalid metadata to "today".
        try:
            from datetime import date
            return date(y, month, day).isoformat()
        except ValueError:
            return None
    normalized = re.sub(r"\s+", "", text or "")
    if re.search(r"(?:刚刚|今天|今日|分钟前)", normalized):
        return today
    # "几小时前" might cross midnight, so it is intentionally ambiguous.
    return None


def _query(href: str) -> tuple[str, dict[str, list[str]]]:
    url = urlsplit(html_lib.unescape(href or ""))
    return url.path.lower(), parse_qs(url.query)


def parse_boxes(html: str) -> dict[int, str]:
    """Parse both option selectors and custom mailbox navigation links."""
    soup = BeautifulSoup(html or "", "html.parser")
    boxes: dict[int, str] = {}
    for node in soup.select("option[value]"):
        try:
            number = int(node.get("value", ""))
        except (TypeError, ValueError):
            continue
        name = node.get_text(" ", strip=True)
        if number >= 2 and name:
            boxes[number] = name
    # NexusPHP renders custom mailboxes in #pmboxmenu even when empty.
    for node in soup.select("#pmboxmenu a[href]"):
        path, params = _query(node.get("href", ""))
        if path.endswith("messages.php") and params.get("box"):
            try:
                number = int(params["box"][0])
            except (TypeError, ValueError):
                continue
            name = node.get_text(" ", strip=True)
            if number >= 2 and name:
                boxes[number] = name
    return boxes


def parse_mailbox(html: str, *, box: int, page: int, today: str) -> InboxPage:
    """Parse rows of the PM listing; IDs are stable across archives.

    NexusPHP's inbox table has five cells: status, subject link, sender,
    sent/received date, and selection checkbox. Listing dates, rather than
    local bet time or lottery draw time, determine today's PM award count.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    entries: list[InboxEntry] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        path, args = _query(link.get("href", ""))
        if not path.endswith("messages.php") or args.get("action") != ["viewmessage"]:
            continue
        # NexusPHP wraps the listing in layout tables. An ancestor layout row
        # also contains the first link, but has no reception-date cell.
        tr = link.find_parent("tr")
        if tr is None:
            continue
        msg_id = (args.get("id") or [""])[0]
        if not msg_id.isdigit() or msg_id in seen:
            continue
        cells = tr.find_all("td", recursive=False)
        # An incomplete row cannot supply the trusted reception date.
        date_cell = cells[3] if len(cells) >= 4 else None
        date_text = date_cell.get_text(" ", strip=True) if date_cell else ""
        # Relative display text often keeps the absolute reception time in
        # a tooltip. Only inspect metadata inside the date cell.
        date_metadata = " ".join(
            str(node.get(attr) or "")
            for node in ([date_cell] + date_cell.find_all(True) if date_cell else [])
            for attr in ("title", "datetime")
        )
        entries.append(InboxEntry(
            mid=msg_id,
            day=_day(date_metadata, today) or _day(date_text, today),
            subject=link.get_text(" ", strip=True),
        ))
        seen.add(msg_id)

    has_next = False
    for a in soup.select("a[href]"):
        path, args = _query(a.get("href", ""))
        if not path.endswith("messages.php") or (args.get("action") or [""])[0] != "viewmailbox":
            continue
        try:
            link_box = int((args.get("box") or ["1"])[0])
            link_page = int((args.get("page") or ["-1"])[0])
        except (ValueError, TypeError):
            continue
        if link_box == box and link_page == page + 1:
            has_next = True
            break

    # A 200 OK login/error page must not be misread as an empty mailbox.
    lower = soup.get_text(" ", strip=True).lower()
    empty_hint = any(x in lower for x in (
        "没有消息", "没有短讯", "没有任何短讯", "暂无消息", "暂无短讯",
        "no messages", "no private message",
    ))
    # A navigation bar may remain visible on an HTML error page. It does NOT
    # prove that the message list was successfully loaded and is empty.
    valid = bool(entries or empty_hint)
    return InboxPage(tuple(entries), has_next, valid)


def parse_award_message(html: str, *, today: str) -> tuple[str | None, bool]:
    """Read an award PM, with date from the detail's header (not site footer).

    Caller must retain the date from its mailbox list if this detail has no
    reliable date. An award is one PM whose text explicitly names the actual
    "观影随机续期奖励" rating reason, never merely mentions a lottery.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    # Subject alone is insufficient; require the explicit reward in PM body.
    is_reward = REWARD_TEXT in text and not re.search(
        r"(?:未获得|没有获得|未中奖|未获得过)\s*.{0,20}" + REWARD_TEXT,
        text,
    )
    detail_day = None
    for tr in soup.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        if re.search(r"(?:日期|时间|date|sent|发送于|收到于)", label, re.I):
            detail_day = _day(cells[1].get_text(" ", strip=True), today)
            if detail_day:
                break
    return detail_day, is_reward


def parse_helper_reward_count(html: str) -> int:
    """Extract the authenticated helper dashboard's explicit daily reward count.

    Keep failure messages diagnostic but never include cookies, request headers,
    full page contents, usernames, or other account details.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    lower = text.lower()

    if not text:
        raise TicketInboxError("Emby 订阅 Cookie 检查失败：辅助页面返回空内容")

    if (
        re.search(r"(?:登录|login|sign.?in)", title, re.I)
        or re.search(r"(?:请先登录|请登录|登录后继续|账号登录|sign in to continue)", text, re.I)
        or soup.select_one('input[type="password"]')
    ):
        raise TicketInboxError("Emby 订阅 Cookie 未通过认证或已过期；请重新复制登录后的 Cookie")

    patterns = (
        r"今日\s*随机奖励\s*[:：]?\s*(\d+)",
        r"今日\s*随机奖励.{0,20}?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))

    if any(word in lower for word in ("internal server error", "bad gateway", "服务暂不可用")):
        raise TicketInboxError("Emby 订阅页面返回服务错误")

    # Browser-visible helper dashboard has these stable account/dashboard labels.
    # Their absence usually means the request got an app shell, an expired session,
    # or an unexpected page rather than the authenticated dashboard.
    has_account_marker = "主站用户" in text or re.search(r"\bUID\s*\d+", text, re.I) is not None
    has_emby_marker = "Emby 订阅" in text
    if not (has_account_marker and has_emby_marker):
        raise TicketInboxError(
            "未识别到已登录的 Emby 订阅页面；Cookie 可能不完整、已过期，"
            f"或请求返回了不同页面（诊断：账号标记={int(has_account_marker)}，"
            f"订阅标记={int(has_emby_marker)}，页面字符数={len(text)}，标题是否存在={int(bool(title))}）"
        )

    raise TicketInboxError(
        "已识别到 Emby 订阅页面，但页面中没有可读取的“今日随机奖励”数字；"
        f"可能是页面结构变化（诊断：奖励标签={int('今日随机奖励' in text)}，页面字符数={len(text)}）"
    )


def parse_helper_reward_response(payload) -> int:
    """Validate the helper API JSON and return its explicit daily reward count."""
    if not isinstance(payload, dict):
        raise TicketInboxError("辅助站 API 返回格式无效")
    if payload.get("success") is not True:
        # Do not echo arbitrary server text that could contain account details.
        message = str(payload.get("message") or "").lower()
        if "登录" in message or "过期" in message or "unauth" in message or "login" in message:
            raise TicketInboxError("Emby 订阅 Token 无效或已过期，请重新登录后获取 accessToken")
        raise TicketInboxError("辅助站 API 未返回成功状态")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TicketInboxError("辅助站 API 缺少奖励数据")
    value = data.get("todayRandomRewardCount")
    if isinstance(value, bool):
        raise TicketInboxError("辅助站 API 的今日奖励计数格式无效")
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise TicketInboxError("辅助站 API 未返回今日随机奖励计数") from None
    if count < 0:
        raise TicketInboxError("辅助站 API 返回了负数奖励计数")
    return count

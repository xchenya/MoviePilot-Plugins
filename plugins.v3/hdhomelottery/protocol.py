"""HDHome 2026 anniversary event."""
import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html

HOME = "https://hdhome.org/lottery.php?hd=202611"
TZ = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 11, 24, 20, tzinfo=TZ).timestamp()
END = datetime(2026, 11, 26, tzinfo=TZ).timestamp()
COST = 10000
PRIZES = {"67": "永久VIP会员", "71": "10TB上传", "70": "100TB上传", "61": "永久保号卡",
          "62": "1年期VIP会员", "63": "TTG 邀请码", "64": "邀请卡", "65": "复活卡",
          "69": "救命卡", "72": "CHD 邀请码"}


def cooldown(now):
    if now < START + 1200:
        return 120
    return 60 if now < START + 3600 else 30


def inspect_page(markup, target):
    doc = html.fromstring(markup)
    visible = " ".join(doc.xpath("//body//text()[not(ancestor::script or ancestor::style)]"))
    if not doc.xpath('//a[contains(@href,"logout.php")]'):
        raise ValueError("无法确认登录，请检查 MP 站点 Cookie")
    balance = re.search(r"魔力值\s*\[\s*使用\s*\]\s*[:：]\s*([\d,]+(?:\.\d+)?)", visible)
    if not balance or "2026年站庆活动抽奖" not in visible:
        raise ValueError("无法识别本期活动或魔力余额")
    for row in doc.xpath("//tr"):
        cells = row.xpath("./td")
        if len(cells) != 9 or cells[0].text_content().strip() != target:
            continue
        if PRIZES[target] not in cells[1].text_content():
            raise ValueError("奖品名称已变更")
        stock = cells[6].text_content().strip()
        if not stock.isdecimal() or int(stock) < 1:
            raise ValueError("目标奖品已抽完或库存未知")
        for a in cells[-1].xpath('.//a[@href]'):
            if a.text_content().strip() != "点击抽奖":
                continue
            url = urljoin(HOME, a.get("href"))
            parts = urlsplit(url)
            q = parse_qs(parts.query)
            if (parts.scheme == "https" and parts.netloc == "hdhome.org"
                    and parts.path == "/lottery.php" and q.get("cz") == ["lottery"]
                    and q.get("id") == [target] and q.get("hd") == ["202611"]
                    and len(q.get("key", [])) == 1):
                return float(balance[1].replace(",", "")), url
        break
    raise ValueError("该奖品当前没有可参与入口，请核对库存和参与资格")


def receipt(markup):
    doc = html.fromstring(markup)
    # Limit matching to individual response messages, never the event rules or records.
    for block in doc.xpath("//td[not(.//td)]|//p|//div[not(.//div or .//table)]|//h2"):
        message = "".join(block.itertext()).strip()
        if len(message) > 220 or "中奖码" in message or "活动规则" in message:
            continue
        if re.search(r"(?:您|你|本次|此次|很遗憾|很可惜|抱歉).{0,40}(?:未中奖|没有中奖|未能中奖|未抽中)|^(?:未中奖|未抽中)[！!。]?$", message):
            return "未中奖"
        if re.search(r"恭喜.{0,18}(?:抽中|获得|中奖)", message):
            return "已中奖"
    return "结果待核对"

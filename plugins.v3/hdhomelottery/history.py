"""Read confirmed draws from the account's HDHome event history."""
import re
from collections import Counter
from datetime import datetime

from lxml import html

HISTORY_URL = "https://hdhome.org/lottery.php?action=record&user=my&hd=202611"
COLUMNS = ("序号", "物品名称", "用户", "消耗魔力", "抽奖码", "是否中奖", "抽奖时间", "领取/使用状态", "操作")
SUMMARY = re.compile(r"累计抽奖\s*[:：]\s*([\d,]+)\s*次\s*[,，]\s*出奖\s*[:：]\s*([\d,]+)\s*次")


def parse_history(markup):
    doc = html.fromstring(markup)
    if not doc.xpath('//a[contains(@href,"logout.php")]'):
        raise ValueError("无法确认登录，请检查 MP 站点 Cookie")
    for row in doc.xpath("//tr"):
        headings = tuple(cell.text_content().strip() for cell in row.xpath("./td|./th"))
        if headings == COLUMNS:
            break
    else:
        raise ValueError("无法识别本期个人抽奖记录表")
    records = {}
    summary = None
    for entry in row.itersiblings("tr"):
        cells = [cell.text_content().strip() for cell in entry.xpath("./td")]
        if len(cells) == 1:
            summary = SUMMARY.search(cells[0]) or summary
            continue
        if len(cells) != len(COLUMNS):
            continue
        record_id, prize, _, cost, code, won, played, claim, _ = cells
        if not record_id.isdecimal() or not cost.replace(",", "").isdecimal() or won not in ("是", "否"):
            raise ValueError("站点抽奖记录格式已变更")
        timestamp = datetime.strptime(played, "%Y-%m-%d %H:%M:%S").isoformat(sep=" ")
        records[record_id] = dict(prize=prize, cost=int(cost.replace(",", "")), code=code,
                                  won=won == "是", time=timestamp, claim=claim)
    rows = sorted(records.values(), key=lambda item: item["time"], reverse=True)
    observed_wins = sum(item["won"] for item in rows)
    total, wins = (map(lambda value: int(value.replace(",", "")), summary.groups())
                   if summary else (len(rows), observed_wins))
    if total < len(rows) or not observed_wins <= wins <= total:
        raise ValueError("记录明细与站点统计不一致")
    return dict(rows=rows, total=total, wins=wins, spent=sum(item["cost"] for item in rows),
                prizes=Counter(item["prize"] for item in rows if item["won"]))

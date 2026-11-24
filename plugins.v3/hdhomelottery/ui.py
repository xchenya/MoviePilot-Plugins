"""MoviePilot native details page for the anniversary lottery."""
from html import escape

from .history import HISTORY_URL


def node(name, text=None, children=None, **props):
    result = {"component": name}
    if text is not None:
        result["text"] = escape(str(text))
    if children is not None:
        result["content"] = children
    if props:
        result["props"] = props
    return result


def card(title, *body):
    return node("VCard", children=[
        node("VCardTitle", title), node("VCardText", children=list(body)),
    ], variant="outlined", **{"class": "mb-3"})


def table(headers, rows):
    return node("VTable", density="compact", children=[
        node("thead", children=[node("tr", children=[node("th", label) for label in headers])]),
        node("tbody", children=[node("tr", children=[node("td", value) for value in row]) for row in rows]),
    ])


def history_table(rows):
    return table(("抽奖时间", "奖品", "抽奖码", "消耗魔力", "结果", "领取状态"), [
        (item["time"], item["prize"], item["code"], f"{item['cost']:,}",
         "中奖" if item["won"] else "未中奖", item["claim"] or "—") for item in rows
    ])


def page(status, progress, last, manual, history, synced_at, error):
    nodes = [
        node("VAlert", status, type="info", variant="tonal", **{"class": "mb-3"}),
        card("插件运行", node("div", f"本插件已提交 {progress} 次"),
             node("div", f"最近结果：{last or '尚无结果'}"),
             node("div", f"最近手动运行：{manual or '尚未运行'}")),
    ]
    source = node("VBtn", "查看站内原始记录", href=HISTORY_URL, target="_blank", rel="noopener noreferrer",
                  variant="text")
    if error:
        nodes.append(node("VAlert", error, type="warning", variant="tonal", **{"class": "mb-3"}))
    if history is None:
        return nodes + [card("本期抽奖记录", source)]
    rows, total, wins = history["rows"], history["total"], history["wins"]
    rate = f"{wins / total:.2%}" if total else "—"
    spent_label = "消耗魔力" if len(rows) == total else "已读取明细消耗"
    metrics = [("站内抽奖", f"{total:,} 次"), ("中奖", f"{wins:,} 次"),
               ("实际中奖率", rate), (spent_label, f"{history['spent']:,}")]
    nodes.append(node("VRow", children=[
        node("VCol", children=[card(label, node("div", value, **{"class": "text-h6"}))],
             cols=6, md=3) for label, value in metrics
    ]))
    if history["prizes"]:
        nodes.append(card("中奖奖品", table(("奖品", "中奖次数"), history["prizes"].most_common())))
    details = [node("div", f"站点读取时间 {synced_at}（北京时间） · 已读取 {len(rows):,} 条明细",
                    **{"class": "text-caption mb-2"}), source]
    if rows:
        details.append(history_table(rows[:25]))
        if len(rows) > 25:
            details.append(node("VExpansionPanels", variant="accordion", children=[
                node("VExpansionPanel", children=[
                    node("VExpansionPanelTitle", f"第 {offset + 1}–{min(offset + 25, len(rows))} 条"),
                    node("VExpansionPanelText", children=[history_table(rows[offset:offset + 25])]),
                ]) for offset in range(25, len(rows), 25)
            ]))
    else:
        details.append(node("div", "当前没有抽奖明细"))
    return nodes + [card("本期抽奖记录", *details)]

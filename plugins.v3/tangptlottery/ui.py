"""Native MP configuration and cached, account-isolated daily statistics."""
from html import escape


def component(name, text=None, content=None, **props):
    """Escape text for hosts whose native component renderer accepts HTML."""
    node = {"component": name}
    if props:
        node["props"] = props
    if text is not None:
        node["text"] = escape(str(text))
    if content is not None:
        node["content"] = content
    return node


def row(fields, width=6):
    """Collapse form fields and metrics into one column on small screens."""
    return component("VRow", content=[component("VCol", content=[field], cols=12, md=width,
                                                **{"class": "pa-2", "style": "min-width: 0"}) for field in fields],
                     **{"no-gutters": True, "class": "ma-0"})


def card(title, children):
    """Use MP's native theme and spacing."""
    return component("VCard", content=[
        component("VCardTitle", title, **{"class": "text-subtitle-1 font-weight-bold px-5 pt-4 pb-2 text-wrap"}),
        component("VCardText", content=children, **{"class": "pa-3"}),
    ], variant="outlined", **{"class": "mb-4"})


def form():
    """Expose one-shot operations and a native Cron picker, with no second save."""
    def field(model, label, **props):
        return component("VTextField", model=model, label=label, variant="outlined", density="comfortable",
                         **{"hide-details": "auto", **props})

    def switch(model, label, hint):
        return component("div", content=[
            component("VSwitch", model=model, label=label, color="primary", inset=True,
                      **{"hide-details": True, "density": "comfortable"}),
            component("div", hint, **{"class": "text-caption text-medium-emphasis mt-1",
                                      "style": "white-space: normal; line-height: 1.6"}),
        ])

    def note(text):
        return row([component("div", text, **{"class": "text-body-2 text-medium-emphasis",
                                              "style": "line-height: 1.7"})], 12)

    return [component("VForm", content=[
        card("站点连接", [
            note("默认读取 MP 站点管理的 Cookie 与 User-Agent。也可填写其他正常运行插件所用的同一组凭据，手动填写优先。"),
            row([field("cookie", "手动 Cookie（可选）", type="password", autocomplete="off", clearable=True,
                       placeholder="留空时自动读取站点管理")], 12),
            row([field("user_agent", "User-Agent（可选）", autocomplete="off", clearable=True,
                       placeholder="留空时使用站点设置或内置浏览器 UA")], 12),
            row([switch("use_proxy", "使用系统代理", "使用 MP 配置的代理；默认直连。"),
                 switch("diagnose_only", "仅检查连接", "保存后检查一次，不抽奖；开关自动复位。")]),
        ]),
        card("定时与通知", [
            row([switch("enabled", "启用每日定时", "后台自动执行，无需打开插件页面"),
                 switch("notify", "发送结果通知", "每轮一次汇总，使用 MP 插件通知渠道")]),
            row([component("VCronField", model="cron", label="执行时间（北京时间）")], 12),
            note("默认每天 08:00。也可设为 0 8,18 * * *，每天 08:00 和 18:00 执行，共用当日目标。"),
        ]),
        card("抽奖策略", [
            row([field("daily_target", "每日目标（抽）", type="number", min=1, max=1000),
                 component("VSelect", model="batch", label="每批优先抽数", variant="outlined", density="comfortable",
                           **{"hide-details": "auto"}, items=[
                     {"title": f"{count} 抽", "value": count} for count in (1, 10, 20, 50, 100)])]),
            row([field("reserve", "最低保留魔力", type="number", min=0),
                 field("max_cost", "单抽费用上限", type="number", min=1)]),
            row([field("interval", "批次间隔（秒）", type="number", min=5, max=900)]),
            note("默认每日 10 抽、每批 10 抽、间隔 30 秒。按实际单抽费用扣款前核对保留魔力，额度不足时自动使用较小档位。"),
            note("每日目标按北京时间统计本插件的提交次数，并受站点剩余次数限制。请避免同一账号同时运行多个抽奖插件。"),
        ]),
        card("手动运行与恢复", [
            row([switch("run_once", "保存后运行一次", "自动复位，遵守当日目标；同时勾选连接检查时只检查。")], 12),
            row([switch("acknowledge_pending", "已核对结果，解除暂停", "用于超时等结果不明的请求。请先到站点核对结果；本次只解除暂停，原请求仍占用当日目标。")], 12),
        ]),
    ])]


def prize_table(prizes):
    """Keep prize contents and compensation distinct instead of guessing values."""
    entries = sorted(prizes.items(), key=lambda item: (-item[1], item[0]))
    return component("VTable", density="compact", content=[
        component("thead", content=[component("tr", content=[component("th", "奖品 / 实际结果"), component("th", "次数")])]),
        component("tbody", content=[component("tr", content=[component("td", label), component("td", count)])
                                    for label, count in entries] or [
            component("tr", content=[component("td", "暂无已确认奖品", colspan=2)])]),
    ])


def page(state, today, error=""):
    """Render local records only; yesterday's quota never appears as today's."""
    uid = state.get("active_uid")
    ledger = {key.rsplit(":", 1)[1]: value for key, value in (state.get("days") or {}).items()
              if uid and key.rsplit(":", 1)[0] == uid}
    daily, last = ledger.get(today, {}), state.get("last") or {}
    snap = state.get("snapshot") or {}
    if snap.get("uid") != uid or snap.get("day") != today:
        snap = {}
    pending = state.get("pending")
    message = error or (f"{last.get('time', '').replace('T', ' ')} · {last.get('status', '')}：{last.get('message', '')}"
                        if last else "尚未执行，请先运行一次连接检查。")
    nodes = [component("VAlert", type="warning" if error or pending or last.get("status") == "异常停止" else "info",
                       variant="tonal", text=message, **{"class": "mb-3"})]
    if pending:
        nodes.append(component("VAlert", type="warning", variant="tonal",
                               text=f"{pending.get('day', '')} 有 {pending.get('count', '?')} 抽待核对，自动抽奖已暂停。请在站点核对后使用配置中的解除暂停开关。",
                               **{"class": "mb-3"}))
    nodes.append(card(f"每日统计 · {today}", [
        component("div", "按北京时间累计本插件已确认的抽奖结果；网页手动抽奖与过去的站点记录不补录。"),
        component("div", f"今日目标已占用 {daily.get('attempted', 0):g} 次（包含未确认请求），已确认 {daily.get('draws', 0):g} 次。",
                  **{"class": "text-caption mt-2"}),
    ]))
    metrics = [("今日抽奖", f"{daily.get('draws', 0):g} 次"),
               ("今日消耗魔力", f"{daily.get('spent', 0):,.0f}"),
               ("今日余额变化", f"{daily.get('change', 0):+,.1f}"),
               ("站点剩余次数（最近读取）", f"约 {snap['remaining']} 次" if snap else "待检查")]
    nodes.append(row([card(label, [component("div", value, **{"class": "text-h6"})]) for label, value in metrics], 3))
    nodes.append(card("今日奖品统计", [prize_table(daily.get("prizes") or {}),
        component("div", f"已确认折算奖励 {daily.get('compensated', 0):,.0f} 魔力。余额变化为每批扣费前后余额差，可能包含期间做种收益。",
                  **{"class": "text-caption mt-2"})]))
    panels = [component("VExpansionPanel", content=[
        component("VExpansionPanelTitle", f"{day} · {value.get('draws', 0):g} 抽"),
        component("VExpansionPanelText", content=[
            component("div", f"目标占用 {value.get('attempted', 0):g} 次 · 消耗 {value.get('spent', 0):,.0f} 魔力 · 余额变化 {value.get('change', 0):+,.1f}"),
            prize_table(value.get("prizes") or {}),
        ]),
    ]) for day, value in sorted(ledger.items(), reverse=True) if day < today]
    nodes.append(card("历史每日统计", [component("VExpansionPanels", content=panels, variant="accordion")]
                      if panels else [component("div", "暂无历史每日记录")]))
    history = [item for item in state.get("history", []) if item.get("uid") == uid][-15:]
    nodes.append(card("最近执行记录", [component("VTable", density="compact", content=[
        component("thead", content=[component("tr", content=[component("th", value) for value in ["执行时间", "状态", "抽数", "说明"]])]),
        component("tbody", content=[component("tr", content=[component("td", value) for value in [
            item.get("time", "").replace("T", " "), item.get("status", ""), item.get("draws", 0), item.get("message", ""),
        ]]) for item in reversed(history)]),
    ])]))
    return nodes

"""Native MoviePilot Vuetify configuration and cached result pages."""


def component(name, text=None, content=None, **props):
    """Build a native component without HTML injection or global styles."""
    node = {"component": name}
    if props:
        node["props"] = props
    if text is not None:
        node["text"] = str(text)
    if content is not None:
        node["content"] = content
    return node


def row(fields, width=6):
    """Responsive two-column forms collapse naturally on mobile."""
    return component("VRow", content=[component("VCol", content=[field], cols=12, md=width) for field in fields])


def card(title, children):
    """Compact native card, using the host theme."""
    return component("VCard", content=[component("VCardTitle", title),
                                      component("VCardText", content=children)], **{"class": "mb-3", "variant": "outlined"})


def form():
    """No separate save button: MP supplies the single save action."""
    def field(model, label, **props):
        return component("VTextField", model=model, label=label, **props)

    def switch(model, label, hint):
        return component("VSwitch", model=model, label=label, color="primary", hint=hint, **{"persistent-hint": True})

    return [component("VForm", content=[
        card("运行设置", [
            row([switch("enabled", "启用每日定时", "开启后按 Cron 执行"),
                 switch("notify", "发送结果通知", "每轮汇总一次，使用 MP 的插件通知渠道")]),
            row([switch("run_once", "保存后运行一次", "开关自动复位；未开启每日定时也可运行"),
                 switch("diagnose_only", "仅检查连接", "只读取账号、余额和次数，不抽奖")]),
            row([component("VCronField", model="cron", label="执行时间（Cron）"),
                 field("timezone", "执行时区", placeholder="Asia/Shanghai")]),
            component("VAlert", type="info", variant="tonal", text="默认北京时间每天 08:05。站点每日 00:00 UTC（北京时间 08:00）重置；支持多次定时，例如 5 8,12,18 * * *，达到每日目标后不会重复抽奖。"),
        ]),
        card("抽奖策略", [
            row([field("daily_target", "每日目标（实际抽奖次数）", type="number", min=1, max=500),
                 component("VSelect", model="batch", label="优先连抽数量", items=[
                     {"title": "单抽", "value": 1}, {"title": "三连抽", "value": 3},
                     {"title": "十连抽", "value": 10}])]),
            row([field("reserve", "最低保留工分", type="number", min=0),
                 field("interval", "每批间隔（秒）", type="number", min=3, max=900)]),
            row([field("retries", "异常重试次数", type="number", min=0, max=5),
                 switch("use_proxy", "使用 MP 系统代理", "Cookie 和 User-Agent 从站点管理读取")]),
            component("VAlert", type="info", variant="tonal", text="默认目标 50 抽、十连抽、间隔 35 秒，保留 10,000 工分。网页手动抽过的次数计入每日目标。尾数、余额或站点配额不足十连时自动使用三连/单抽；请勿与油猴或其他插件同时运行。"),
        ]),
        card("连接与异常恢复", [
            component("VAlert", type="info", variant="tonal", text="在 MP 站点管理添加 https://ptlgs.org 并填写有效 Cookie；无需在本插件重复填写凭据。建议首次打开“仅检查连接”与“保存后运行一次”，确认正常后关闭“仅检查连接”。"),
            switch("acknowledge_pending", "已核对站点，清除待确认订单", "仅用于超过 15 分钟或跨日仍未确认的订单。先到站点核对抽奖记录，再勾选保存；本次只清除标记，不抽奖，也不清除每日计数。"),
        ]),
    ])]


def page(state, error=""):
    """Show recent results, prize counts and history without a site request."""
    last = state.get("last") or {}
    pending = state.get("pending")
    message = error or last.get("message") or "尚未执行，请先配置站点并运行一次连接检查。"
    nodes = [component("VAlert", type="warning" if error or pending or last.get("status") == "异常停止" else "info",
                       variant="tonal", text=message, **{"class": "mb-3"})]
    if pending:
        nodes.append(component("VAlert", type="warning", variant="tonal", text=f"待确认订单：{pending.get('count', '?')} 抽。优先重试原订单；超过 15 分钟或跨日后需人工核对。", **{"class": "mb-3"}))
    metrics = [("最近状态", last.get("status", "未运行")), ("本次抽奖", str(last.get("draws", 0)) + " 抽"),
               ("当前工分", f"{last['balance']:,.1f}" if last.get("balance") is not None else "—"),
               ("今日剩余", str(last.get("remaining")) if last.get("remaining") is not None else "—")]
    nodes.append(row([card(label, [component("div", value, **{"class": "text-h6"})]) for label, value in metrics], 3))
    prizes = sorted((last.get("prizes") or {}).items(), key=lambda pair: -pair[1])
    nodes.append(card("本次奖品", [component("VTable", content=[component("tbody", content=[
        component("tr", content=[component("td", label), component("td", count)]) for label, count in prizes
    ] or [component("tr", content=[component("td", "暂无奖品记录")])])])]))
    history = list(reversed(state.get("history", [])[-15:]))
    nodes.append(card("最近执行记录", [component("VTable", density="compact", content=[
        component("thead", content=[component("tr", content=[component("th", value) for value in
                                                               ["执行时间", "状态", "抽数", "消耗工分", "工分变化"]])]),
        component("tbody", content=[component("tr", content=[component("td", value) for value in [
            item.get("time", "").replace("T", " "), item.get("status", ""), item.get("draws", 0),
            f"{item.get('spent', 0):,.0f}", f"{item.get('change', 0):+,.1f}",
        ]]) for item in history]),
    ]), component("div", "工分变化为每笔订单扣费前后余额差，可能包含期间做种收入；奖品按站点实际名称统计，不按名称估算返还工分。", **{"class": "text-caption mt-2"})]))
    return nodes

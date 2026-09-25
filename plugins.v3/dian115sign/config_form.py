"""Dian115Sign compact Vuetify JSON configuration form."""
from __future__ import annotations

from typing import Any


def build_form() -> tuple[list[dict], dict[str, Any]]:
    """Keep everyday settings compact; retain advanced recovery controls."""

    def card(icon: str, color: str, title: str, rows: list[dict]) -> dict:
        return {
            "component": "VCard",
            "props": {"class": "mt-3", "variant": "tonal"},
            "content": [
                {"component": "VCardTitle", "props": {"class": "d-flex align-center"}, "content": [
                    {"component": "VIcon", "props": {"color": color, "class": "mr-2"}, "text": icon},
                    {"component": "span", "text": title},
                ]},
                {"component": "VDivider"},
                {"component": "VCardText", "content": rows},
            ],
        }

    def row(items: list[dict]) -> dict:
        return {"component": "VRow", "content": items}

    def col(md: int, component: dict) -> dict:
        return {"component": "VCol", "props": {"cols": 12, "md": md}, "content": [component]}

    def props(model: str, label: str, **kwargs: Any) -> dict:
        value = {"model": model, "label": label}
        for key, item in kwargs.items():
            value[key.replace("_", "-")] = item
        return value

    def text(model: str, label: str, **kwargs: Any) -> dict:
        return {"component": "VTextField", "props": props(model, label, **kwargs)}

    def switch(model: str, label: str, color: str = "primary", **kwargs: Any) -> dict:
        value = props(model, label, **kwargs)
        value["color"] = color
        return {"component": "VSwitch", "props": value}

    form = [{
        "component": "VForm",
        "content": [
            card("mdi-account-key", "primary", "账号与基础设置", [
                row([
                    col(6, switch("enabled", "启用定时签到", "primary",
                                  hint="开启后按下方 Cron 自动执行", persistent_hint=True)),
                    col(6, switch("notify", "签到结果通知", "success",
                                  hint="成功、已签到或失败时发送通知", persistent_hint=True)),
                ]),
                row([
                    col(6, text("email", "登录邮箱", placeholder="you@example.com",
                                hint="可以只使用邮箱 + 密码，不要求 Token/Cookie",
                                persistent_hint=True, clearable=True)),
                    col(6, text("password", "登录密码", type="password",
                                hint="仅保存在 MoviePilot 插件配置中",
                                persistent_hint=True, clearable=True)),
                ]),
                row([
                    col(12, text("token", "登录 Token（可选）", type="password",
                                 placeholder="有邮箱密码时可留空",
                                 hint="仅用于复用已有登录态；无效旧 Token 不再阻止邮箱密码登录",
                                 persistent_hint=True, clearable=True)),
                ]),
            ]),
            card("mdi-calendar-check", "success", "签到设置", [
                row([
                    col(4, switch("lucky_mode", "运气签模式", "warning",
                                  hint="关闭为普通签；运气签存在扣分可能",
                                  persistent_hint=True)),
                    col(4, switch("diagnose_only", "仅诊断", "info",
                                  hint="只验证登录与账号读取，不提交签到",
                                  persistent_hint=True)),
                    col(4, text("cron", "定时表达式", placeholder="30 9 * * *",
                                hint="默认每天 09:30", persistent_hint=True)),
                ]),
            ]),
            card("mdi-earth", "info", "网络设置", [
                row([
                    col(4, switch("use_system_proxy", "使用系统代理", "info",
                                  hint="使用 MoviePilot 中配置的代理",
                                  persistent_hint=True)),
                    col(8, text("proxy", "自定义代理（可选）",
                                placeholder="http://10.0.0.2:7890",
                                hint="关闭系统代理后生效", persistent_hint=True,
                                clearable=True)),
                ]),
            ]),
            card("mdi-flask-outline", "secondary", "测试与恢复", [
                row([
                    col(4, switch("onlyonce", "立即执行一次", "info",
                                  hint="保存后执行一次，随后自动复位",
                                  persistent_hint=True)),
                    col(4, switch("reset_session", "清除浏览器会话", "warning",
                                  hint="下次重新登录或使用配置中的 Token/Cookie",
                                  persistent_hint=True)),
                    col(4, switch("clear_pending", "清除待确认标记", "error",
                                  hint="仅在已人工核对网站签到状态后使用",
                                  persistent_hint=True)),
                ]),
            ]),
            card("mdi-tune-variant", "grey", "高级适配（通常无需修改）", [
                row([
                    col(12, text("cookie", "完整 Cookie（可选）", type="password",
                                 hint="仅在需要复用完整浏览器会话时填写；邮箱+密码可独立使用",
                                 persistent_hint=True, clearable=True)),
                ]),
                row([
                    col(6, text("timezone", "站点时区", placeholder="Asia/Shanghai")),
                    col(6, text("timeout", "页面超时（秒）", type="number",
                                hint="范围 10–60 秒", persistent_hint=True)),
                ]),
                row([
                    col(6, text("normal_selector", "普通签按钮 CSS 选择器")),
                    col(6, text("lucky_selector", "运气签按钮 CSS 选择器")),
                ]),
                row([
                    col(6, text("submit_selector", "最终提交按钮 CSS 选择器")),
                    col(6, text("login_selector", "登录按钮 CSS 选择器")),
                ]),
            ]),
            {"component": "VAlert", "props": {
                "type": "info", "variant": "tonal", "class": "mt-3",
                "text": "推荐直接填写邮箱和密码。Token/Cookie 都是可选项；如果旧配置残留无效值，"
                        "插件会忽略它并继续使用邮箱密码登录。首次建议开启“仅诊断”测试登录。",
            }},
        ],
    }]

    return form, {
        "enabled": False,
        "onlyonce": False,
        "diagnose_only": True,
        "email": "",
        "password": "",
        "token": "",
        "cookie": "",
        "lucky_mode": False,
        "cron": "30 9 * * *",
        "notify": False,
        "use_system_proxy": True,
        "proxy": "",
        "timezone": "Asia/Shanghai",
        "timeout": 30,
        "normal_selector": "",
        "lucky_selector": "",
        "submit_selector": "",
        "login_selector": "",
        "reset_session": False,
        "clear_pending": False,
    }

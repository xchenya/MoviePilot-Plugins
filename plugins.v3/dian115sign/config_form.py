"""Dian115Sign compact Vuetify JSON configuration form."""
from __future__ import annotations

from typing import Any


def build_form() -> tuple[list[dict], dict[str, Any]]:
    """Keep the UI close to the original plugin: three compact cards."""

    def card(icon: str, color: str, title: str, rows: list[dict]) -> dict:
        return {
            "component": "VCard",
            "props": {"class": "mt-3"},
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
            card("mdi-cog", "primary", "基础设置", [
                row([
                    col(4, switch("enabled", "启用插件", "primary",
                                  hint="开启后按定时计划自动签到", persistent_hint=True)),
                    col(4, switch("notify", "签到结果通知", "success",
                                  hint="成功、已签到或失败时发送通知", persistent_hint=True)),
                    col(4, switch("diagnose_only", "仅诊断", "info",
                                  hint="只检查登录与账号，不提交签到", persistent_hint=True)),
                ]),
                row([
                    col(6, text("email", "登录邮箱", placeholder="you@example.com",
                                hint="邮箱 + 密码可以独立登录", persistent_hint=True,
                                clearable=True)),
                    col(6, text("password", "登录密码", type="password",
                                hint="仅保存在 MoviePilot 插件配置中",
                                persistent_hint=True, clearable=True)),
                ]),
                row([
                    col(12, text(
                        "token", "Token / Cookie（可选）", type="password",
                        placeholder="纯 Token，或 portal_token=...; __Host-portal_browser=...",
                        hint="兼容纯 Token、单个 Cookie、完整 Cookie；填写后优先使用，失效时可回退邮箱密码登录",
                        persistent_hint=True, clearable=True
                    )),
                ]),
            ]),
            card("mdi-calendar-check", "success", "签到设置", [
                row([
                    col(4, switch("lucky_mode", "运气签模式", "warning",
                                  hint="关闭为普通签；运气签存在扣分可能",
                                  persistent_hint=True)),
                    col(4, text("cron", "定时表达式", placeholder="30 9 * * *",
                                hint="默认每天 09:30", persistent_hint=True)),
                    col(4, switch("use_system_proxy", "使用系统代理", "info",
                                  hint="使用 MoviePilot 系统代理", persistent_hint=True)),
                ]),
                row([
                    col(4, switch("retry_enabled", "失败自动重试", "warning",
                                  hint="仅对超时、网络等可恢复失败重试；403、密码错误、人机验证等不会重试",
                                  persistent_hint=True)),
                    col(4, text("retry_count", "重试次数", type="number",
                                hint="默认 1 次，最大 10 次", persistent_hint=True)),
                    col(4, text("retry_interval", "重试间隔（秒）", type="number",
                                hint="默认 60 秒", persistent_hint=True)),
                ]),
                row([
                    col(12, text("proxy", "自定义代理（可选）",
                                 placeholder="http://10.0.0.2:7890",
                                 hint="关闭系统代理后生效", persistent_hint=True,
                                 clearable=True)),
                ]),
            ]),
            card("mdi-bug", "info", "调试与恢复", [
                row([
                    col(3, switch("onlyonce", "立即运行一次", "info",
                                  hint="保存后执行一次并自动复位", persistent_hint=True)),
                    col(3, switch("force_once", "强制重新签到一次", "warning",
                                  hint="保存后立即访问站点并点击签到，忽略本地重复状态；随后自动复位",
                                  persistent_hint=True)),
                    col(3, switch("reset_session", "清除浏览器会话", "warning",
                                  hint="下次重新建立登录态", persistent_hint=True)),
                    col(3, switch("clear_pending", "清除待确认标记", "error",
                                  hint="仅在已人工确认网站签到状态后使用",
                                  persistent_hint=True)),
                ]),
            ]),
            {"component": "VAlert", "props": {
                "type": "info", "variant": "tonal", "class": "mt-3",
                "text": "推荐填写邮箱和密码；Token / Cookie 是可选加速项。"
                        "该字段可直接粘贴纯 Token，也可粘贴完整 Cookie。首次建议开启“仅诊断”。",
            }},
        ],
    }]

    # cookie/login_selector and other adaptation keys remain accepted internally
    # for backward compatibility but are intentionally not exposed in the normal UI.
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
        "force_once": False,
        "retry_enabled": False,
        "retry_count": 1,
        "retry_interval": 60,
    }

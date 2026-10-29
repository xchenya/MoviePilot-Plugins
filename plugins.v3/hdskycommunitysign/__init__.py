# SPDX-License-Identifier: GPL-3.0-only
"""HDSky 社区客户端签到：认证、宿主管理的定时服务与持久化回执。"""
import copy
import json
import math
import uuid
import re
import threading
import time
from datetime import date, datetime, timedelta
from http.client import HTTPException
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.sdk.plugin import _PluginBase
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.scheduler import update_plugin_job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
try:
    from app.schemas.types import MessageType
except ImportError:
    from app.schemas.types import NotificationType as MessageType

ORIGIN = "https://hdsky.supertimi.de:8443"
HOST = "hdsky.supertimi.de"
PATHS = {
    "send": "/api/portal/auth/start",
    "login": "/api/portal/auth/verify",
    "check": "/api/portal/session",
    "sign": "/api/portal/daily-checkin",
}
DEFAULT_UA = "HDSkyWindows/0.6.0-rc.1"  # 官方 Windows 0.8.27 的主 API UA
COOKIE_FIELDS = (
    "version", "name", "value", "port", "port_specified", "domain",
    "domain_specified", "domain_initial_dot", "path", "path_specified",
    "secure", "expires", "discard", "comment", "comment_url", "rfc2109",
)
SIGNED = {"success", "already", "confirmed"}


class PublicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    uid: str = ""
    use_proxy: bool = False
    user_agent: str = DEFAULT_UA
    auto_sign: bool = False
    notify: bool = True
    cron: str = "0 8 * * *"
    retry_count: int = Field(default=3, ge=0, le=10)
    retry_interval: int = Field(default=300, ge=60, le=86400)


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    uid: str | None = None
    use_proxy: bool | None = None
    user_agent: str | None = None
    code: str = Field(default="", max_length=6, repr=False)
    cookie: str = Field(default="", max_length=16384, repr=False)


class PublicAuth(BaseModel):
    uid: str = ""
    display_name: str = ""
    cookie_configured: bool = False
    verified: bool = False
    checked_at: float = 0
    pending_uid: str = ""
    send_after: float = 0
    verify_after: float = 0
    retry_after: float = 0
    balance: float | None = None
    balance_at: float = 0
    connection_status: str = "unknown"
    connection_at: float = 0


class RetryStatus(BaseModel):
    pending: bool = False
    used: int = 0
    limit: int = 0
    next_at: float = 0


class StatusMessage(BaseModel):
    success: bool = False
    message: str = ""
    at: float = 0


class DailyRecord(BaseModel):
    day: str
    uid: str
    status: str = "unrecorded"
    message: str = "尚无记录"
    time: float = 0
    amount: float | None = None
    balance: float | None = None


class DailyStatistics(BaseModel):
    uid: str = ""
    today: DailyRecord | None = None
    completed_days: int = 0
    reward_total: float = 0
    unknown_reward_days: int = 0
    days: list[DailyRecord] = Field(default_factory=list)


class PublicState(BaseModel):
    config: PublicConfig
    auth: PublicAuth
    status: StatusMessage
    statistics: DailyStatistics
    history: list[DailyRecord] = Field(default_factory=list)
    retry: RetryStatus = Field(default_factory=RetryStatus)


class ActionResult(BaseModel):
    success: bool
    message: str
    state: PublicState


class AuthError(Exception):
    def __init__(self, message, invalid=False, csrf=False, uncertain=False, retryable=False):
        super().__init__(message)
        self.invalid = invalid
        self.csrf = csrf
        self.uncertain = uncertain
        self.retryable = retryable


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Cookie 和验证码不得跟随重定向转发。
        return None


class HdskyCommunitySign(_PluginBase):
    plugin_name = "天空社区客户端签到"
    plugin_desc = "HDSky 社区客户端每日签到，支持直接登录、余额查询、Cookie 连通性检测及自定义签到重试。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.2.1"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya"
    plugin_config_prefix = "hdskycommunitysign_"
    plugin_order = 30
    auth_level = 2

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self._config = {}
        self._auth = {}
        self._status = {}
        self._runtime = {}
        self._trigger = None
        self._generation = 0
        self._stopped = False

    @staticmethod
    def _bool(value):
        return value is True or value == 1 or str(value).lower() in {"true", "on", "yes"}

    def init_plugin(self, config=None):
        with self._lock:
            values = config or {}
            self._stopped = False
            self._generation += 1
            self._config = {
                "enabled": self._bool(values.get("enabled", False)),
                "uid": str(values.get("uid") or "").strip(),
                "use_proxy": self._bool(values.get("use_proxy", False)),
                "user_agent": str(values.get("user_agent") or DEFAULT_UA).strip(),
                "action": "none", "cookie_input": "", "verify_code": "",
                "auto_sign": self._bool(values.get("auto_sign", False)),
                "notify": self._bool(values.get("notify", True)),
                "cron": str(values.get("cron") or "0 8 * * *").strip(),
                "retry_count": values.get("retry_count", 3),
                "retry_interval": values.get("retry_interval", 300),
            }
            self._auth = copy.deepcopy(self.get_data("auth") or {})
            self._status = copy.deepcopy(self.get_data("status") or {})
            self._runtime = copy.deepcopy(self.get_data("checkins") or {})
            self._backfill_daily()
            self._trigger = None
            action = str(values.get("action") or "none")
            cookie = str(values.get("cookie_input") or "").strip()
            code = str(values.get("verify_code") or "").strip()
            # 先落盘清除一次性操作与输入，即使超时/重启也不会自动重放。
            if self.update_config(dict(self._config)) is False:
                self._config["enabled"] = False
                self._record(False, "配置复位失败，未执行本次操作。")
                return
            try:
                retries = PublicConfig(retry_count=self._config["retry_count"],
                                       retry_interval=self._config["retry_interval"])
                self._config.update(retry_count=retries.retry_count, retry_interval=retries.retry_interval)
                self._trigger = CronTrigger.from_crontab(
                    self._config["cron"], timezone=getattr(settings, "TZ", "Asia/Shanghai"))
            except (ValueError, TypeError):
                self._record(False, "Cron 或重试设置无效，定时任务未启用；请检查配置。")
                # 避免无效旧配置使公开状态接口无法序列化。
                self._config.update(retry_count=3, retry_interval=300)
                return
            plan = self._runtime.get("sign_retry")
            account_uid = str((self._auth.get("account") or {}).get("uid") or "")
            if plan and (not self.get_state() or not self._config["retry_count"]
                         or (plan.get("uid"), plan.get("day")) != (account_uid, self._day())
                         or (self._config["uid"] and self._config["uid"] != account_uid)):
                self._runtime.pop("sign_retry", None)
                self._save_runtime()
            if action == "none" and not cookie and not code:
                return
            if not self.get_state():
                self._record(False, "请先启用插件；本次未发送任何请求。")
                return
            try:
                if action not in {"none", "send", "login", "check", "sign"}:
                    raise AuthError("未知操作，请重新选择。")
                if cookie and action in {"send", "login"}:
                    raise AuthError("手动 Cookie 与验证码登录请分开操作。")
                if code and action != "login":
                    raise AuthError("已填写验证码，请选择“提交验证码并登录”。")
                if cookie:
                    self._import_cookie(cookie)
                elif action == "send":
                    self._send_code()
                elif action == "login":
                    self._login(code)
                elif action == "check":
                    self._check_cookie()
                if action == "sign":
                    self.sign_in()
            except AuthError as exc:
                if exc.invalid:
                    self._auth["verified"] = False
                    self._runtime.pop("sign_retry", None)
                    self._save_runtime()
                    self._save_auth()
                self._record(False, str(exc))

    def get_state(self):
        return self._config.get("enabled", False) and not self._stopped

    def get_command(self):
        return []

    def get_service(self):
        if not self.get_state() or not self._trigger:
            return []
        from functools import partial
        services = []
        if self._config.get("auto_sign"):
            services.append({"id": self.__class__.__name__ + ".daily",
                 "name": "天空社区客户端签到", "trigger": self._trigger,
                 "func": partial(self.sign_in, generation=self._generation),
                 "kwargs": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 300}})
        if self._config.get("retry_count"):
            services.append({"id": self.__class__.__name__ + ".retry",
                 "name": "天空社区签到重试检查", "trigger": IntervalTrigger(seconds=30),
                 "func": partial(self.retry_sign_in, generation=self._generation),
                 "kwargs": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 60}})
        return services

    def get_api(self):
        definitions = [
            ("/state", "GET", self.api_state, PublicState, "读取登录状态与每日统计（不访问社区）"),
            ("/config", "POST", self.api_save_config, ActionResult, "保存签到设置"),
            ("/auth", "POST", self.api_auth, ActionResult, "发送验证码、登录或检查社区会话"),
            ("/sign", "POST", self.api_sign, ActionResult, "立即签到一次"),
        ]
        return [{"path": path, "methods": [method], "endpoint": endpoint,
                 "auth": "bear", "response_model": model, "summary": summary}
                for path, method, endpoint, model, summary in definitions]

    def get_render_mode(self):
        return "vue", f"dist/assets-v{self.plugin_version}"

    def api_state(self) -> PublicState:
        with self._lock:
            account = self._auth.get("account") or {}
            auth = PublicAuth(
                uid=account.get("uid", ""), display_name=account.get("display_name", ""),
                cookie_configured=bool(self._auth.get("cookies")),
                verified=bool(self._auth.get("verified")),
                checked_at=self._auth.get("checked_at") or 0,
                pending_uid=(self._auth.get("pending") or {}).get("uid", ""),
                send_after=self._auth.get("send_after") or 0,
                verify_after=self._auth.get("verify_after") or 0,
                retry_after=self._runtime.get("retry_after") or 0,
                balance=self._number(self._auth.get("balance")),
                balance_at=self._auth.get("balance_at") or 0,
                connection_status=self._auth.get("connection_status", "unknown"),
                connection_at=self._auth.get("connection_at") or 0,
            )
            # 只选取公开字段，凭据与一次性输入不进入 HTTP 响应。
            return PublicState(
                config=PublicConfig(**{key: self._config[key] for key in PublicConfig.model_fields
                                       if key in self._config}),
                auth=auth, status=StatusMessage(**self._status),
                statistics=self._statistics(auth.uid),
                history=[DailyRecord(**row) for row in self._runtime.get("history", [])[:30]],
                retry=self._retry_status(),
            )

    def _api_result(self, success, message):
        return ActionResult(success=success, message=message, state=self.api_state())

    @staticmethod
    def _validate_connection(config):
        uid = config.get("uid", "")
        if uid and not re.fullmatch(r"[1-9][0-9]{0,11}", uid):
            raise AuthError("请输入正确的 HDSky 数字 UID。")
        ua = config.get("user_agent", "")
        if not ua or len(ua) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in ua):
            raise AuthError("User-Agent 格式不正确。")

    def api_save_config(self, payload: PublicConfig) -> ActionResult:
        with self._lock:
            if self._stopped:
                return self._api_result(False, "插件正在停止，请刷新页面后再试。")
            config = {**self._config, **payload.model_dump(exclude_unset=True)}
            config.update(action="none", cookie_input="", verify_code="")
            for key in ("uid", "user_agent", "cron"):
                config[key] = str(config.get(key) or "").strip()
            config["user_agent"] = config["user_agent"] or DEFAULT_UA
            try:
                self._validate_connection(config)
                trigger = CronTrigger.from_crontab(
                    config["cron"], timezone=getattr(settings, "TZ", "Asia/Shanghai"))
            except AuthError as exc:
                return self._api_result(False, str(exc))
            except (ValueError, TypeError):
                return self._api_result(False, "Cron 无效，请使用五段 Cron 表达式。")
            if self.update_config(dict(config)) is False:
                return self._api_result(False, "配置保存失败，请稍后再试。")
            account_changed = config["uid"] != self._config.get("uid", "")
            interval_changed = config["retry_interval"] != self._config.get("retry_interval")
            self._config, self._trigger = config, trigger
            self._generation += 1
            if account_changed or not config["enabled"] or not config["retry_count"]:
                self._runtime.pop("sign_retry", None)
                self._save_runtime()
            elif interval_changed and self._retry_status().pending:
                self._runtime["sign_retry"]["next_at"] = max(
                    time.time() + config["retry_interval"], self._runtime.get("retry_after", 0))
                self._save_runtime()
        # 更新宿主注册的任务，不自建调度器；按当前运行实例定位分身。
        try:
            update_plugin_job(self.__class__.__name__)
        except Exception:
            return self._api_result(False, "设置已保存，但定时任务刷新失败，请在 MP 服务页检查或重启 MP。")
        return self._api_result(True, "签到设置已保存。")

    def api_auth(self, payload: AuthRequest) -> ActionResult:
        with self._lock:
            if self._stopped:
                return self._api_result(False, "插件正在停止，请刷新页面后再试。")
            try:
                if payload.action not in {"send", "login", "cookie", "check"}:
                    raise AuthError("未知登录操作。")
                if (payload.code and payload.action != "login"
                        or payload.cookie and payload.action != "cookie"):
                    raise AuthError("验证码与 Cookie 请分别提交。")
                config = dict(self._config)
                for key in ("uid", "use_proxy", "user_agent"):
                    value = getattr(payload, key)
                    if value is not None:
                        config[key] = value.strip() if isinstance(value, str) else value
                config["user_agent"] = config.get("user_agent") or DEFAULT_UA
                self._validate_connection(config)
                if payload.action in {"send", "login"} and not config.get("uid"):
                    raise AuthError("请输入 HDSky 数字 UID。")
                # 只应用本次登录的连接信息，不保存页面中尚未提交的调度设置。
                if self.update_config(dict(config)) is False:
                    raise AuthError("连接设置保存失败，未发送请求。")
                if config.get("uid") != self._config.get("uid"):
                    self._runtime.pop("sign_retry", None)
                    self._save_runtime()
                self._config = config
                if payload.action == "send":
                    self._send_code()
                elif payload.action == "login":
                    self._login(payload.code)
                elif payload.action == "cookie":
                    self._import_cookie(payload.cookie)
                else:
                    self._check_cookie()
            except AuthError as exc:
                if payload.action == "check":
                    self._auth.update(connection_status="invalid" if exc.invalid else "error",
                                      connection_at=time.time())
                    self._save_auth()
                if exc.invalid:
                    self._auth["verified"] = False
                    self._runtime.pop("sign_retry", None)
                    self._save_runtime()
                    self._save_auth()
                self._record(False, str(exc))
            return self._api_result(bool(self._status.get("success")), self._status.get("message", ""))

    def api_sign(self) -> ActionResult:
        row = self.sign_in()
        if row is None:
            return self._api_result(False, "请先启用插件并保存设置，再执行签到。")
        return self._api_result(row["status"] in SIGNED, row["message"])

    def stop_service(self):
        self._stopped = True  # 在途查询返回后、提交签到前可及时停止

    def _save_auth(self):
        self.save_data("auth", copy.deepcopy(self._auth))

    def _record(self, success, message):
        self._status = {"success": success, "message": message, "at": time.time()}
        self.save_data("status", dict(self._status))

    def _uid(self):
        uid = self._config.get("uid", "")
        if not re.fullmatch(r"[1-9][0-9]{0,11}", uid):
            raise AuthError("请输入正确的 HDSky 数字 UID。")
        return uid

    @staticmethod
    def _dump_cookies(jar):
        jar.clear_expired_cookies()
        rows = []
        for cookie in jar:
            row = {key: getattr(cookie, key) for key in COOKIE_FIELDS}
            row["rest"] = dict(cookie._rest)
            rows.append(row)
        return rows

    @staticmethod
    def _load_cookies(rows):
        jar = CookieJar()
        try:
            for row in rows or []:
                cookie = Cookie(**row)
                domain = cookie.domain.lstrip(".")
                if HOST != domain and not HOST.endswith("." + domain):
                    continue
                if not cookie.is_expired():
                    jar.set_cookie(cookie)
        except (TypeError, ValueError, KeyError, AttributeError):
            raise AuthError("已保存的 Cookie 数据无法读取，请重新登录或手动填写。") from None
        return jar

    @staticmethod
    def _parse_cookie(value):
        value = value.strip()
        if value.lower().startswith("cookie:"):
            value = value[7:].strip()
        if not value or len(value) > 16384 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise AuthError("请粘贴单行 Cookie 请求头，不要包含换行或其它请求头。")
        jar = CookieJar()
        names = set()
        for part in value.split(";"):
            part = part.strip()
            if not part:
                continue
            name, sep, content = part.partition("=")
            name = name.strip()
            if not sep or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                raise AuthError("Cookie 格式应为 name=value; name2=value2。")
            if name in names:
                raise AuthError("Cookie 名称重复，请复制 /api/portal/session 请求的 Cookie 请求头。")
            if name.lower() in {"path", "domain", "expires", "max-age", "samesite", "secure", "httponly"}:
                raise AuthError("请复制 Cookie 请求头，不要粘贴 Set-Cookie 响应头。")
            names.add(name)
            jar.set_cookie(Cookie(
                version=0, name=name, value=content.strip(), port=None,
                port_specified=False, domain=HOST, domain_specified=False,
                domain_initial_dot=False, path="/", path_specified=True,
                secure=True, expires=None, discard=True, comment=None,
                comment_url=None, rest={}, rfc2109=False,
            ))
        if not names:
            raise AuthError("Cookie 为空。")
        return jar

    def _request(self, action, jar, payload=None, csrf=""):
        if action not in PATHS:
            raise AuthError("不支持的请求。")
        if time.time() < float(self._runtime.get("retry_after") or 0):
            raise AuthError("社区请求处于限流冷却，请稍后再试。", retryable=True)
        ua = self._config.get("user_agent") or DEFAULT_UA
        if len(ua) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in ua):
            raise AuthError("User-Agent 格式不正确。")
        proxies = {}
        if self._config.get("use_proxy"):
            proxies = getattr(settings, "PROXY", None)
            if not isinstance(proxies, dict) or not proxies:
                raise AuthError("MP 代理未配置，请先配置代理或关闭“使用 MP 代理”。")
        opener = build_opener(ProxyHandler(proxies), NoRedirect(), HTTPCookieProcessor(jar))
        headers = {
            "Accept": "application/json", "User-Agent": ua,
            "Referer": ORIGIN + "/portal", "Origin": ORIGIN,
            "X-HDSky-Client": "app", "X-HDSky-Platform": "windows",
        }
        if action == "sign":
            if not csrf or any(ord(c) < 32 or ord(c) > 126 for c in csrf):
                raise AuthError("会话 CSRF Token 无效，请重新登录。")
            headers["X-CSRF-Token"] = csrf
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(ORIGIN + PATHS[action], data=data, headers=headers,
                          method="POST" if data is not None else "GET")
        # 默认 TLS 证书验证；不重试 POST；所有请求仅发往固定社区 HTTPS 地址。
        try:
            with opener.open(request, timeout=35) as response:
                raw = response.read(1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            # 只识别已知 CSRF 错误，不记录或转发服务器原文。
            try:
                error_data = json.loads(exc.read(65536))
            except (ValueError, OSError, HTTPException):
                error_data = {}
            retry_header = exc.headers.get("Retry-After", "") if exc.headers else ""
            exc.close()
            if status == 429:
                from email.utils import parsedate_to_datetime
                try:
                    delay = float(retry_header)
                except (ValueError, TypeError):
                    try:
                        delay = parsedate_to_datetime(retry_header).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        delay = 300
                delay = min(86400, max(60, delay)) if math.isfinite(delay) else 300
                self._runtime["retry_after"] = time.time() + delay
                self._save_runtime()
                raise AuthError("社区限制了请求频率，请等待冷却结束。", retryable=True) from None
            if 300 <= status < 400:
                raise AuthError("社区返回重定向，已停止；请在浏览器核对登录或验证页面。") from None
            if status in (400, 401, 403) and action == "login":
                raise AuthError("登录被拒绝，请核对 UID 和验证码是否正确、是否已过期。") from None
            if status == 401 and action in {"check", "sign"}:
                raise AuthError("Cookie 已失效或不属于此社区，请重新登录或重新填写。", invalid=True) from None
            if (status == 403 and action == "sign" and isinstance(error_data, dict)
                    and error_data.get("error") == "页面安全校验已失效，请刷新后重试"):
                raise AuthError("页面安全校验已失效，正在刷新会话。", csrf=True)
            if status == 403:
                raise AuthError("社区拒绝访问（403），请检查防护验证、User-Agent 或网络。") from None
            raise AuthError(f"社区返回 HTTP {status}。",
                            uncertain=action == "sign" and status >= 500,
                            retryable=status >= 500) from None
        except (URLError, TimeoutError, OSError, ValueError, HTTPException):
            raise AuthError("请求未完成，请检查网络、代理和证书。",
                            uncertain=action == "sign", retryable=True) from None
        if len(raw) > 1024 * 1024:
            raise AuthError("社区响应过大，已停止解析。", uncertain=action == "sign")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AuthError("社区未返回有效 JSON，可能是登录页或防护验证页。", uncertain=action == "sign") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            # 不把服务端正文或任意异常字符串写入配置、日志和提示，避免泄露凭据。
            message = {
                "send": "社区未确认验证码已发送，请核对 UID 或稍后重试。",
                "login": "社区未确认登录成功，请核对 UID 和验证码。",
                "check": "社区未确认会话有效，请重新登录或填写 Cookie。",
                "sign": "社区未确认签到成功，正在核对今日状态。",
            }[action]
            raise AuthError(message, uncertain=action == "sign")
        return result

    def _send_code(self):
        uid = self._uid()
        now = time.time()
        if now < float(self._auth.get("send_after") or 0):
            raise AuthError("发送间隔至少 60 秒，请稍后再试。")
        # 即使超时也先保存冷却，避免重复触发站内信。
        self._auth["send_after"] = now + 60
        self._auth["pending"] = {"uid": uid, "at": now, "cookies": []}
        self._save_auth()
        jar = CookieJar()
        self._request("send", jar, {"hdskyUid": uid})
        self._auth["pending"] = {
            "uid": uid, "at": now, "cookies": self._dump_cookies(jar),
        }
        self._save_auth()
        self._record(True, "验证码已发送，请查看 HDSky 站内信，在当前页面输入六位验证码并点击“登录”。")

    def _session_profile(self, result, expected_uid=""):
        profile = result.get("profile")
        if not isinstance(profile, dict) or not isinstance(profile.get("account"), dict):
            raise AuthError("会话响应缺少账户信息，未保存新 Cookie。")
        account = profile["account"]
        uid = str(account.get("hdskyUid") or "")
        if not re.fullmatch(r"[1-9][0-9]{0,11}", uid):
            raise AuthError("当前社区会话未绑定有效的 HDSky UID。")
        if expected_uid and uid != expected_uid:
            raise AuthError("会话 UID 与填写的 UID 不一致，未覆盖原 Cookie。")
        csrf = result.get("csrfToken")
        if not isinstance(csrf, str) or not csrf:
            raise AuthError("会话缺少 CSRF Token，未保存新 Cookie。")
        return {"uid": uid, "display_name": str(account.get("displayName") or "")[:100]}, csrf

    def _accept(self, jar, result, expected_uid="", source="login", clear_pending=True):
        account, csrf = self._session_profile(result, expected_uid)
        cookies = self._dump_cookies(jar)
        if not cookies:
            raise AuthError("社区未下发可保存的 Cookie，请在浏览器登录后手动填写。")
        if (self._auth.get("account") or {}).get("uid") != account["uid"]:
            self._runtime.pop("sign_retry", None)
            self._save_runtime()
        self._auth.update({
            "cookies": cookies, "csrf_token": csrf, "account": account,
            "source": source, "verified": True, "checked_at": time.time(),
            "connection_status": "ok", "connection_at": time.time(),
            "balance": self._number((result["profile"].get("wallet") or {}).get("balance"))
                       if isinstance(result["profile"].get("wallet"), dict) else None,
            "balance_at": time.time(),
        })
        if clear_pending:
            self._auth.pop("pending", None)
        self._save_auth()

    def _login(self, code):
        uid = self._uid()
        if not re.fullmatch(r"[0-9]{6}", code):
            raise AuthError("请输入六位数字验证码。")
        pending = self._auth.get("pending") or {}
        if pending.get("uid") != uid:
            raise AuthError("请先为当前 UID 发送验证码，再提交验证码登录。")
        now = time.time()
        if now < float(self._auth.get("verify_after") or 0):
            raise AuthError("验证操作过于频繁，请至少间隔 5 秒。")
        self._auth["verify_after"] = now + 5
        self._save_auth()
        jar = self._load_cookies(pending.get("cookies"))
        result = self._request("login", jar, {"hdskyUid": uid, "code": code})
        # 按真实网页合同：verify 同时返回 profile/csrfToken，Cookie 从响应头提取。
        self._accept(jar, result, expected_uid=uid)
        self._record(True, "登录成功，社区会话已保存。")

    def _import_cookie(self, value):
        jar = self._parse_cookie(value)
        try:
            result = self._request("check", jar)
        except AuthError as exc:
            # 新输入失败只否定候选 Cookie，不污染之前有效的已保存会话。
            raise AuthError(str(exc)) from None
        self._accept(jar, result, self._config.get("uid", ""), source="manual")
        self._record(True, "手动 Cookie 验证成功并已保存；输入框已清空，原有凭据已替换。")

    def _check_cookie(self):
        jar = self._load_cookies(self._auth.get("cookies"))
        if not list(jar):
            raise AuthError("没有可用的 Cookie，请先登录或手动填写。", invalid=True)
        result = self._request("check", jar)
        self._accept(jar, result, self._config.get("uid", ""), self._auth.get("source", "login"),
                     clear_pending=False)
        daily = (result.get("profile") or {}).get("dailyCheckin")
        if isinstance(daily, dict) and isinstance(daily.get("checkedIn"), bool):
            self._merge_daily({"uid": self._auth["account"]["uid"], "day": self._day(),
                "status": "already" if daily["checkedIn"] else "not_signed",
                "message": "只读查询：今日已签到。" if daily["checkedIn"] else "只读查询：今日尚未签到。",
                "time": time.time(), "balance": self._auth["balance"],
                "amount": self._number(daily.get("amount")) if daily["checkedIn"] else None})
            self._prune_daily()
            self._save_runtime()
        self._record(True, "站点连接正常，Cookie 有效；已查询余额，未执行签到。")

    def _retry_status(self):
        plan = self._runtime.get("sign_retry") or {}
        uid = str((self._auth.get("account") or {}).get("uid") or "")
        limit = self._config.get("retry_count", 0)
        valid = (self.get_state() and self._trigger and limit and plan.get("uid") == uid
                 and plan.get("day") == self._day()
                 and (not self._config.get("uid") or self._config["uid"] == uid))
        if not valid:
            return RetryStatus(limit=limit)
        return RetryStatus(pending=bool(plan.get("next_at")) and plan.get("used", 0) < limit,
                           used=plan.get("used", 0), limit=limit, next_at=plan.get("next_at", 0))

    def _plan_retry(self, status, uid, day, retryable):
        if status in SIGNED or not retryable or not self.get_state() or not self._config.get("retry_count"):
            self._runtime.pop("sign_retry", None)
            return
        if not uid or day != self._day():
            self._runtime.pop("sign_retry", None)
            return
        plan = self._runtime.get("sign_retry") or {}
        used = plan.get("used", 0) if (plan.get("uid"), plan.get("day")) == (uid, day) else 0
        self._runtime["sign_retry"] = {
            "uid": uid, "day": day, "used": used,
            "next_at": max(time.time() + self._config["retry_interval"],
                           self._runtime.get("retry_after", 0))
                       if used < self._config["retry_count"] else 0,
        }

    def retry_sign_in(self, generation=None):
        with self._lock:
            if generation is not None and generation != self._generation:
                return None
            status = self._retry_status()
            if not status.pending:
                return None
            plan = self._runtime["sign_retry"]
            if time.time() < max(plan["next_at"], self._runtime.get("retry_after", 0)):
                return None
            # 先保存已使用次数，崩溃或重启不会恢复已消耗的重试额度。
            plan["used"] += 1
            plan["next_at"] = time.time() + self._config["retry_interval"]
            self._save_runtime()
            return self.sign_in(generation=generation, expected=(plan["uid"], plan["day"]))


    def _save_runtime(self):
        self.save_data("checkins", copy.deepcopy(self._runtime))

    def _merge_daily(self, row):
        uid, day = str(row.get("uid") or ""), row.get("day", "")
        if not re.fullmatch(r"[1-9][0-9]{0,11}", uid):
            return
        try:
            date.fromisoformat(day)
        except (ValueError, TypeError):
            return
        records = self._runtime.setdefault("daily_stats", {})
        key = uid + ":" + day
        previous = records.get(key, {})
        # 一旦确认已签到，之后的读取错误不能把当日统计降为失败。
        if previous.get("status") in SIGNED and row.get("status") not in SIGNED:
            return
        if previous.get("time", 0) > row.get("time", 0):
            return
        merged = {name: row.get(name) for name in ("day", "uid", "status", "message", "time")}
        # 已签到时间固定为首次确认成功的时间，后续查询只更新状态与数值。
        if previous.get("status") in SIGNED and previous.get("time"):
            merged["time"] = previous["time"]
        for name in ("amount", "balance"):
            value = self._number(row.get(name))
            if value is None and previous.get("status") in SIGNED:
                value = self._number(previous.get(name))
            merged[name] = value
        records[key] = merged

    def _backfill_daily(self):
        """从 1.0.0 保留的回执幂等迁移；每日聚合独立于 60 条操作历史。"""
        before = copy.deepcopy(self._runtime.get("daily_stats", {}))
        rows = list(self._runtime.get("history", []))
        if self._runtime.get("last"):
            rows.append(self._runtime["last"])
        for row in sorted(rows, key=lambda item: item.get("time", 0)):
            key = str(row.get("uid") or "") + ":" + str(row.get("day") or "")
            if before.get(key, {}).get("status") in SIGNED:
                # 修复旧版被刷新覆盖的时间；不以历史快照覆盖当前余额等统计。
                previous = self._runtime["daily_stats"][key]
                if (row.get("status") in SIGNED and row.get("time", 0) > 0
                        and (not previous.get("time") or row["time"] < previous["time"])):
                    previous["time"] = row["time"]
                continue
            self._merge_daily(row)
        self._prune_daily()
        if before != self._runtime.get("daily_stats", {}):
            self._save_runtime()

    def _prune_daily(self):
        cutoff = (date.fromisoformat(self._day()) - timedelta(days=89)).isoformat()
        records = self._runtime.get("daily_stats", {})
        for key in list(records):
            if records[key].get("day", "") < cutoff:
                del records[key]

    def _statistics(self, uid):
        result = DailyStatistics(uid=uid)
        if not uid:
            return result
        today = date.fromisoformat(self._day())
        records = self._runtime.get("daily_stats", {})
        for offset in range(30):
            day = (today - timedelta(days=offset)).isoformat()
            row = DailyRecord(**records.get(uid + ":" + day, {"uid": uid, "day": day}))
            result.days.append(row)
            if row.status in SIGNED:
                result.completed_days += 1
                if row.amount is None:
                    result.unknown_reward_days += 1
                else:
                    result.reward_total += row.amount
        result.today = result.days[0]
        return result

    @staticmethod
    def _day():
        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

    @staticmethod
    def _number(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return value
        return None

    def _daily(self, result, uid):
        profile = result.get("profile")
        if not isinstance(profile, dict):
            raise AuthError("签到响应缺少账户状态。", uncertain=True)
        account = profile.get("account") or {}
        if not isinstance(account, dict) or str(account.get("hdskyUid") or "") != uid:
            raise AuthError("签到响应账号不一致，已停止。", uncertain=True)
        daily = profile.get("dailyCheckin")
        if not isinstance(daily, dict) or not isinstance(daily.get("checkedIn"), bool):
            raise AuthError("服务器未返回有效的今日签到状态，已停止提交。", uncertain=True)
        wallet = profile.get("wallet")
        return {"checked": daily["checkedIn"], "amount": self._number(daily.get("amount")),
                "balance": self._number(wallet.get("balance")) if isinstance(wallet, dict) else None}

    def _refresh_sign_session(self, jar, uid=""):
        result = self._request("check", jar)
        self._accept(jar, result, uid or self._config.get("uid", ""),
                     self._auth.get("source", "login"), clear_pending=False)
        uid = self._auth["account"]["uid"]
        return uid, self._daily(result, uid)

    def _finish_sign(self, status, message, uid="", daily=None, day=None, retryable=False):
        day = day or self._day()
        daily = daily or {}
        row = {"time": time.time(), "day": day, "uid": uid, "status": status,
               "message": message, "amount": daily.get("amount"), "balance": daily.get("balance")}
        self._merge_daily(row)
        self._prune_daily()
        history = self._runtime.setdefault("history", [])
        previous = history[0] if history else {}
        # 同账号同日重复检查的“已签到”只更新一行，不刷通知。
        duplicate = (status == "already" and previous.get("uid") == uid
                     and previous.get("day") == day
                     and previous.get("status") in {"success", "already", "confirmed"})
        if not duplicate:
            history.insert(0, row)
            del history[60:]
        self._runtime["last"] = row
        self._plan_retry(status, uid, day, retryable)
        self._save_runtime()
        self._record(status in {"success", "already", "confirmed"}, message)
        logger.info(f"天空社区签到：{message}")
        if self._config.get("notify") and not duplicate:
            lines = [message]
            if uid:
                lines.append("HDSky UID：" + uid)
            if daily.get("amount") is not None:
                lines.append(f"今日奖励：{daily['amount']:g} 银元")
            if daily.get("balance") is not None:
                lines.append(f"当前余额：{daily['balance']:g} 银元")
            try:
                self.post_message(mtype=MessageType.Plugin, title="【天空社区客户端签到】",
                                  text="\n".join(lines))
            except Exception:
                logger.warning("天空社区签到结果已保存，但通知发送失败。")
        return row

    def sign_in(self, generation=None, expected=None):
        with self._lock:
            if not self.get_state() or (generation is not None and generation != self._generation):
                return None
            uid, day, daily = "", self._day(), None
            try:
                jar = self._load_cookies(self._auth.get("cookies"))
                if not list(jar):
                    raise AuthError("请先完成站内信登录或手动填写社区 Cookie。", invalid=True)
                uid, daily = self._refresh_sign_session(jar)
                day = self._day()
                if expected is not None and expected != (uid, day):
                    self._runtime.pop("sign_retry", None)
                    self._save_runtime()
                    return None
                attempts = self._runtime.setdefault("attempts", {})
                key = uid + ":" + day
                # 只保留近 60 个账号日意图。
                for old in sorted(attempts)[:-59]:
                    if old != key:
                        attempts.pop(old, None)
                attempt = attempts.get(key)
                if daily["checked"]:
                    if attempt:
                        attempt["state"] = "done"
                    return self._finish_sign("already", "今日已签到，已跳过提交。", uid, daily, day)
                if attempt and attempt.get("state") in {"sent", "uncertain", "done"}:
                    return self._finish_sign("uncertain",
                        "今日已有提交记录但服务器尚未确认；仅重试查询，不重复提交。", uid, daily, day,
                        retryable=True)
                if not self.get_state():
                    return None
                attempt = {"request_key": (attempt or {}).get("request_key") or uuid.uuid4().hex,
                           "state": "sent", "day": day, "uid": uid}
                attempts[key] = attempt
                self._save_runtime()  # 发出写请求前持久化；崩溃后只查状态。
                try:
                    result = self._request("sign", jar, {"requestKey": attempt["request_key"]},
                                           csrf=self._auth["csrf_token"])
                except AuthError as exc:
                    if not exc.csrf:
                        raise
                    # 服务端明确拒绝了 CSRF 才允许刷新后重试一次，复用同一请求键。
                    uid, daily = self._refresh_sign_session(jar, uid)
                    if daily["checked"]:
                        attempt["state"] = "done"
                        return self._finish_sign("confirmed", "已核实今日签到完成。", uid, daily, day)
                    if not self.get_state():
                        attempt["state"] = "rejected"
                        self._save_runtime()
                        return None
                    if self._day() != day:
                        attempt["state"] = "rejected"
                        self._runtime.pop("sign_retry", None)
                        self._save_runtime()
                        return None
                    result = self._request("sign", jar, {"requestKey": attempt["request_key"]},
                                           csrf=self._auth["csrf_token"])
                daily = self._daily(result, uid)
                if not daily["checked"]:
                    raise AuthError("签到返回后今日状态仍未确认。", uncertain=True)
                self._auth["cookies"] = self._dump_cookies(jar)
                self._auth.update(balance=daily["balance"], balance_at=time.time())
                self._save_auth()
                attempt["state"] = "done"
                return self._finish_sign("success", "签到成功。", uid, daily, day)
            except AuthError as exc:
                attempt = self._runtime.get("attempts", {}).get(uid + ":" + day)
                if exc.invalid:
                    self._auth["verified"] = False
                    self._auth.update(connection_status="invalid", connection_at=time.time())
                    self._save_auth()
                if attempt and attempt.get("state") == "sent":
                    # 非明确拒绝都按未知写入处理；仅通过一次读请求核对。
                    attempt["state"] = "uncertain" if exc.uncertain else "rejected"
                    self._save_runtime()
                    if exc.uncertain:
                        can_recheck = True
                        try:
                            _, verified = self._refresh_sign_session(jar, uid)
                            if verified["checked"]:
                                attempt["state"] = "done"
                                return self._finish_sign("confirmed", "提交响应异常，已核实今日签到完成。",
                                                         uid, verified, day)
                        except AuthError as check_error:
                            if check_error.invalid:
                                can_recheck = False
                                self._auth.update(verified=False, connection_status="invalid",
                                                  connection_at=time.time())
                                self._save_auth()
                        return self._finish_sign("uncertain", "签到结果待确认，已暂停今日重复提交。",
                                                 uid, None, day, retryable=can_recheck)
                # 预查询失败时也为已保存账号记录当日结果，但不触碰旧提交意图。
                recorded_uid = uid or str((self._auth.get("account") or {}).get("uid") or "")
                return self._finish_sign("failed", str(exc), recorded_uid, None, day,
                                         retryable=exc.retryable or exc.uncertain)

    def get_form(self):
        # Vue 配置组件自己调用已认证 API，模型不包含任何一次性凭据。
        return None, PublicConfig(**{key: self._config[key] for key in PublicConfig.model_fields
                                     if key in self._config}).model_dump()

    def get_page(self):
        return []

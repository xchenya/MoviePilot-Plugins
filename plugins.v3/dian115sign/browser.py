"""Browser-only Dian115 client: execute the site's UI, never forge its proof/signature.

The API names and result fields below come from the original public plugin. They
are a compatibility assumption until verified against the user's live account.
No MoviePilot imports are made here; host integration lives in __init__.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from threading import Event
from typing import Any, Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ORIGIN = "https://m.dian115.com"
API = "/api/portal"
AUTH_CODES = {"no_token", "invalid_token", "token_revoked", "unauthorized"}
HUMAN_CODES = {"turnstile_failed", "captcha_required", "captcha_failed"}
KNOWN_PATHS = {
    f"{API}/auth/browser-challenge", f"{API}/auth/browser-session",
    f"{API}/auth/policy", f"{API}/auth/login", f"{API}/me",
    f"{API}/signin", f"{API}/signin/calendar",
}


class PortalError(Exception):
    """A safe, user-readable error; never includes headers, passwords or bodies."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Options:
    """Immutable settings snapshot for one execution."""

    email: str = ""
    password: str = ""
    token: str = ""
    cookie: str = ""
    lucky_mode: bool = False
    timezone: str = "Asia/Shanghai"
    timeout: int = 30
    normal_selector: str = ""
    lucky_selector: str = ""
    submit_selector: str = ""
    login_selector: str = ""

    @property
    def mode(self) -> str:
        """Translate the existing plugin's mode switch."""
        return "lucky" if self.lucky_mode else "normal"

    def today(self) -> str:
        """Use the configured site timezone, not the container's local timezone."""
        return datetime.now(ZoneInfo(self.timezone)).date().isoformat()

    def identity(self, proxy: str = "") -> str:
        """Bind cached authentication to the explicit credentials and egress."""
        raw = json.dumps([self.email, self.password, self.token, self.cookie, proxy],
                         ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Outcome:
    """Only allowlisted, non-secret data can reach logs or the plugin page."""

    ok: bool = False
    code: str = "not_started"
    message: str = "尚未运行"
    date: str = ""
    mode: str = "normal"
    already: bool = False
    award: float | None = None
    balance: float | None = None
    streak: int | None = None
    uncertain: bool = False
    submitted: bool = False
    checked_at: str = ""
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable snapshot."""
        return asdict(self)


def seed_cookies(token: str = "", cookie: str = "") -> list[dict[str, Any]]:
    """Accept a bare token or a complete Cookie header; keep all cookie pairs.

    Cookie attributes are not converted into cookies. Cookies are always scoped
    to the fixed HTTPS site and are never sent using a global Cookie header.
    """
    result: dict[str, str] = {}
    for raw in (token, cookie):
        raw = str(raw or "").strip()
        if not raw:
            continue
        if len(raw) > 65536 or "\r" in raw or "\n" in raw:
            raise PortalError("cookie_invalid", "Cookie 格式不合法；请粘贴单行 Cookie 值。")
        raw = re.sub(r"^(?:Cookie|Authorization)\s*:\s*", "", raw, flags=re.I)
        raw = re.sub(r"^Bearer\s+", "", raw, flags=re.I)
        if raw.count(".") == 2 and ";" not in raw and not re.match(r"^[\w-]+=", raw):
            result["__Host-portal_token"] = raw
            continue
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except CookieError:
            raise PortalError("cookie_invalid", "Cookie 无法解析。") from None
        if not jar:
            raise PortalError("cookie_invalid", "请输入完整 Cookie 或登录 Token。")
        result.update({key: morsel.value for key, morsel in jar.items()})
    return [{"name": key, "value": value, "url": ORIGIN + "/", "secure": True,
             "httpOnly": key in {"__Host-portal_token", "portal_token"}, "sameSite": "Lax"}
            for key, value in result.items()]


def initial_cookies(options: Options) -> tuple[list[dict[str, Any]], bool]:
    """Build optional seed cookies without blocking password login.

    Legacy/stale Token or Cookie values may survive an upgrade. When a complete
    email/password pair is configured, an unparsable seed is ignored and the
    browser proceeds to the normal login form. Without password credentials,
    the same malformed seed remains a configuration error.
    """
    if not options.token and not options.cookie:
        return [], False
    try:
        return seed_cookies(options.token, options.cookie), False
    except PortalError as error:
        if error.code == "cookie_invalid" and options.email and options.password:
            return [], True
        raise


def same_origin(url: str) -> bool:
    """Never fill credentials or accept account responses on a redirected site."""
    target = urlsplit(url)
    try:
        return (target.scheme == "https" and target.hostname == "m.dian115.com"
                and target.port in (None, 443) and not target.username and not target.password)
    except ValueError:
        return False


def safe_code(value: Any) -> str:
    """Keep bounded machine codes, not arbitrary server-provided messages."""
    text = value if isinstance(value, str) else ""
    return text if re.fullmatch(r"[a-z][a-z0-9_\-]{0,63}", text) else ""


def number(value: Any) -> float | None:
    """Reject non-finite values and booleans in account/result fields."""
    import math
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError, OverflowError):
        return None


def browser_failure(error: Exception) -> PortalError:
    """Classify transport/launch failures without exposing the exception text."""
    text = str(error)
    mappings = (
        (("ERR_BLOCKED_BY_ADMINISTRATOR",), "browser_policy_block", "浏览器导航被系统策略阻止。"),
        (("ERR_PROXY_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED"), "proxy_failed", "浏览器无法连接配置的代理。"),
        (("ERR_NAME_NOT_RESOLVED",), "dns_failed", "浏览器无法解析站点域名。"),
        (("ERR_CERT_", "CERTIFICATE_VERIFY_FAILED"), "tls_failed", "站点证书验证失败；未关闭 TLS 校验。"),
        (("Executable doesn't exist", "executable doesn't exist"), "browser_missing", "宿主浏览器可执行文件缺失；请修复 MoviePilot 浏览器环境。"),
    )
    for markers, code, message in mappings:
        if any(marker in text for marker in markers):
            return PortalError(code, message)
    if isinstance(error, ImportError):
        return PortalError("browser_dependency_missing", "宿主浏览器依赖不可用；插件没有自行安装或升级宿主依赖。")
    if type(error).__name__ == "TimeoutError":
        return PortalError("browser_timeout", "浏览器页面或元素等待超时；未重复提交签到。")
    return PortalError("browser_error", f"浏览器操作未完成（{type(error).__name__}）；请检查宿主浏览器环境、代理或页面变化。")


class Trace:
    """Observe only the site's known portal responses; retain no raw payloads."""

    def __init__(self):
        self.rows: list[dict[str, Any]] = []
        self.latest: dict[str, dict[str, Any]] = {}
        self.user: dict[str, Any] | None = None
        self.auth_failed = False
        self.human_required = False
        self.sign: dict[str, Any] | None = None

    def response(self, response: Any) -> None:
        """Playwright response event handler; malformed bodies cannot crash it."""
        if not same_origin(response.url):
            return
        path = urlsplit(response.url).path
        if path not in KNOWN_PATHS:
            return
        try:
            payload = response.json()
        except Exception:
            payload = None
        payload = payload if isinstance(payload, dict) else {}
        status = int(response.status)
        code = safe_code(payload.get("code"))
        content_type = str(response.headers.get("content-type", "")).split(";", 1)[0]
        content_type = content_type if content_type in {
            "application/json", "text/html", "text/plain", "application/problem+json"
        } else "other"
        row = {"path": path, "status": status, "code": code, "content_type": content_type}
        self.rows.append(row)
        self.rows = self.rows[-30:]
        self.latest[path] = row
        if code in AUTH_CODES:
            self.auth_failed = True
        if code in HUMAN_CODES:
            self.human_required = True
        if path.endswith("/auth/policy") and payload.get("turnstile_enabled") is True:
            self.human_required = True
        if path == f"{API}/me" and 200 <= status < 300 and code == "ok":
            user = payload.get("user")
            if isinstance(user, dict) and user:
                self.user = {key: user.get(key) for key in (
                    "points", "consecutive_signin", "last_signin_date")}
                self.auth_failed = False
        if path == f"{API}/signin" and response.request.method.upper() == "POST":
            self.user = None  # Old account statistics are not post-sign-in statistics.
            self.sign = {"status": status, "code": code,
                         **{key: payload.get(key) for key in (
                             "award", "new_balance", "mode", "lucky_tier")}}

    def gate_error(self) -> PortalError | None:
        """Distinguish access rejection from an invalid login."""
        for path, row in self.latest.items():
            if row["status"] == 429:
                return PortalError("rate_limited", f"站点限流：HTTP 429，接口 {path}；本轮不重试。")
            if row["status"] == 403 and row["code"] not in AUTH_CODES:
                return PortalError("access_denied", f"站点拒绝访问：HTTP 403，接口 {path}，"
                                   f"业务码 {row['code'] or '未提供'}；未将其判定为 Token 失效。")
            if row["status"] >= 500:
                return PortalError("server_error", f"站点服务异常：HTTP {row['status']}，接口 {path}。")
        return None


class SubmissionGuard:
    """Prevent accidental mode changes, diagnostic sign-ins and blind replay."""

    def __init__(self, mode: str, diagnose: bool, cancel: Event,
                 mark_pending: Callable[[], bool]):
        self.mode, self.diagnose, self.cancel = mode, diagnose, cancel
        self.mark_pending = mark_pending
        self.sent = 0
        self.login_sent = 0
        self.error: PortalError | None = None

    def route(self, route: Any) -> None:
        """Validate outgoing writes before the browser sends them."""
        req = route.request
        path = urlsplit(req.url).path
        if req.method.upper() != "POST" or path not in {
            f"{API}/signin", f"{API}/auth/login"
        }:
            route.continue_()
            return
        if self.cancel.is_set() or not same_origin(req.url):
            self.error = PortalError("cancelled", "任务已取消或目标域名异常；已阻止提交。")
        elif path.endswith("/auth/login"):
            if self.login_sent:
                self.error = PortalError("login_repeated", "已阻止同一轮重复提交登录；请检查账号或人机验证。")
            else:
                self.login_sent += 1
        elif self.diagnose:
            self.error = PortalError("diagnostic_write_blocked", "诊断模式已阻止签到提交。")
        elif self.sent:
            self.error = PortalError("duplicate_blocked", "已阻止同一轮重复提交签到。")
        else:
            try:
                body = req.post_data_json
            except Exception:
                body = None
            if not isinstance(body, dict) or body.get("mode") != self.mode:
                self.error = PortalError("mode_mismatch", "页面请求的签到模式与设置不符；已阻止提交，未自动改用另一种模式。")
            elif not self.mark_pending():
                self.error = PortalError("state_write_failed", "无法记录提交状态或配置已经重载；为避免重复签到，已阻止提交。")
            else:
                self.sent += 1
        if self.error:
            route.abort()
        else:
            route.continue_()


class BrowserRunner:
    """One bounded browser session, one login at most, one sign-in at most."""

    def __init__(self, options: Options, launch: Callable[..., Any], cancel: Event,
                 load_state: Callable[[], dict | None], save_state: Callable[[dict], None],
                 pending: Callable[[], bool], mark_pending: Callable[[], bool],
                 proxy: dict | None = None):
        self.options, self.launch, self.cancel = options, launch, cancel
        self.load_state, self.save_state = load_state, save_state
        self.pending, self.mark_pending, self.proxy = pending, mark_pending, proxy
        self.trace = Trace()
        self.page: Any = None
        self.guard: SubmissionGuard | None = None
        self.deadline = 0.0

    def _check(self) -> None:
        """Bound every wait and refuse off-site credential interaction."""
        if self.cancel.is_set():
            raise PortalError("cancelled", "配置已更新或插件已停用；任务取消。")
        if time.monotonic() >= self.deadline:
            raise PortalError("timeout", "等待站点响应超时；未进行盲目重试。")
        if self.page is not None and self.page.url != "about:blank" and not same_origin(self.page.url):
            raise PortalError("site_redirect", "站点跳转到了其他域名，已停止；未向跳转后的页面填写账号密码。")
        if self.guard and self.guard.error:
            raise self.guard.error

    def _wait(self, seconds: float = 0.2) -> None:
        """Pump browser events instead of blocking them with time.sleep()."""
        self._check()
        self.page.wait_for_timeout(seconds * 1000)
        self._check()

    @staticmethod
    def _one(locator: Any) -> Any | None:
        """Fail closed on ambiguous UI; never click the first arbitrary button."""
        matches = [locator.nth(i) for i in range(min(locator.count(), 100))
                   if locator.nth(i).is_visible() and locator.nth(i).is_enabled()]
        if len(matches) > 1:
            raise PortalError("selector_ambiguous", "发现多个匹配按钮或输入框；请指定更精确的选择器。")
        return matches[0] if matches else None

    def _password(self) -> Any | None:
        """Identify a visible password field without reading its value."""
        return self._one(self.page.locator('input[type="password"]'))

    def _goto(self, path: str) -> None:
        """Only navigate to the fixed portal origin."""
        self._check()
        response = self.page.goto(ORIGIN + path, wait_until="domcontentloaded",
                                  timeout=self.options.timeout * 1000)
        self._check()
        if response and response.status in {403, 429}:
            raise PortalError("page_rejected", f"页面访问被拒绝：HTTP {response.status}；本轮不重试。")
        if response and response.status >= 500:
            raise PortalError("server_error", f"页面服务异常：HTTP {response.status}。")

    def _account(self) -> dict[str, Any]:
        """Confirm authentication from /me, not from the unverified JWT payload."""
        stop = min(self.deadline, time.monotonic() + self.options.timeout)
        while time.monotonic() < stop:
            self._check()
            gate = self.trace.gate_error()
            if gate:
                raise gate
            if self.trace.user:
                return self.trace.user
            if self.trace.auth_failed or self._password() is not None:
                break
            self._wait()
        else:
            raise PortalError("account_unconfirmed", "未观察到有效账号响应；页面或接口可能变化，请查看诊断记录。")
        if not (self.options.email and self.options.password):
            raise PortalError("login_required", "站点要求登录；请在插件配置中填入完整 Cookie，或邮箱和密码。")
        if self.trace.human_required:
            raise PortalError("human_required", "站点要求人机验证；请先在浏览器完成验证并更新 Cookie。")
        if self._password() is None:
            self._goto("/login")
        # Wait for a unique login form; re-check origin before filling secrets.
        stop = min(self.deadline, time.monotonic() + 10)
        password = None
        while time.monotonic() < stop:
            self._check()
            password = self._password()
            if password is not None:
                break
            self._wait()
        if password is None:
            raise PortalError("login_ui_changed", "未找到登录表单；没有尝试猜测性提交。")
        self._check()
        if self.trace.human_required:
            raise PortalError("human_required", "登录需要人机验证；请手动完成后更新 Cookie。")
        email = self._one(self.page.locator(
            'input[type="email"], input[name="email"], input[autocomplete="username"]'))
        if email is None:
            raise PortalError("login_ui_changed", "未找到唯一的邮箱输入框；请检查站点登录页面。")
        email.fill(self.options.email)
        self._check()
        password.fill(self.options.password)
        self._check()
        button = (self._one(self.page.locator(self.options.login_selector))
                  if self.options.login_selector else self._one(self.page.get_by_role(
                      "button", name=re.compile(r"^\s*(?:登录|登\s+录|立即登录|Login|Sign in)\s*$", re.I))))
        if button is None:
            raise PortalError("login_ui_changed", "未找到唯一登录按钮；请设置登录按钮选择器。")
        self.trace.auth_failed = False
        self.trace.latest.pop(f"{API}/auth/login", None)
        button.click(timeout=5000)
        stop = min(self.deadline, time.monotonic() + self.options.timeout)
        while time.monotonic() < stop:
            self._wait()
            gate = self.trace.gate_error()
            if gate:
                raise gate
            if self.trace.human_required:
                raise PortalError("human_required", "站点要求人机验证；自动登录已停止。")
            row = self.trace.latest.get(f"{API}/auth/login", {})
            if row.get("code") == "ok" and 200 <= row.get("status", 0) < 300:
                # Re-enter the sign-in view; let the frontend refresh its session.
                self.trace.user = None
                self._goto("/me/signin")
                break
            if row.get("code") or row.get("status", 0) >= 400:
                raise PortalError("login_failed", "站点拒绝登录；业务码：" + (row.get("code") or "未提供"))
        else:
            raise PortalError("login_timeout", "登录结果未确认；本轮不再次提交密码。")
        stop = min(self.deadline, time.monotonic() + self.options.timeout)
        while time.monotonic() < stop:
            self._wait()
            gate = self.trace.gate_error()
            if gate:
                raise gate
            if self.trace.user:
                return self.trace.user
        raise PortalError("account_unconfirmed", "登录后仍未取得有效账号响应；没有执行签到。")

    def _sign_button(self) -> Any | None:
        """Select a mode-specific button before considering a generic submit."""
        selector = (self.options.lucky_selector if self.options.lucky_mode
                    else self.options.normal_selector)
        if selector:
            return self._one(self.page.locator(selector))
        mode = "运气" if self.options.lucky_mode else "普通"
        return self._one(self.page.get_by_role("button", name=re.compile(
            rf"^\s*{mode}签(?:到)?(?:\s*[（(].*[)）])?\s*$")))

    def _submit_button(self) -> Any | None:
        """A generic button is safe only because outgoing mode is checked."""
        if self.options.submit_selector:
            return self._one(self.page.locator(self.options.submit_selector))
        return self._one(self.page.get_by_role("button", name=re.compile(
            r"^\s*(?:立即签到|今日签到|签到|开始签到)\s*$")))

    def _sign(self, outcome: Outcome) -> None:
        """Use the actual UI, observe its response, never replay an uncertain POST."""
        if self.pending():
            raise PortalError("previous_outcome_unknown", "上一次提交结果不确定，且账号尚未显示今日已签；"
                              "为避免重复提交已停止。请先人工核对，再清除待确认标记。")
        mode_button = self._sign_button()
        button = mode_button
        if button is None:
            button = self._submit_button()
        if button is None:
            raise PortalError("signin_ui_changed", "没有找到唯一签到按钮；请设置模式/提交按钮选择器。")
        self._check()
        button.click(timeout=5000)
        self._wait(0.5)
        # Some sites have a mode selector followed by a separate submit button.
        if mode_button is not None and not self.guard.sent and not self.trace.sign:
            submit = self._submit_button()
            if submit is not None:
                self._check()
                submit.click(timeout=5000)
        stop = min(self.deadline, time.monotonic() + self.options.timeout)
        while self.trace.sign is None and time.monotonic() < stop:
            self._wait()
            gate = self.trace.gate_error()
            if gate:
                raise gate
        self._check()
        sign = self.trace.sign
        if sign is None:
            raise PortalError("outcome_unknown" if self.guard.sent else "signin_ui_changed",
                              "未获得明确签到结果；没有重复提交。请核对网站签到状态。")
        if not self.guard.sent:
            raise PortalError("untracked_submission", "未确认签到请求经过提交保护；不将响应计为成功。")
        status, code = sign["status"], sign["code"]
        if code == "already_signed" and status in {200, 409}:
            outcome.ok, outcome.already = True, True
            outcome.code, outcome.message = "already_signed", "站点确认今日已签到"
        elif 200 <= status < 300 and code == "ok":
            if sign.get("mode") not in {None, "", self.options.mode}:
                raise PortalError("response_mode_mismatch", "站点返回的签到模式不符；请人工核对结果。")
            outcome.ok, outcome.code, outcome.message = True, "signed", "站点确认签到成功"
            outcome.streak = None  # Do not invent or reuse the pre-sign-in streak.
            outcome.award = number(sign.get("award"))
            outcome.balance = number(sign.get("new_balance"))
        else:
            raise PortalError("signin_rejected", f"签到未成功：HTTP {status}，业务码 {code or '未提供'}。")

    def run(self, diagnose: bool = False) -> Outcome:
        """Run and close the browser in its owning thread, including failures."""
        outcome = Outcome(date=self.options.today(), mode=self.options.mode,
                          checked_at=datetime.now(ZoneInfo(self.options.timezone)).isoformat(timespec="seconds"))
        self.deadline = time.monotonic() + max(60, self.options.timeout * 4)
        context = None
        try:
            self._check()
            state = self.load_state()
            kwargs: dict[str, Any] = {"headless": True, "service_workers": "block"}
            if self.proxy:
                kwargs["proxy"] = self.proxy
            if state:
                kwargs["storage_state"] = state
            context = self.launch(**kwargs)
            if not state:
                cookies, ignored_seed = initial_cookies(self.options)
                if ignored_seed:
                    self.trace.rows.append({
                        "path": "browser.credentials", "status": 0,
                        "code": "cookie_seed_ignored", "content_type": "other",
                    })
                if cookies:
                    context.add_cookies(cookies)
            self.guard = SubmissionGuard(self.options.mode, diagnose, self.cancel, self.mark_pending)
            context.route("**/api/portal/**", self.guard.route)
            self.page = context.new_page()
            self.page.set_default_timeout(5000)
            self.page.on("response", self.trace.response)
            self._goto("/me/signin")
            user = self._account()
            outcome.balance = number(user.get("points"))
            streak = number(user.get("consecutive_signin"))
            outcome.streak = int(streak) if streak is not None else None
            signed_today = str(user.get("last_signin_date") or "") == outcome.date
            if diagnose:
                outcome.ok, outcome.code = True, "diagnostic_ok"
                outcome.already = signed_today
                outcome.message = "登录与账号读取正常；诊断模式未提交签到"
            elif signed_today:
                outcome.ok, outcome.already = True, True
                outcome.code, outcome.message = "already_signed", "账号确认今日已签到，无需重复提交"
            else:
                self._sign(outcome)
            # Save renewed cookies/storage, not the stale configured token.
            if not self.cancel.is_set():
                try:
                    self.save_state(context.storage_state())
                except Exception:
                    # A confirmed external operation stays confirmed even if caching fails.
                    self.trace.rows.append({"path": "browser.state", "status": 0,
                                            "code": "state_save_failed", "content_type": "other"})
        except PortalError as error:
            outcome.code, outcome.message = error.code, str(error)
        except Exception as error:
            # Playwright errors can contain request headers and form values.
            # Deliberately do not log str(error), exception chains or tracebacks.
            failure = browser_failure(error)
            outcome.code, outcome.message = failure.code, str(failure)
        finally:
            outcome.submitted = bool(self.guard and self.guard.sent)
            sign = self.trace.sign or {}
            definitive_rejection = 400 <= sign.get("status", 0) < 500
            outcome.uncertain = (outcome.code == "previous_outcome_unknown" or
                                 (outcome.submitted and not outcome.ok and not definitive_rejection))
            outcome.diagnostics = list(self.trace.rows)
            if context is not None:
                try:
                    context.close()
                except Exception:
                    # Close failure must not turn a confirmed sign-in into a retry.
                    outcome.diagnostics.append({"path": "browser.close", "status": 0,
                                                "code": "close_failed", "content_type": "other"})
        return outcome

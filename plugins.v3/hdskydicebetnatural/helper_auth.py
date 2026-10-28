"""HDSky helper login and native MP form buttons; no game actions."""
import copy
import re
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HelperAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["send", "login", "status", "import"]
    uid: str = Field(default="", max_length=12)
    email: str = Field(default="", max_length=254)
    code: str = Field(default="", max_length=6, repr=False)
    access_token: str = Field(default="", max_length=8192, repr=False)
    refresh_token: str = Field(default="", max_length=8192, repr=False)
    site_id: int | None = Field(default=None, ge=1)


class HelperAuthState(BaseModel):
    configured: bool = False
    uid: str = ""
    email: str = ""
    pending_uid: str = ""
    pending_email: str = ""
    send_after: float = 0
    verify_after: float = 0
    retry_after: float = 0
    saved_at: float = 0


class HelperAuthResult(BaseModel):
    success: bool
    message: str
    state: HelperAuthState


class HelperLoginError(Exception):
    pass


UI_KEYS = (
    "helper_uid", "helper_email", "helper_code", "helper_busy",
    "helper_login_message", "helper_login_type", "helper_plugin_id",
)


def token_value(value):
    if not isinstance(value, str):
        raise HelperLoginError("认证响应中的 Token 格式无效，请重新登录。")
    value = value.strip()
    if not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value) or ";" in value:
        raise HelperLoginError("Token 格式无效，请重新登录或复制完整 Token。")
    return value


class HelperLogin:
    """One instance-scoped lock also serializes refresh and configuration reload."""
    def __init__(self, host):
        self.host = host
        self.lock = threading.RLock()

    def metadata(self):
        value = self.host.get_data("helper_login")
        return copy.deepcopy(value) if isinstance(value, dict) else {}

    def credentials(self):
        value = self.host.get_data("helper_credentials")
        return copy.deepcopy(value) if isinstance(value, dict) else {}

    def write(self, key, value):
        if self.host.save_data(key, copy.deepcopy(value)) is False:
            raise HelperLoginError("凭据或登录状态保存失败，请检查 MP 存储后重试。")

    def initialize(self, config):
        """Migrate old manual config once; keep later form saves free of secrets."""
        credentials = self.credentials()
        access = str(config.get("helper_cookie") or "").strip()
        refresh = str(config.get("helper_refresh_token") or "").strip()
        if access or refresh:
            # Existing 2.4.x configs may have access only; retain that supported mode.
            if access:
                access = re.sub(r"(?i)^bearer\s+", "", access).removeprefix("accessToken=")
                access = token_value(access)
            if refresh:
                token_value(refresh)
            credentials = {"access_token": access, "refresh_token": refresh,
                           "uid": "", "email": "", "saved_at": time.time()}
            self.write("helper_credentials", credentials)
        self.host._helper_cookie = credentials.get("access_token", "")
        self.host._helper_refresh_token = credentials.get("refresh_token", "")
        config.pop("helper_cookie", None)
        config.pop("helper_refresh_token", None)
        for key in UI_KEYS:
            config.pop(key, None)
        self.host._config = dict(config)

    def save_tokens(self, access, refresh, uid=None, email=None):
        access, refresh = token_value(access), token_value(refresh)
        previous = self.credentials()
        value = {"access_token": access, "refresh_token": refresh,
                 "uid": previous.get("uid", "") if uid is None else uid,
                 "email": previous.get("email", "") if email is None else email,
                 "saved_at": time.time()}
        self.write("helper_credentials", value)  # Persistence must succeed before activation.
        self.host._helper_cookie, self.host._helper_refresh_token = access, refresh
        self.host._config["helper_cookie"] = ""
        self.host._config["helper_refresh_token"] = ""

    def state(self):
        meta, credentials = self.metadata(), self.credentials()
        return HelperAuthState(
            configured=bool(credentials.get("access_token")),
            uid=credentials.get("uid", ""), email=credentials.get("email", ""),
            saved_at=credentials.get("saved_at", 0),
            **{key: meta.get(key, "" if key.startswith("pending_") else 0)
               for key in ("pending_uid", "pending_email", "send_after", "verify_after", "retry_after")})

    def result(self, success, message):
        return HelperAuthResult(success=success, message=message, state=self.state())

    def remote(self, action, body, site_id):
        try:
            response = self.host._helper_login_post(action, body, site_id)
        except Exception:
            raise HelperLoginError("辅助站请求未完成，请检查网络和代理；本次不会自动重发。") from None
        if response is None:
            raise HelperLoginError("辅助站未响应；本次不会自动重发。")
        status = response.status_code
        if status == 429:
            retry = (getattr(response, "headers", None) or {}).get("Retry-After", "")
            try:
                delay = float(retry)
            except (TypeError, ValueError):
                try:
                    dt = parsedate_to_datetime(retry)
                    delay = dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    delay = 300
            import math
            delay = min(86400, max(60, delay)) if math.isfinite(delay) else 300
            meta = self.metadata()
            meta["retry_after"] = time.time() + delay
            self.write("helper_login", meta)
            raise HelperLoginError("辅助站请求被限流，请等待冷却结束后重试。")
        if status in (301, 302, 303, 307, 308):
            raise HelperLoginError("辅助站返回重定向，已停止转发登录信息。")
        if status != 200:
            if status in (400, 401, 403, 422):
                raise HelperLoginError("登录请求被拒绝，请核对 UID、主站邮箱和验证码；验证码可能已过期。")
            raise HelperLoginError(f"辅助站返回 HTTP {status}；本次不会自动重试。")
        try:
            payload = response.json()
        except Exception:
            raise HelperLoginError("辅助站未返回有效 JSON，请检查网络或站点验证页面。") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise HelperLoginError("辅助站未确认操作成功，请核对 UID、主站邮箱和验证码。")
        return payload

    def perform(self, request):
        if not self.lock.acquire(blocking=False):
            return self.result(False, "正在处理认证请求，请稍后再试。")
        try:
            if request.action == "status":
                return self.result(True, "Token 已保存，独立观影券检查会核验有效性并自动续期。"
                                   if self.state().configured else "尚未保存辅助站凭据。")
            meta, now = self.metadata(), time.time()
            if now < meta.get("retry_after", 0):
                raise HelperLoginError("辅助站正在限流冷却，请稍后再试。")
            if request.action == "import":
                access, refresh = token_value(request.access_token), token_value(request.refresh_token)
                self.save_tokens(access, refresh, uid="", email="")
                return self.result(True, "手动 Token 已保存；独立观影券检查将核验有效性。")
            uid, email = request.uid.strip(), request.email.strip()
            if not re.fullmatch(r"[1-9][0-9]{0,11}", uid):
                raise HelperLoginError("请输入正确的主站数字 UID。")
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise HelperLoginError("请输入主站资料中的完整邮箱。")
            if request.action == "send":
                if now < meta.get("send_after", 0):
                    raise HelperLoginError("发送验证码需间隔至少 60 秒，请稍后再试。")
                meta.update(send_after=now + 60, pending_uid=uid, pending_email=email)
                self.write("helper_login", meta)  # Even a timeout may have delivered the private message.
                self.remote("send", {"userId": uid, "email": email, "code": ""}, request.site_id)
                return self.result(True, "验证码已发到 HDSky 主站私信；填写后直接点击“登录”，无需保存配置。")
            code = request.code.strip()
            if not re.fullmatch(r"[0-9]{6}", code):
                raise HelperLoginError("请输入六位数字验证码。")
            if (meta.get("pending_uid"), meta.get("pending_email")) != (uid, email):
                raise HelperLoginError("请先为当前 UID 和邮箱发送验证码，再提交登录。")
            if now < meta.get("verify_after", 0):
                raise HelperLoginError("登录操作需间隔至少 5 秒，请稍后再试。")
            meta["verify_after"] = now + 5
            self.write("helper_login", meta)
            payload = self.remote("login", {"userId": uid, "email": email, "code": code}, request.site_id)
            data = payload.get("data")
            if not isinstance(data, dict):
                raise HelperLoginError("登录响应缺少认证数据，未替换原凭据。")
            user = data.get("user") or {}
            if not isinstance(user, dict):
                raise HelperLoginError("登录响应账户信息无效，未替换原凭据。")
            if user.get("userId") is not None and str(user["userId"]) != uid:
                raise HelperLoginError("登录响应 UID 不一致，未替换原凭据。")
            access, refresh = token_value(data.get("accessToken")), token_value(data.get("refreshToken"))
            token_uid = self.host._helper_user_id(access)
            if token_uid and token_uid != uid:
                raise HelperLoginError("登录响应 Token 的 UID 不一致，未替换原凭据。")
            self.save_tokens(access, refresh, uid, email)
            meta.pop("pending_uid", None)
            meta.pop("pending_email", None)
            self.write("helper_login", meta)
            return self.result(True, "登录成功，Token 已保存并立即生效，无需再保存或关闭配置页。")
        except HelperLoginError as exc:
            return self.result(False, str(exc))
        finally:
            self.lock.release()


def click_handler(action):
    """MP FormRender's documented event function; uses the host-authenticated API."""
    return r"""async function () {
      if (model.helper_busy) return;
      model.helper_busy = true;
      model.helper_login_type = 'info';
      model.helper_login_message = '正在处理…';
      const uid = String(model.helper_uid || '').trim();
      const email = String(model.helper_email || '').trim();
      const code = String(model.helper_code || '').trim();
      const access = String(model.helper_cookie || '').trim();
      const refresh = String(model.helper_refresh_token || '').trim();
      if ('ACTION' === 'login') model.helper_code = '';
      if ('ACTION' === 'import') { model.helper_cookie = ''; model.helper_refresh_token = ''; }
      try {
        if (!window.MoviePilotAPI) throw new Error('API unavailable');
        const payload = { action: 'ACTION', uid, email,
          site_id: model.site_id ? Number(model.site_id) : null };
        if ('ACTION' === 'login') payload.code = code;
        if ('ACTION' === 'import') { payload.access_token = access; payload.refresh_token = refresh; }
        const result = await window.MoviePilotAPI.post(
          'plugin/' + model.helper_plugin_id + '/helper/auth', payload,
          { feedback: 'silent' });
        model.helper_login_message = result.message;
        model.helper_login_type = result.success ? 'success' : 'warning';
      } catch (_) {
        model.helper_login_type = 'warning';
        model.helper_login_message = '请求未完成，请检查连接。验证码发送或登录不会自动重发；可点击“刷新登录状态”核对已保存状态。';
      } finally { model.helper_busy = false; }
    }""".replace("ACTION", action)


def login_form(plugin_id, state):
    message = ("Token 已保存；可重新获取验证码登录以更换账号。"
               if state.configured else "填写主站 UID 和邮箱，验证码会发到主站私信。")
    def field(model, label, **props):
        return {"component": "VTextField", "props": {"model": model, "label": label,
                "disabled": "{{ helper_busy }}", **props}}
    def button(action, text, disabled):
        return {"component": "VBtn", "text": text, "props": {"type": "button", "color": "primary",
                "variant": "tonal", "class": "mr-2 mb-2", "text": text,
                "disabled": disabled, "loading": "{{ helper_busy }}",
                "onClick": click_handler(action)}}
    content = [
        {"component": "VCardTitle", "text": "Emby 订阅登录"},
        {"component": "VCardText", "content": [
            {"component": "VAlert", "props": {"type": "{{ helper_login_type }}",
                "variant": "tonal", "class": "mb-4", "text": "{{ helper_login_message }}"}},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    field("helper_uid", "主站 UID", inputmode="numeric", maxlength=12, autocomplete="off")]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    field("helper_email", "主站邮箱", type="email", autocomplete="off")]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    field("helper_code", "站内信六位验证码", type="password", maxlength=6,
                          inputmode="numeric", autocomplete="one-time-code")]},
            ]},
            button("send", "发送验证码", "{{ helper_busy || !helper_uid || !helper_email }}"),
            button("login", "登录", "{{ helper_busy || !helper_uid || !helper_email || !/^[0-9]{6}$/.test(helper_code) }}"),
            button("status", "刷新登录状态", "{{ helper_busy }}"),
            {"component": "VAlert", "props": {"type": "info", "variant": "text",
             "text": "发送与登录直接生效，无需保存配置。登录只用于辅助站观影券核验；主站 Cookie 仍从上方选择的 MP 站点读取。其他设置修改后按原方式保存。"}},
        ]},
    ]
    defaults = {"helper_uid": state.pending_uid or state.uid, "helper_email": state.pending_email or state.email,
                "helper_code": "", "helper_busy": False, "helper_plugin_id": plugin_id,
                "helper_login_message": message, "helper_login_type": "success" if state.configured else "info"}
    return {"component": "VCard", "props": {"variant": "outlined", "class": "my-4"}, "content": content}, defaults

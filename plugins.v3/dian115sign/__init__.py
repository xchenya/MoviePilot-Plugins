"""Dian115Sign 2.0.6: MoviePilot V3 browser-native, fail-closed rewrite.

Independent rewrite maintained by xchenya; original feature reference: JinxJie's
plugins.v2/dian115sign. This is not an official release from that author.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from app import schemas
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .browser import BrowserRunner, Options, Outcome, PortalError


class DiagnosticData(BaseModel):
    """Secret-free endpoint diagnostics, not response bodies or request headers."""

    path: str
    status: int
    code: str = ""
    content_type: str = "other"


class RunData(BaseModel):
    """Explicit API response contract shared by run, diagnose and cached status."""

    ok: bool = False
    code: str = "not_started"
    message: str = "尚未运行"
    date: str = ""
    mode: str = "normal"
    already: bool = False
    award: float | None = None
    balance: float | None = None
    streak: int | None = None
    local_streak: int | None = None
    retry_count: int = 0
    uncertain: bool = False
    submitted: bool = False
    checked_at: str = ""
    diagnostics: list[DiagnosticData] = Field(default_factory=list)


class _LocalCompleted(Exception):
    """Internal control flow for an identity-matched same-day completed sign-in."""

    def __init__(self, outcome: Outcome):
        super().__init__("completed")
        self.outcome = outcome


class Dian115Sign(_PluginBase):
    """Single-account plugin; use V3 virtual instances for additional accounts."""

    plugin_name = "癫影自动签到"
    plugin_desc = "V3 浏览器重写测试版：普通签/运气签、登录会话、登录诊断、错误分类及结果通知。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "2.0.6"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya/MoviePilot-Plugins"
    plugin_config_prefix = "dian115sign_"
    plugin_order = 50
    auth_level = 2

    def __init__(self):
        """Only initialize in-memory state; no network, file or DB side effects."""
        super().__init__()
        self._run_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._cancel = threading.Event()
        self._cancel.set()
        self._config: dict[str, Any] = {}
        self._options = Options()
        self._enabled = False
        self._pending_once = False
        self._force_once = False
        self._config_error = ""
        self._trigger = None

    @staticmethod
    def _defaults() -> dict[str, Any]:
        """Old configuration names are retained where their semantics still apply."""
        return {
            "enabled": False, "onlyonce": False, "diagnose_only": True,
            "email": "", "password": "", "token": "", "cookie": "",
            "lucky_mode": False, "cron": "30 9 * * *", "notify": False,
            "use_system_proxy": True, "proxy": "", "timezone": "Asia/Shanghai",
            "timeout": 30, "normal_selector": "", "lucky_selector": "",
            "submit_selector": "", "login_selector": "",
            "reset_session": False, "clear_pending": False,
            "force_once": False, "retry_enabled": False,
            "retry_count": 1, "retry_interval": 60,
        }

    def init_plugin(self, config: dict | None = None) -> None:
        """Cancel old work, snapshot settings, and declare tasks without running them."""
        with self._state_lock:
            self._cancel.set()
            self._cancel = threading.Event()
            merged = {**self._defaults(), **(config or {})}
            self._enabled = bool(merged.get("enabled"))
            self._pending_once = bool(merged.get("onlyonce"))
            self._force_once = bool(merged.get("force_once"))
            self._config_error = ""
            try:
                timeout = max(10, min(60, int(merged.get("timeout") or 30)))
                merged["timeout"] = timeout
                merged["retry_count"] = max(0, min(10, int(merged.get("retry_count") or 1)))
                merged["retry_interval"] = max(10, min(3600, int(merged.get("retry_interval") or 60)))
                merged["timezone"] = str(merged.get("timezone") or "Asia/Shanghai")
                ZoneInfo(merged["timezone"])
                merged["cron"] = str(merged.get("cron") or "30 9 * * *")
                self._trigger = CronTrigger.from_crontab(
                    merged["cron"], timezone=merged["timezone"])
                kwargs = {f.name: merged[f.name] for f in fields(Options)}
                for name in ("email", "token", "cookie", "normal_selector", "lucky_selector",
                             "submit_selector", "login_selector"):
                    kwargs[name] = str(kwargs[name] or "").strip()
                kwargs["password"] = str(kwargs["password"] or "")
                kwargs["lucky_mode"] = bool(kwargs["lucky_mode"])
                # The visible token field accepts a bare token or a complete Cookie string.
                # If it is filled, it takes precedence over the hidden legacy cookie field.
                if kwargs["token"]:
                    kwargs["cookie"] = ""
                self._options = Options(**kwargs)
            except Exception:
                self._config_error = "配置无效：请检查五段 Cron、IANA 时区和超时秒数。"
                self._trigger = None
            self._config = merged
            # Runtime data stays in plugin-owned storage. No host config/table edits.
            try:
                if merged.get("reset_session"):
                    self._session_file().unlink(missing_ok=True)
                if merged.get("clear_pending"):
                    self.del_data("pending_submission")
            except Exception:
                self._config_error = "插件数据目录或状态清理失败；请检查目录权限。"
            changed = any(merged.get(k) for k in ("onlyonce", "force_once", "reset_session", "clear_pending"))
            for name in ("onlyonce", "force_once", "reset_session", "clear_pending"):
                self._config[name] = False
            if changed:
                if self.update_config(dict(self._config)) is False:
                    self._config_error = "配置保存失败；为避免重复执行，已取消一次性任务。"
                    self._pending_once = False
                    self._force_once = False
            if self._config_error:
                logger.error("癫影：" + self._config_error)

    def get_state(self) -> bool:
        """A requested one-shot task may run while periodic execution is disabled."""
        return (self._enabled or self._pending_once or self._force_once) and not bool(self._config_error)

    def get_service(self) -> list[dict[str, Any]]:
        """Both periodic and one-shot scheduling are owned by MoviePilot."""
        if self._config_error or self._cancel.is_set():
            return []
        prefix = self.__class__.__name__
        jobs: list[dict[str, Any]] = []
        if self._enabled and self._trigger:
            jobs.append({"id": prefix + ".Daily", "name": "癫影每日签到/诊断",
                         "trigger": self._trigger, "func": self._run,
                         "kwargs": {"manual": False}})
        if self._pending_once or self._force_once:
            force = bool(self._force_once)
            jobs.append({
                "id": prefix + ".Once",
                "name": "癫影强制重新签到一次" if force else "癫影立即执行一次",
                "trigger": DateTrigger(run_date=datetime.now(
                    ZoneInfo(self._options.timezone)) + timedelta(seconds=3)),
                "func": self._run,
                "kwargs": {"manual": True, "force": force},
            })
        return jobs

    def stop_service(self) -> None:
        """Cooperative cancellation; browser closes in the worker's finally block.

        Do not close a synchronous Playwright object from a different thread.
        Browser calls have bounded timeouts. No private scheduler/thread survives.
        """
        with self._state_lock:
            self._enabled = False
            self._pending_once = False
            self._force_once = False
            self._cancel.set()

    def get_command(self) -> list[dict[str, Any]]:
        """Use instance-specific actions, so virtual instances do not all execute."""
        plugin_id = self.__class__.__name__
        command = "/dian115_sign" if plugin_id == "Dian115Sign" else f"/{plugin_id.lower()}_sign"
        return [{"cmd": command, "event": EventType.PluginAction,
                 "desc": "癫影执行签到或诊断", "category": "插件命令",
                 "data": {"action": plugin_id + ".run"}}]

    @eventmanager.register(EventType.PluginAction)
    def on_command(self, event: Event) -> None:
        """Ignore other plugins' actions and all remote commands while disabled."""
        data = event.event_data or {}
        if self._enabled and data.get("action") == self.__class__.__name__ + ".run":
            self._run(manual=True)

    def get_api(self) -> list[dict[str, Any]]:
        """Mutating actions are POST; viewing status never performs site requests."""
        model = schemas.Response[RunData]
        return [
            {"path": "/signin", "endpoint": self.api_signin, "methods": ["POST"],
             "auth": "bear", "summary": "按配置执行签到或诊断", "response_model": model},
            {"path": "/diagnose", "endpoint": self.api_diagnose, "methods": ["POST"],
             "auth": "bear", "summary": "登录并诊断，不提交签到", "response_model": model},
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"],
             "auth": "bear", "summary": "读取本地缓存结果", "response_model": model},
        ]

    @staticmethod
    def _response(data: dict) -> schemas.Response[RunData]:
        """Use V3's explicit envelope and typed business payload."""
        body = RunData(**data)
        return schemas.Response(success=body.ok, message=body.message, data=body)

    def api_signin(self) -> schemas.Response[RunData]:
        """Run in the host's synchronous endpoint worker; do not bypass diagnosis."""
        return self._response(self._run(manual=True))

    def api_diagnose(self) -> schemas.Response[RunData]:
        """Force read-only sign-in diagnostics for this request."""
        return self._response(self._run(manual=True, diagnose=True))

    def api_status(self) -> schemas.Response[RunData]:
        """Read cached status without starting a browser."""
        return self._response(self.get_data("last_result") or Outcome().to_dict())

    def _session_file(self) -> Path:
        """Resolve a path in the current instance's private data directory."""
        return Path(self.get_data_path()) / "browser-state.json"

    @staticmethod
    def _proxy(config: dict) -> tuple[str, dict | None]:
        """Resolve direct/system/custom egress without logging proxy credentials."""
        raw = str(config.get("proxy") or "").strip()
        if config.get("use_system_proxy"):
            proxy_setting = getattr(settings, "PROXY", None)
            if isinstance(proxy_setting, dict):
                raw = str(proxy_setting.get("host") or "")
            else:
                raw = str(getattr(proxy_setting, "host", "") or "")
            raw = raw or str(getattr(settings, "PROXY_HOST", "") or "")
            raw = raw or os.environ.get("PROXY_HOST", "")
        if not raw:
            return "", None
        try:
            parsed = urlsplit(raw)
            if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname or not parsed.port:
                raise ValueError()
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            value = {"server": f"{parsed.scheme}://{host}:{parsed.port}"}
            if parsed.username:
                value["username"] = unquote(parsed.username)
            if parsed.password:
                value["password"] = unquote(parsed.password)
            return raw, value
        except Exception:
            raise PortalError("proxy_invalid", "代理格式无效；应为 http(s)://主机:端口 或 socks5://主机:端口。") from None

    @staticmethod
    def _number_text(value: float | int | None, signed: bool = False) -> str:
        """Format score values without trailing .0."""
        if value is None:
            return "未取得"
        numeric = float(value)
        text = str(int(numeric)) if numeric.is_integer() else f"{numeric:g}"
        if signed and numeric > 0:
            return "+" + text
        return text

    def _update_local_streak(self, result: Outcome, identity: str) -> None:
        """Maintain plugin-local consecutive days; never present it as site data."""
        if not identity or not result.ok or result.code not in {"signed", "already_signed"}:
            return
        try:
            today = datetime.fromisoformat(result.date).date()
        except (TypeError, ValueError):
            return
        state = self.get_data("local_streak") or {}
        count = 1
        if isinstance(state, dict) and state.get("identity") == identity:
            try:
                last = datetime.fromisoformat(str(state.get("last_date") or "")).date()
                old_count = max(int(state.get("count") or 0), 0)
                if last == today:
                    count = max(old_count, 1)
                elif last == today - timedelta(days=1):
                    count = old_count + 1
            except (TypeError, ValueError):
                count = 1
        result.local_streak = count
        self.save_data("local_streak", {
            "identity": identity,
            "last_date": result.date,
            "count": count,
        })

    def _send_result_notification(self, result: Outcome, diagnostic: bool) -> None:
        """Send one fixed-title, separator-based notification template."""
        title = "癫影签到"
        checked = "未取得"
        try:
            checked = datetime.fromisoformat(
                str(result.checked_at or "").replace("Z", "+00:00")
            ).strftime("%H:%M:%S")
        except (TypeError, ValueError):
            raw = str(result.checked_at or "")
            if "T" in raw:
                checked = raw.split("T", 1)[1][:8]

        if diagnostic:
            status = "✅诊断正常" if result.ok else "❌诊断失败"
        elif result.ok and result.already:
            status = "✅今日已签到"
        elif result.ok:
            status = "✅签到成功"
        else:
            status = "❌签到失败"

        lines = [
            "━━━━━━━━━━━━━━",
            f"✨ 状态：{status}",
            "━━━━━━━━━━━━━━",
        ]
        if result.ok:
            lines.extend([
                "📊 数据统计",
                f"💰 当前积分：{self._number_text(result.balance)}",
                f"📆 本地连续签到：{self._number_text(result.local_streak)}"
                    + ("天" if result.local_streak is not None else ""),
            ])
            if result.ok and not result.already and not diagnostic:
                lines.insert(-2, f"🎁 本次积分：{self._number_text(result.award, signed=True)}")
        else:
            lines.extend([
                "📊 任务信息",
                f"🧩 错误代码：{result.code or 'unknown'}",
                f"📝 失败原因：{result.message or '未知错误'}",
                f"🔁 已重试：{int(result.retry_count or 0)}次",
            ])
        lines.extend([
            "━━━━━━━━━━━━━━",
            f"🕐 签到时间：{checked}",
        ])
        self.post_message(
            mtype=NotificationType.Plugin,
            title=title,
            text="\n".join(lines),
        )

    @staticmethod
    def _retryable(result: Outcome) -> bool:
        """Retry only transient failures that occurred before an uncertain write."""
        if result.ok or result.submitted or result.uncertain:
            return False
        return result.code in {
            "browser_timeout", "timeout", "browser_error",
            "proxy_failed", "dns_failed", "server_error",
            "account_unconfirmed", "login_timeout", "runtime_error",
        }

    def _run(self, manual: bool = False, diagnose: bool | None = None,
             force: bool = False) -> dict:
        """One shared execution entry for services, commands and POST APIs."""
        if not self._run_lock.acquire(blocking=False):
            return Outcome(code="busy", message="已有任务运行，已跳过并发请求。").to_dict()
        try:
            with self._state_lock:
                cancel = self._cancel
                config, options = dict(self._config), self._options
                if self._config_error:
                    return Outcome(code="config_invalid", message=self._config_error).to_dict()
                if cancel.is_set() or (not manual and not self._enabled):
                    return Outcome(code="disabled", message="插件已停用或任务已取消。").to_dict()
                if manual:
                    self._pending_once = False
                    self._force_once = False
            diagnostic = bool(config.get("diagnose_only", True)) if diagnose is None else diagnose
            logger.info(f"癫影开始{'诊断（不签到）' if diagnostic else '签到'}，模式：{options.mode}")
            result: Outcome
            try:
                raw_proxy, proxy = self._proxy(config)
                identity = options.identity(raw_proxy)
                state_file = self._session_file()
                completed = self.get_data("completed_day") or {}
                same_day_completed = (
                    isinstance(completed, dict)
                    and completed.get("date") == options.today()
                    and completed.get("identity") == identity
                )
                local_duplicate_ready = (
                    same_day_completed
                    and completed.get("duplicate_verified") is True
                    and completed.get("balance") is not None
                )
                if not diagnostic and not force and local_duplicate_ready:
                    result = Outcome(
                        ok=True,
                        code="already_signed",
                        message="本地记录确认今日已签到，无需再次访问站点",
                        date=options.today(),
                        mode=options.mode,
                        already=True,
                        balance=completed.get("balance"),
                        local_streak=completed.get("local_streak"),
                        checked_at=datetime.now(
                            ZoneInfo(options.timezone)
                        ).isoformat(timespec="seconds"),
                    )
                    logger.info("癫影：本地重复签到状态已确认，跳过站点请求")
                    raise _LocalCompleted(result)

                # The first duplicate check of the day must be confirmed by the site
                # toast. A force-once run also bypasses the local duplicate shortcut.
                verify_duplicate = bool(force or not (
                    same_day_completed and completed.get("duplicate_verified") is True
                ))

                def current() -> bool:
                    """Never publish old-generation results after a configuration reload."""
                    return self._cancel is cancel and not cancel.is_set()

                def load_state() -> dict | None:
                    """Reject cached credentials after account or proxy changes."""
                    try:
                        payload = json.loads(state_file.read_text(encoding="utf-8"))
                        if payload.get("identity") == identity and isinstance(payload.get("state"), dict):
                            return payload["state"]
                    except (OSError, ValueError, AttributeError):
                        pass
                    return None

                def save_state(state: dict) -> None:
                    """Atomic 0600 session file; never write tokens back into source."""
                    with self._state_lock:
                        if not current():
                            return
                        state_file.parent.mkdir(parents=True, exist_ok=True)
                        temp = state_file.with_suffix(".tmp")
                        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        try:
                            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                                json.dump({"identity": identity, "state": state}, stream, ensure_ascii=False)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.chmod(temp, 0o600)
                            os.replace(temp, state_file)
                        finally:
                            temp.unlink(missing_ok=True)

                def pending() -> bool:
                    """An indeterminate earlier write must be checked before another."""
                    value = self.get_data("pending_submission") or {}
                    # A proxy/token change must not bypass a same-day pending write.
                    return value.get("date") == options.today()

                def mark_pending() -> bool:
                    """Persist the intent BEFORE allowing the browser's POST."""
                    with self._state_lock:
                        if not current():
                            return False
                        value = {"date": options.today(), "identity": identity}
                        try:
                            self.save_data("pending_submission", value)
                            return self.get_data("pending_submission") == value
                        except Exception:
                            return False

                # Delay browser imports/launch until an explicit task actually runs.
                from app.sdk.browser import launch_browser_context
                max_retry = (
                    int(config.get("retry_count") or 0)
                    if config.get("retry_enabled") and not diagnostic
                    else 0
                )
                retry_interval = int(config.get("retry_interval") or 60)
                retry_count = 0
                while True:
                    runner = BrowserRunner(
                        options, launch_browser_context, cancel, load_state,
                        save_state, pending, mark_pending, proxy
                    )
                    result = runner.run(
                        diagnose=diagnostic,
                        verify_duplicate=verify_duplicate,
                    )
                    result.retry_count = retry_count
                    if (not self._retryable(result)) or retry_count >= max_retry:
                        break
                    retry_count += 1
                    logger.warning(
                        f"癫影：[{result.code}] {result.message}；"
                        f"{retry_interval} 秒后进行第 {retry_count} 次重试"
                    )
                    if cancel.wait(retry_interval):
                        result = Outcome(
                            code="cancelled",
                            message="插件已停用或配置已更新，取消失败重试。",
                            date=options.today(),
                            mode=options.mode,
                            retry_count=retry_count,
                            checked_at=datetime.now(
                                ZoneInfo(options.timezone)
                            ).isoformat(timespec="seconds"),
                        )
                        break

                # Never replace a same-day known balance with an empty duplicate result.
                if result.ok and result.balance is None and same_day_completed:
                    previous_balance = completed.get("balance")
                    if previous_balance is not None:
                        result.balance = previous_balance
                    else:
                        history = self.get_data("run_history") or []
                        if isinstance(history, list):
                            for item in reversed(history):
                                if (isinstance(item, dict)
                                        and item.get("date") == result.date
                                        and item.get("ok") is True
                                        and item.get("balance") is not None):
                                    result.balance = item.get("balance")
                                    break
                self._update_local_streak(result, identity)
                with self._state_lock:
                    if current():
                        try:
                            if result.ok and (result.already or not diagnostic):
                                self.del_data("pending_submission")
                            elif result.submitted and not result.uncertain:
                                self.del_data("pending_submission")
                            if result.ok and (result.already or result.code == "signed"):
                                saved_balance = result.balance
                                if saved_balance is None and same_day_completed:
                                    saved_balance = completed.get("balance")
                                self.save_data("completed_day", {
                                    "date": result.date,
                                    "identity": identity,
                                    "balance": saved_balance,
                                    "streak": result.streak,
                                    "local_streak": result.local_streak,
                                    "duplicate_verified": bool(result.already),
                                })
                            history = self.get_data("run_history") or []
                            history = history if isinstance(history, list) else []
                            self.save_data("run_history", (history + [result.to_dict()])[-100:])
                        except Exception:
                            result.diagnostics.append({"path": "plugin.storage", "status": 0,
                                                       "code": "storage_failed", "content_type": "other"})
                            logger.warning("癫影：执行结果写入本地缓存失败；不会因此重做签到。")
            except _LocalCompleted as completed:
                result = completed.outcome
                try:
                    self._update_local_streak(result, identity)
                except Exception:
                    logger.warning("癫影：本地连续签到统计更新失败。")
            except PortalError as error:
                result = Outcome(code=error.code, message=str(error))
            except Exception as error:
                result = Outcome(code="runtime_error", message=f"插件执行异常（{type(error).__name__}）；未输出敏感异常详情。")
            if not cancel.is_set():
                with self._state_lock:
                    if self._cancel is cancel and not cancel.is_set():
                        try:
                            self.save_data("last_result", result.to_dict())
                        except Exception:
                            logger.warning("癫影：结果缓存保存失败；不会因此重新签到。")
                (logger.info if result.ok else logger.warning)(
                    f"癫影：[{result.code}] {result.message}")
                if config.get("notify"):
                    try:
                        self._send_result_notification(result, diagnostic)
                    except Exception:
                        logger.warning("癫影：通知发送失败；不会因此重新签到。")
            return result.to_dict()
        finally:
            self._run_lock.release()

    def get_form(self) -> tuple[list[dict], dict]:
        """Return the compact card-based configuration UI."""
        from .config_form import build_form
        return build_form()

    def get_page(self) -> list[dict]:
        """Render cached account/run data in a compact dashboard; never access the site."""
        result = self.get_data("last_result") or {}
        history = self.get_data("run_history") or []
        history = history if isinstance(history, list) else []
        message = self._config_error or result.get("message") or "尚未执行；请先运行一次诊断。"

        def metric(icon: str, label: str, value: str, color: str) -> dict:
            return {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "h-100"},
                "content": [{
                    "component": "VCardText",
                    "props": {"class": "text-center pa-3"},
                    "content": [
                        {"component": "VIcon", "props": {"color": color, "size": "28", "class": "mb-2"}, "text": icon},
                        {"component": "div", "props": {"class": f"text-h6 font-weight-bold text-{color}"}, "text": value},
                        {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": label},
                    ],
                }],
            }

        def short_time(value: Any) -> str:
            raw = str(value or "")
            if not raw:
                return "—"
            try:
                return datetime.fromisoformat(
                    raw.replace("Z", "+00:00")
                ).strftime("%H:%M:%S")
            except ValueError:
                return raw.split("T", 1)[-1][:8] if "T" in raw else raw[-8:]

        code = str(result.get("code") or "not_started")
        ok = bool(result.get("ok"))
        balance = result.get("balance")
        streak = result.get("local_streak")
        award = result.get("award")
        checked = short_time(result.get("checked_at"))
        today_state = (
            "已签到" if result.get("already") else
            "签到成功" if code == "signed" else
            "诊断正常" if code == "diagnostic_ok" else
            "待确认" if result.get("uncertain") else
            "未完成"
        )

        page: list[dict] = [
            {"component": "VAlert", "props": {
                "type": "success" if ok else ("warning" if result.get("uncertain") else "info"),
                "variant": "tonal", "class": "mb-3", "text": message,
            }},
            {"component": "VRow", "props": {"dense": True}, "content": [
                {"component": "VCol", "props": {"cols": 6, "md": 3},
                 "content": [metric("mdi-wallet-outline", "当前积分",
                                    str(balance if balance is not None else "—"), "info")]},
                {"component": "VCol", "props": {"cols": 6, "md": 3},
                 "content": [metric("mdi-fire", "本地连续签到",
                                    f"{streak} 天" if streak is not None else "—", "success")]},
                {"component": "VCol", "props": {"cols": 6, "md": 3},
                 "content": [metric("mdi-calendar-check", "今日状态", today_state,
                                    "success" if ok else "warning")]},
                {"component": "VCol", "props": {"cols": 6, "md": 3},
                 "content": [metric("mdi-clock-outline", "最近执行",
                                    checked, "primary")]},
            ]},
        ]

        rows = []
        for item in reversed(history[-10:]):
            if not isinstance(item, dict):
                continue
            item_award = item.get("award")
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": short_time(item.get("checked_at"))},
                    {"component": "td", "props": {"class": "text-center"},
                     "text": "运气签" if item.get("mode") == "lucky" else "普通签"},
                    {"component": "td", "props": {"class": "text-center"},
                     "text": str(item.get("code") or "—")},
                    {"component": "td", "props": {"class": "text-center"},
                     "text": (f"{item_award:+g}" if isinstance(item_award, (int, float)) else "—")},
                    {"component": "td", "props": {"class": "text-center"},
                     "text": str(item.get("balance") if item.get("balance") is not None else "—")},
                ],
            })

        table_body = rows or [{
            "component": "tr",
            "content": [{"component": "td", "props": {"colspan": 5, "class": "text-center text-medium-emphasis"},
                         "text": "暂无执行记录"}],
        }]
        page.append({
            "component": "VCard",
            "props": {"class": "mt-3", "variant": "tonal"},
            "content": [
                {"component": "VCardTitle", "props": {"class": "d-flex align-center"}, "content": [
                    {"component": "VIcon", "props": {"color": "primary", "class": "mr-2"}, "text": "mdi-history"},
                    {"component": "span", "text": "最近执行"},
                ]},
                {"component": "VDivider"},
                {"component": "VCardText", "props": {"class": "pa-2"}, "content": [{
                    "component": "VTable", "props": {"density": "comfortable"}, "content": [
                        {"component": "thead", "content": [{"component": "tr", "content": [
                            {"component": "th", "text": "时间"},
                            {"component": "th", "props": {"class": "text-center"}, "text": "模式"},
                            {"component": "th", "props": {"class": "text-center"}, "text": "结果"},
                            {"component": "th", "props": {"class": "text-center"}, "text": "积分"},
                            {"component": "th", "props": {"class": "text-center"}, "text": "余额"},
                        ]}]},
                        {"component": "tbody", "content": table_body},
                    ],
                }]},
            ],
        })

        diagnostics = result.get("diagnostics") or []
        if isinstance(diagnostics, list) and diagnostics:
            diagnostic_rows = []
            for row in diagnostics[-8:]:
                if not isinstance(row, dict):
                    continue
                diagnostic_rows.append({
                    "component": "tr",
                    "content": [
                        {"component": "td", "text": str(row.get("path") or "—")},
                        {"component": "td", "props": {"class": "text-center"}, "text": str(row.get("status") or "—")},
                        {"component": "td", "text": str(row.get("code") or "—")},
                    ],
                })
            page.append({
                "component": "VCard",
                "props": {"class": "mt-3", "variant": "outlined"},
                "content": [
                    {"component": "VCardTitle", "props": {"class": "text-subtitle-1"}, "text": "诊断信息"},
                    {"component": "VCardText", "props": {"class": "pa-2"}, "content": [{
                        "component": "VTable", "props": {"density": "compact"}, "content": [
                            {"component": "thead", "content": [{"component": "tr", "content": [
                                {"component": "th", "text": "接口"},
                                {"component": "th", "props": {"class": "text-center"}, "text": "HTTP"},
                                {"component": "th", "text": "代码"},
                            ]}]},
                            {"component": "tbody", "content": diagnostic_rows},
                        ],
                    }]},
                ],
            })
        return page

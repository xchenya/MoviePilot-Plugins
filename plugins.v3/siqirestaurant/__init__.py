# SPDX-License-Identifier: GPL-3.0-only
"""思齐餐厅：V3 原生面板、服务器端厨房状态和受限的站点操作。"""
import copy
import hashlib
import math
import random
import re
import threading
import time
from datetime import datetime
from functools import wraps
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field

from app.sdk.plugin import _PluginBase
from app.sdk.config import settings
from app.sdk.scheduler import update_plugin_job
from app.db.oper.site import SiteOper
from app.schemas import NotificationType


class RestaurantResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool
    message: str = ""
    restaurant: dict[str, Any] = Field(default_factory=dict)
    kitchen: list[dict[str, Any]] = Field(default_factory=list)
    cleaning: dict[str, float] = Field(default_factory=dict)
    server_now: float = 0
    uncertain: bool = False
    requires_confirmation: bool = False
    restaurants: list[dict[str, Any]] = Field(default_factory=list)
    candidate: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    automation: dict[str, Any] = Field(default_factory=dict)


class PublicConfig(BaseModel):
    enabled: bool = False
    use_proxy: bool = False
    cookie_configured: bool = False
    site_configured: bool = False
    auto_enabled: bool = False
    cron: str = "0 8 * * *"
    run_once: bool = False
    auto_purchase: bool = True
    daily_budget: int = 5000
    magic_reserve: int = 10000
    auto_visit: bool = False
    visit_targets: list[str] = Field(default_factory=list)
    notify: bool = False


class ConfigResult(BaseModel):
    success: bool
    message: str = ""
    config: PublicConfig


class RestaurantError(Exception):
    pass


class RestaurantReadError(RestaurantError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def serialized(func):
    @wraps(func)
    def call(self, *args, **kwargs):
        with self._lock:
            try:
                return func(self, *args, **kwargs)
            except RestaurantError as exc:
                return self._result(False, str(exc))
    return call


class SiqiRestaurant(_PluginBase):
    plugin_name = "思齐餐厅"
    plugin_desc = "思齐餐厅后台自动经营：每日开业、并行烹饪、及时上菜、限额补货及原生管理面板。"
    plugin_icon = "https://si-qi.xyz/favicon.ico"
    plugin_version = "1.4.1"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya"
    plugin_config_prefix = "siqirestaurant_"
    plugin_order = 30
    auth_level = 2

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self._siteoper = SiteOper()
        self._config = {}
        self._snapshot = {}
        self._runtime = {}
        self._last_fetch = 0
        self._stopped = False
        self._next_auto = 0
        self._stop_auto = threading.Event()

    def init_plugin(self, config: dict = None):
        with self._lock:
            values = config or {}
            self._config = {"enabled": self._bool(values.get("enabled", False)),
                            "use_proxy": self._bool(values.get("use_proxy", False)),
                            "cookie": str(values.get("cookie") or "").strip()}
            self._config.update(self._auto_config(values))
            self._runtime = self.get_data("runtime") or {}
            self._snapshot = {}
            self._last_fetch = 0
            self._stopped = False
            self._stop_auto.clear()
            self._next_auto = 0
            # 正在经营的任务跨重启续跑，空闲状态只等 Cron，不再轮询站点。
            if self._automatic_enabled() and (self._runtime.get("pending") or
                    any(s.get("status") != "idle" for s in self._runtime.get("kitchen", []))):
                self.start_automation()
            if self._bool(values.get("run_once", False)):
                self.update_config(self._config)
                self.start_automation(once=True)

    def _auto_config(self, values):
        cron = str(values.get("cron") or "").strip()
        if not cron:
            # 旧版单个时间转换为 Cron；新安装默认每天 08:00，时区跟随 MP。
            start = str(values.get("start_time", "08:00"))
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start):
                raise RestaurantError("旧开业时间格式无效，请设置 Cron")
            hour, minute = map(int, start.split(":"))
            cron = f"{minute} {hour} * * *"
        try:
            CronTrigger.from_crontab(cron, timezone=settings.TZ)
        except (ValueError, TypeError) as exc:
            raise RestaurantError("Cron 格式无效，请使用 MP 的五段 Cron 表达式") from exc
        return {"auto_enabled": self._bool(values.get("auto_enabled", False)),
                "auto_visit": self._bool(values.get("auto_visit", False)),
                "visit_targets": self._visit_targets(values.get("visit_targets", [])),
                "notify": self._bool(values.get("notify", False)),
                "auto_purchase": self._bool(values.get("auto_purchase", True)),
                "cron": cron, "run_once": False,
                "daily_budget": self._int(values.get("daily_budget", 5000), "每日采购预算", 0, 1000000),
                "magic_reserve": self._int(values.get("magic_reserve", 10000), "保留魔力", 0, 1000000000)}

    def _visit_targets(self, values):
        if not isinstance(values, list) or len(values) > 3:
            raise RestaurantError("下馆子名单最多填写 3 位用户名")
        names = []
        for value in values:
            if not isinstance(value, str):
                raise RestaurantError("下馆子名单须为用户名列表")
            if value.strip():
                name = self._username({"target_username": value})
                if name.casefold() in {n.casefold() for n in names}:
                    raise RestaurantError("下馆子名单不能重复")
                names.append(name)
        return names

    def _automatic_enabled(self):
        return self._config.get("auto_enabled") or self._config.get("auto_visit")

    @staticmethod
    def _bool(value):
        return value is True or value == 1 or str(value).lower() in {"true", "yes", "on"}

    def get_state(self):
        return self._config.get("enabled", False)

    def get_command(self):
        return []

    def get_service(self):
        if not self.get_state():
            return []
        jobs = []
        if self._automatic_enabled():
            jobs.append({"id": f"{self.__class__.__name__}.schedule", "name": "思齐餐厅定时检查",
                         "trigger": CronTrigger.from_crontab(self._config["cron"], timezone=settings.TZ),
                         "func": self.start_automation,
                         "kwargs": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 60}})
        if self._automatic_enabled() or self._runtime.get("run", {}).get("active"):
            jobs.append({"id": f"{self.__class__.__name__}.automation", "name": "思齐餐厅营业服务",
                 "trigger": IntervalTrigger(seconds=1), "func": self.run_automation,
                 "kwargs": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 10}})
        return jobs

    def start_automation(self, once=False):
        """Cron / 保存后运行一次仅唤醒工作任务，重复触发不会重开或重复下馆子。"""
        with self._lock:
            if self._stopped or not self.get_state() or not (once or self._automatic_enabled()):
                return
            run = self._runtime.setdefault("run", {})
            if run.get("active"):
                return
            run.update(active=True, operate=bool(once or self._config.get("auto_enabled")),
                       visits=bool(self._config.get("auto_visit")), once=bool(once), failures=0)
            self._next_auto = 0
            self._save()

    def get_form(self):
        return None, self.api_config()

    def get_page(self):
        return []

    def get_render_mode(self):
        return "vue", f"dist/assets-v{self.plugin_version}"

    def stop_service(self):
        self._stopped = True
        self._stop_auto.set()

    def get_api(self):
        definitions = [
            ("/config", "GET", self.api_config, PublicConfig, "读取配置（不返回 Cookie）"),
            ("/config", "POST", self.api_save_config, ConfigResult, "保存配置"),
            ("/state", "GET", self.api_state, RestaurantResult, "读取厨房和餐厅状态"),
            ("/refresh", "POST", self.api_refresh, RestaurantResult, "刷新站点状态"),
            ("/action", "POST", self.api_action, RestaurantResult, "执行餐厅操作"),
            ("/tick", "POST", self.api_tick, RestaurantResult, "处理倒计时及页面员工服务"),
            ("/resolve", "POST", self.api_resolve, RestaurantResult, "核对后解除不确定写入锁"),
        ]
        return [{"path": path, "methods": [method], "endpoint": endpoint,
                 "auth": "bear", "response_model": model, "summary": summary}
                for path, method, endpoint, model, summary in definitions]

    def api_config(self) -> dict:
        site = self._siteoper.get_by_domain("si-qi.xyz")
        return {"enabled": self.get_state(), "use_proxy": self._config.get("use_proxy", False),
                "cookie_configured": bool(self._config.get("cookie") or getattr(site, "cookie", None)),
                "site_configured": bool(site), **self._auto_config(self._config)}

    def api_save_config(self, payload: dict = None) -> dict:
        payload = payload or {}
        if any(payload.get(key) is False for key in ("auto_enabled", "auto_visit", "enabled")):
            self._stop_auto.set()
        with self._lock:
            config = dict(self._config)
            for key in ("enabled", "use_proxy"):
                if key in payload:
                    config[key] = self._bool(payload[key])
            if payload.get("clear_cookie") is True:
                config["cookie"] = ""
            elif str(payload.get("cookie") or "").strip():
                config["cookie"] = str(payload["cookie"]).strip()
            try:
                config.update(self._auto_config({**config, **payload}))
            except RestaurantError as exc:
                self._stop_auto.clear()
                return {"success": False, "message": str(exc), "config": self.api_config()}
            self.update_config(config)
            self._config = config
            run_once = self._bool(payload.get("run_once", False))
            run = self._runtime.setdefault("run", {})
            if not self.get_state() or (not run.get("once") and not self._automatic_enabled()):
                run["active"] = False
            if not run.get("once"):
                run["operate"] = bool(config.get("auto_enabled"))
            run["visits"] = bool(config.get("auto_visit"))
            self._snapshot = {}
            self._last_fetch = 0
            self._next_auto = 0
            self._stop_auto.clear()
            if run_once:
                self.start_automation(once=True)
            self._save()
        # 宿主统一管理任务，配置保存后立即生效，停用时移除原任务。
        try:
            update_plugin_job(self.__class__.__name__)
        except Exception:
            return {"success": False, "message": "配置已保存，但定时任务更新失败，请重启 MP 后检查托管状态", "config": self.api_config()}
        message = "配置已保存"
        if run_once:
            message += "；已安排运行一次，开关已自动关闭" if self.get_state() else "；插件未启用，本次未运行"
        return {"success": True, "message": message, "config": self.api_config()}

    def _credentials(self):
        site = self._siteoper.get_by_domain("si-qi.xyz")
        cookie = self._config.get("cookie") or getattr(site, "cookie", "")
        if not cookie or str(cookie).strip().lower() == "cookie":
            raise RestaurantError("请在 MP 站点管理添加思齐并更新 Cookie，或在插件配置中填写 Cookie")
        # 不接受用户提供的任意转发地址，Cookie 只发往明确的思齐 HTTPS 源。
        source = urlsplit(str(getattr(site, "url", "") or "https://si-qi.xyz"))
        if (source.scheme != "https" or source.hostname != "si-qi.xyz"
                or source.port not in (None, 443) or source.username or source.password):
            raise RestaurantError("思齐站点地址必须为 https://si-qi.xyz")
        ua = getattr(site, "ua", None) or "Mozilla/5.0"
        return str(cookie), ua

    def _context(self):
        if self._stopped or not self.get_state():
            raise RestaurantError("请先启用餐厅插件")
        cookie, _ = self._credentials()
        context = hashlib.sha256(cookie.encode()).hexdigest()
        if self._runtime.get("context") != context:
            pending = copy.deepcopy(self._runtime.get("pending"))
            if pending:
                pending["stove"] = None  # 新凭据的厨房已隔离，未知请求仍须人工核对。
            self._runtime = {"context": context, "day": "", "kitchen": [], "cleaning": {},
                             "pending": pending, "receipts": self._runtime.get("receipts", {}), "events": [],
                             "pending_purchase": self._runtime.get("pending_purchase"),
                             "run": self._runtime.get("run", {}),
                             "automation": self._runtime.get("automation", {}),
                             "auto_visits": self._runtime.get("auto_visits", {}),
                             "notifications": self._runtime.get("notifications", {})}
            self._snapshot = {}
            self._last_fetch = 0
            self._save()

    def _save(self):
        self.save_data("runtime", copy.deepcopy(self._runtime))

    def _event(self, action, message, success):
        items = self._runtime.setdefault("events", [])
        items.insert(0, {"time": time.time(), "action": action, "message": message, "success": success})
        del items[100:]

    def _request(self, action, payload=None, read=False):
        cookie, ua = self._credentials()
        label = {"fetch": "读取餐厅状态", "inspect_restaurant_target": "查询下馆子目标",
                 "list_visitable_restaurants": "读取随机餐馆",
                 "purchase_ingredient": "购买食材", "start_session": "开始营业",
                 "serve_customer": "上菜", "customer_left": "顾客离席",
                 "discard_dish": "丢弃菜品", "visit_restaurant": "下馆子"}.get(action, "餐厅操作")
        cookie_source = "插件覆盖" if self._config.get("cookie") else "MP 站点"
        route = "MP 代理" if self._config.get("use_proxy") else "系统网络（含环境代理）"
        # 空闲查询允许较慢线路；营业、在制订单及开业结果待确认时保持短超时。
        live = (self._snapshot.get("state", {}).get("session_status") == "open"
                or self._runtime.get("run", {}).get("live")
                or (self._runtime.get("pending") or {}).get("action") == "start_session"
                or any(s.get("status") != "idle" for s in self._runtime.get("kitchen", [])))
        timeout = (5, 15) if read and not live else (3, 5)
        headers = {"Cookie": cookie, "User-Agent": ua, "Referer": "https://si-qi.xyz/siqi_restaurant.php",
                   "Accept": "application/json", "Origin": "https://si-qi.xyz"}
        options = dict(headers=headers, timeout=timeout, allow_redirects=False,
                       proxies=settings.PROXY if self._config.get("use_proxy") else None)
        try:
            if action == "fetch":
                response = requests.get("https://si-qi.xyz/siqi_restaurant.php",
                                        params={"action": "fetch"}, **options)
            else:
                # 与网页 FormData 相同的 multipart 表单，无自动重试。
                data = {"action": action, **(payload or {})}
                response = requests.post("https://si-qi.xyz/siqi_restaurant.php",
                                         files={key: (None, str(value)) for key, value in data.items()}, **options)
            status = response.status_code
            if 300 <= status < 400:
                raise RestaurantReadError(f"站点 HTTP {status} 重定向，请核对 Cookie 或站点登录/验证页面")
            if status in (401, 403):
                raise RestaurantReadError(f"站点 HTTP {status} 拒绝访问，请核对 Cookie、User-Agent 和站点防护")
            if status == 429:
                raise RestaurantReadError("站点 HTTP 429 请求过于频繁，请稍后再试", retryable=True)
            if status != 200:
                raise RestaurantReadError(f"站点 HTTP {status}", retryable=500 <= status < 600)
            try:
                result = response.json()
            except ValueError:
                # 只识别响应类型，不记录正文、跳转地址或第三方异常文本。
                html = ("text/html" in response.headers.get("Content-Type", "").lower()
                        or response.content.lstrip().startswith(b"<"))
                reason = ("站点返回 HTML 页面，可能是登录或验证页面，请核对 Cookie 和 User-Agent"
                          if html else "站点返回非 JSON 数据，请稍后刷新并核对站点响应")
                raise RestaurantReadError(reason) from None
            if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
                raise RestaurantReadError("站点 JSON 格式异常，缺少有效 success 字段")
            return result
        except (requests.RequestException, RestaurantReadError) as exc:
            retryable = False
            if isinstance(exc, RestaurantReadError):
                reason, retryable = str(exc), exc.retryable
            elif isinstance(exc, requests.exceptions.ProxyError):
                reason, retryable = "代理连接失败，请检查代理地址和连通性", True
            elif isinstance(exc, requests.exceptions.SSLError):
                reason = "TLS 证书校验或握手失败，请检查证书、系统时间和代理"
            elif isinstance(exc, requests.exceptions.ConnectTimeout):
                reason, retryable = f"连接超时（{timeout[0]} 秒）", True
            elif isinstance(exc, requests.exceptions.ReadTimeout):
                reason, retryable = f"响应读取超时（{timeout[1]} 秒）", True
            elif isinstance(exc, requests.Timeout):
                reason, retryable = "请求超时", True
            elif isinstance(exc, requests.ConnectionError):
                reason, retryable = "连接失败，请检查 DNS、网络或环境代理", True
            else:
                reason = "请求发送失败，请检查 Cookie、User-Agent 和代理配置格式"
            message = f"{label}失败：{reason}；Cookie 来源：{cookie_source}；网络：{route}"
            if not read:
                raise RestaurantError(f"{message}；写入结果不明，正在读回核对，原请求不会重发") from None
            raise RestaurantReadError(message, retryable=retryable) from None

    @staticmethod
    def _empty(index):
        return {"index": index, "dish_key": "", "tool_key": "", "ingredients": {},
                "status": "idle", "ready_at": 0}

    def _merge(self, response):
        for key in ("user", "state", "config", "inventory", "staff", "visits", "logs"):
            if key in response:
                self._snapshot[key] = copy.deepcopy(response[key])

    def _refresh(self):
        result = self._request("fetch", read=True)
        if not result["success"]:
            raise RestaurantError(str(result.get("message") or "餐厅数据读取失败"))
        if not all(isinstance(result.get(key), dict) for key in ("state", "config", "inventory")):
            raise RestaurantError("餐厅响应缺少 state/config/inventory，请核对站点版本")
        self._merge(result)
        self._last_fetch = time.time()
        state = self._snapshot["state"]
        day = str(state.get("session_date") or state.get("date") or
                  datetime.now(ZoneInfo("Asia/Shanghai")).date())
        if self._runtime.get("day") != day:
            self._runtime["day"] = day
            self._runtime["kitchen"] = []
            self._runtime["cleaning"] = {}
        count = min(50, max(1, int(state.get("unlocked", {}).get("stations") or 1)))
        old = {s["index"]: s for s in self._runtime.get("kitchen", [])}
        self._runtime["kitchen"] = [old.get(i) or self._empty(i) for i in range(1, count + 1)]
        self._reconcile_pending()
        self._save()

    def _ensure_fresh(self, force=False):
        self._context()
        if force or not self._snapshot or time.time() - self._last_fetch > 5:
            self._refresh()
        self._advance()

    def _advance(self):
        now = time.time()
        changed = False
        for stove in self._runtime.get("kitchen", []):
            if stove["status"] == "cooking" and now >= stove["ready_at"]:
                stove["status"] = "ready"
                changed = True
        cleaning = self._runtime.setdefault("cleaning", {})
        for key, until in list(cleaning.items()):
            if now >= until:
                del cleaning[key]
                changed = True
        if changed:
            self._save()

    def _result(self, success=True, message="", **extra):
        return {"success": success, "message": message, "restaurant": copy.deepcopy(self._snapshot),
                "kitchen": copy.deepcopy(self._runtime.get("kitchen", [])),
                "cleaning": dict(self._runtime.get("cleaning", {})), "server_now": time.time(),
                "uncertain": bool(self._runtime.get("pending") or self._runtime.get("pending_purchase")),
                "automation": {**copy.deepcopy(self._runtime.get("automation", {})),
                               "enabled": bool(self.get_state() and self._config.get("auto_enabled")),
                               "active": bool(self.get_state() and (self._automatic_enabled() or
                                              self._runtime.get("run", {}).get("active"))),
                               "running": bool(self._runtime.get("run", {}).get("active")),
                               "visit_enabled": bool(self.get_state() and self._config.get("auto_visit")),
                               "visits": copy.deepcopy(self._runtime.get("auto_visits", {})),
                               "daily_budget": self._config.get("daily_budget", 5000),
                               "next_check": self._next_auto},
                "events": copy.deepcopy(self._runtime.get("events", [])), **extra}

    @serialized
    def api_state(self) -> dict:
        self._ensure_fresh()
        return self._result()

    @serialized
    def api_refresh(self) -> dict:
        self._ensure_fresh(force=True)
        return self._result(message="状态已刷新")

    @staticmethod
    def _int(value, name, minimum=1, maximum=10000):
        if isinstance(value, bool) or not str(value).isdigit():
            raise RestaurantError(f"{name}必须为整数")
        result = int(value)
        if not minimum <= result <= maximum:
            raise RestaurantError(f"{name}须在 {minimum}–{maximum} 之间")
        return result

    def _stove(self, value):
        index = self._int(value, "灶台编号", maximum=50)
        stove = next((s for s in self._runtime["kitchen"] if s["index"] == index), None)
        if stove is None:
            raise RestaurantError("灶台尚未解锁")
        return stove

    def _dish(self, key):
        allowed = self._snapshot["state"].get("unlocked", {}).get("dishes", [])
        dish = next((d for d in self._snapshot["config"].get("dishes", []) if d["key"] == key), None)
        if dish is None or key not in allowed:
            raise RestaurantError("菜品不存在或尚未解锁")
        return dish

    def _usage(self):
        usage = {}
        for stove in self._runtime["kitchen"]:
            for key, amount in stove["ingredients"].items():
                usage[key] = usage.get(key, 0) + amount
        return usage

    def _prepare(self, stove):
        if stove["status"] != "prepping":
            raise RestaurantError("请先选择菜品")
        dish = self._dish(stove["dish_key"])
        inventory = self._snapshot["inventory"]
        if not inventory.get("tools", {}).get(dish.get("tool")):
            raise RestaurantError("所需工具尚未解锁")
        usage = self._usage()
        amounts = {r["key"]: int(r["quantity"]) for r in dish["ingredients"]}
        for key, quantity in amounts.items():
            available = int(inventory.get("ingredients", {}).get(key, 0)) - usage.get(key, 0)
            if quantity - stove["ingredients"].get(key, 0) > available:
                raise RestaurantError(f"食材 {key} 库存不足，请先购买")
        stove["ingredients"] = amounts
        stove["tool_key"] = dish["tool"]

    def _cook(self, stove):
        if stove["status"] != "prepping":
            raise RestaurantError("当前灶台不能开始烹饪")
        dish = self._dish(stove["dish_key"])
        if stove["tool_key"] != dish["tool"] or any(
                stove["ingredients"].get(i["key"], 0) < int(i["quantity"]) for i in dish["ingredients"]):
            raise RestaurantError("请先备齐食材和工具")
        if any(amount > int(self._snapshot["inventory"].get("ingredients", {}).get(key, 0))
               for key, amount in self._usage().items()):
            raise RestaurantError("站点库存已变化，请取消备菜并重新分配食材")
        duration = float(dish["cook_time"])
        if not math.isfinite(duration) or duration <= 0:
            raise RestaurantError("菜品烹饪时间异常")
        stove.update(status="cooking", ready_at=time.time() + duration)

    def _customer(self, customer_id):
        value = self._int(customer_id, "顾客编号", maximum=2**63-1)
        customer = next((c for c in self._snapshot["state"].get("customer_plan", [])
                         if str(c.get("id")) == str(value)), None)
        if not customer or customer.get("status") != "waiting" or not customer.get("seat"):
            raise RestaurantError("顾客已离席或尚未入座，请刷新")
        if self._runtime["cleaning"].get(str(customer["seat"]), 0) > time.time():
            raise RestaurantError("餐位正在清理，请等待 10 秒")
        return customer

    def _write(self, action, payload, stove=None, customer=None):
        self._runtime["pending"] = {"action": action, "time": time.time(),
                                    "stove": stove["index"] if stove else None,
                                    "payload": copy.deepcopy(payload),
                                    "context": self._runtime.get("context"), "day": self._runtime.get("day"),
                                    "local_day": datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Shanghai")).date().isoformat(),
                                    "before": copy.deepcopy({k: self._snapshot.get(k, {}) for k in
                                                             ("state", "inventory", "user", "visits")}),
                                    "seat": (customer or {}).get("seat"),
                                    "request_id": self._runtime.get("active_request_id")}
        self._save()  # 先记录请求意图；进程中断后也禁止盲目重放。
        try:
            response = self._request(action, payload)
        except RestaurantError as exc:
            self._event(action, str(exc), False)
            self._last_fetch = 0
            self._save()
            raise
        self._merge(response)
        if response["success"]:
            if stove:
                stove.update(self._empty(stove["index"]))
            seat = (response.get("customer") or customer or {}).get("seat")
            if seat and action in {"serve_customer", "customer_left"}:
                self._runtime["cleaning"][str(seat)] = time.time() + 10
            self._last_fetch = 0  # 下一次读取得到完整快照，当前请求绝不重发。
        self._runtime["pending"] = None
        message = str(response.get("message") or ("操作完成" if response["success"] else "站点拒绝操作"))
        self._event(action, message, response["success"])
        request_id = self._runtime.get("active_request_id")
        if request_id:
            self._runtime.setdefault("receipts", {})[request_id] = {
                "success": response["success"], "message": message}
        self._save()
        return self._result(response["success"], message,
                            requires_confirmation=bool(response.get("requires_confirmation")))

    def _reconcile_pending(self):
        """仅依据完整读回快照确认结果；没有证据时保留锁及预算，绝不重放写入。"""
        state = self._snapshot["state"]
        for slot in ("pending_purchase", "pending"):
            pending = self._runtime.get(slot)
            if not pending:
                continue
            before, payload = pending.get("before", {}), pending.get("payload", {})
            same_session = (bool(pending.get("context")) and pending["context"] == self._runtime.get("context")
                            and pending.get("day") == self._runtime.get("day"))
            action = pending["action"]
            confirmed = False
            if same_session:
                if action == "purchase_ingredient":
                    key, quantity = payload.get("ingredient_key"), payload.get("quantity")
                    old = before.get("inventory", {}).get("ingredients", {}).get(key)
                    new = self._snapshot["inventory"].get("ingredients", {}).get(key)
                    price = next((i.get("price") for i in self._snapshot["config"].get("ingredients", [])
                                  if i.get("key") == key), None)
                    old_magic, new_magic = before.get("user", {}).get("magic"), self._snapshot.get("user", {}).get("magic")
                    values = (old, new, quantity, price, old_magic, new_magic)
                    try:
                        if any(isinstance(n, bool) for n in values):
                            raise ValueError("invalid numeric value")
                        old, new, quantity, price, old_magic, new_magic = map(float, values)
                        valid = all(math.isfinite(n) for n in (old, new, quantity, price, old_magic, new_magic))
                    except (ValueError, TypeError):
                        valid = False
                    if valid:
                        confirmed = (quantity > 0 and new == old + quantity and
                                     math.isclose(new_magic, old_magic - quantity * price, abs_tol=0.001))
                elif action == "start_session":
                    confirmed = (before.get("state", {}).get("session_status") == "ready" and
                                 state.get("session_status") in {"open", "closed"})
                elif action in {"serve_customer", "customer_left"}:
                    customer = next((c for c in state.get("customer_plan", [])
                                     if str(c.get("id")) == str(payload.get("customer_id"))), {})
                    confirmed = customer.get("status") == ("served" if action == "serve_customer" else "left")
                elif action == "visit_restaurant":
                    target = str(payload.get("target_username") or "").casefold()
                    today = datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Shanghai")).date().isoformat()
                    confirmed = pending.get("local_day") == today and bool(target) and any(str(r.get("target_username") or "").casefold() == target
                                for r in self._snapshot.get("visits", {}).get("records", []))
                    if confirmed:
                        item = self._visit_account()["attempts"].get(target)
                        if item:
                            item.update(status="success", message="已从站点记录确认到访")
            if confirmed:
                self._runtime.setdefault("run", {})["failures"] = 0
                if pending.get("stove"):
                    stove = self._stove(pending["stove"])
                    stove.update(self._empty(stove["index"]))
                if pending.get("seat") and action in {"serve_customer", "customer_left"}:
                    # 从读回时再等 10 秒，不冒险提前复用餐位。
                    self._runtime["cleaning"][str(pending["seat"])] = time.time() + 10
                if pending.get("request_id"):
                    self._runtime.setdefault("receipts", {})[pending["request_id"]] = {
                        "success": True, "message": "已从站点状态确认成功；原请求未重发"}
                self._runtime[slot] = None
                self._runtime.pop("active_request_id", None)
                self._event("reconcile", f"{action} 已读回确认成功，恢复经营；原请求未重发", True)
            elif slot == "pending" and action == "purchase_ingredient":
                # 隔离未知采购，禁止再次补货；其他已备食材可继续正常烹饪和上菜。
                self._runtime["pending_purchase"] = pending
                self._runtime["pending"] = None
                self._event("reconcile", "采购仍待核对，已暂停补货；现有食材的订单继续服务", False)

    def _dispatch(self, action, args):
        if action in {"list_visitable_restaurants", "inspect_restaurant_target"}:
            payload = {"limit": 6} if action.startswith("list_") else {"target_username": self._username(args)}
            response = self._request(action, payload, read=True)
            return self._result(response["success"], str(response.get("message") or ""),
                                restaurants=response.get("restaurants") or [], candidate=response.get("candidate"))
        if self._runtime.get("pending"):
            raise RestaurantError("上次写入结果不明；请刷新、核对站点后解锁")
        if self._runtime.get("pending_purchase") and action not in {
                "assign_dish", "prepare", "cook", "cancel", "return_stove", "serve"}:
            raise RestaurantError("采购结果待核对，已停止补货和新营业；现有订单继续服务")
        if action in {"assign_dish", "prepare", "cook", "cancel", "return_stove", "serve", "discard"}:
            stove = self._stove(args.get("station_index"))
            if action == "assign_dish":
                if stove["status"] != "idle":
                    raise RestaurantError("请先清理该灶台")
                dish = self._dish(args.get("dish_key"))
                stove.update(dish_key=dish["key"], status="prepping")
            elif action == "prepare":
                self._prepare(stove)
            elif action == "cook":
                self._cook(stove)
            elif action == "cancel":
                if stove["status"] != "prepping":
                    raise RestaurantError("当前灶台状态不支持此操作")
                stove.update(self._empty(stove["index"]))
            else:
                if stove["status"] != "ready":
                    raise RestaurantError("菜品尚未烹饪完成")
                customer = None
                payload = {"dish_key": stove["dish_key"]}
                if action == "serve":
                    customer = self._customer(args.get("customer_id"))
                    if customer["dish_key"] != stove["dish_key"]:
                        raise RestaurantError("菜品与顾客点单不匹配")
                    if float(customer.get("deadline") or 0) <= time.time():
                        raise RestaurantError("顾客耐心已耗尽，请等待离席处理")
                    payload["customer_id"] = customer["id"]
                return self._write("serve_customer" if action == "serve" else "discard_dish", payload, stove, customer)
            self._save()
            return self._result(message="厨房状态已更新")
        if action == "start_session":
            state = self._snapshot["state"]
            if state.get("session_status") != "ready" or not state.get("customers_total"):
                raise RestaurantError("今天无法再次开业")
            return self._write(action, {})
        if action == "purchase_ingredient":
            key = args.get("ingredient_key")
            if key not in {i["key"] for i in self._snapshot["config"].get("ingredients", [])}:
                raise RestaurantError("食材不存在")
            quantity = self._int(args.get("quantity"), "购买数量")
            item = next(i for i in self._snapshot["config"]["ingredients"] if i["key"] == key)
            self._budget(args, float(item["price"]) * quantity)
            return self._write(action, {"ingredient_key": key, "quantity": quantity})
        if action in {"hire_staff", "update_staff_assignment"}:
            role = args.get("role")
            if role not in {"chef", "server"}:
                raise RestaurantError("员工类型无效")
            if action == "hire_staff":
                quantity = self._int(args.get("quantity"), "雇佣人数", maximum=1)
                price = self._snapshot.get("staff", {}).get("next_prices", {}).get(role)
                if not price:
                    raise RestaurantError("当前没有可雇佣名额")
                self._budget(args, float(price))
                return self._write(action, {"role": role, "quantity": quantity})
            station = self._stove(args.get("station_index"))["index"]
            assigned = self._int(args.get("assigned"), "分配状态", minimum=0, maximum=1)
            return self._write(action, {"role": role, "station_index": station, "assigned": assigned})
        if action == "visit_restaurant":
            payload = {"target_username": self._username(args)}
            if args.get("confirm") == "yes":
                payload["confirm"] = "yes"
            return self._write(action, payload)
        raise RestaurantError("不支持的餐厅操作")

    @staticmethod
    def _budget(args, cost):
        try:
            budget = float(args.get("max_cost", -1))
        except (TypeError, ValueError):
            raise RestaurantError("缺少本次确认的魔力预算")
        if not math.isfinite(budget) or budget < cost or cost < 0:
            raise RestaurantError("站点报价超出本次确认预算，请刷新后重新确认")

    @staticmethod
    def _username(args):
        name = str(args.get("target_username") or "").strip()
        if not name or len(name) > 64 or any(ord(c) < 32 for c in name):
            raise RestaurantError("请输入 1–64 字符的用户名")
        return name

    @serialized
    def api_action(self, payload: dict = None) -> dict:
        payload = payload or {}
        self._ensure_fresh(force=True)
        action = str(payload.get("action") or "")
        if (self._automatic_enabled() or self._runtime.get("run", {}).get("active")) and action not in {"list_visitable_restaurants", "inspect_restaurant_target"}:
            raise RestaurantError("后台任务已开启，请先在配置中暂停自动经营和自动下馆子，再执行手动操作")
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            raise RestaurantError("操作参数必须为对象")
        request_id = str(payload.get("request_id") or "")
        if not 8 <= len(request_id) <= 80:
            raise RestaurantError("缺少有效请求编号，请刷新插件页面")
        receipts = self._runtime.setdefault("receipts", {})
        if request_id in receipts:
            old = receipts[request_id]
            return self._result(old["success"], "重复请求未再次执行：" + old["message"])
        self._runtime["active_request_id"] = request_id
        try:
            result = self._dispatch(action, args)
        finally:
            self._runtime.pop("active_request_id", None)
        receipts[request_id] = {"success": result["success"], "message": result["message"]}
        while len(receipts) > 128:
            del receipts[next(iter(receipts))]
        self._save()
        return result

    @serialized
    def api_tick(self, payload: dict = None) -> dict:
        self._ensure_fresh()
        if self._automatic_enabled() or self._runtime.get("run", {}).get("active"):
            return self._result()  # 页面仅观察，后台是唯一自动执行者。
        if self._runtime.get("pending"):
            return self._result(False, "存在结果不明的写入，员工服务已暂停")
        state = self._snapshot["state"]
        if state.get("session_status") != "open":
            return self._result()
        # 与网页一致：到时离席，不提前通知；每个页面 tick 串行处理。
        for customer in state.get("customer_plan", []):
            if (customer.get("status") == "waiting" and customer.get("seat")
                    and customer.get("deadline") and float(customer["deadline"]) <= time.time()
                    and self._runtime["cleaning"].get(str(customer["seat"]), 0) <= time.time()):
                return self._write("customer_left", {"customer_id": customer["id"]}, customer=customer)
        if not (payload or {}).get("run_staff") is True:
            return self._result()
        staff = self._snapshot.get("staff") or {}
        if not staff.get("unlocked"):
            return self._result()
        assignments = staff.get("assignments_map") or staff.get("assignments") or {}
        if isinstance(assignments, list):
            assignments = {str(a["station_index"]): a for a in assignments if a.get("station_index")}
        mode = self._snapshot["config"].get("settings", {}).get("automation_mode", "seat-bound")
        if mode != "seat-bound":
            return self._result(False, "站点员工模式已变化，请手动操作并更新插件")
        for stove in self._runtime["kitchen"]:
            assignment = assignments.get(str(stove["index"]), assignments.get(stove["index"], {}))
            customer = next((c for c in state.get("customer_plan", []) if c.get("status") == "waiting"
                             and str(c.get("seat")) == str(stove["index"])), None)
            if not customer or self._runtime["cleaning"].get(str(stove["index"]), 0) > time.time():
                continue
            if self._bool(assignment.get("chef")) and stove["status"] in {"idle", "prepping"}:
                if stove["status"] == "idle":
                    self._dish(customer["dish_key"])
                    stove.update(dish_key=customer["dish_key"], status="prepping")
                try:
                    self._prepare(stove)
                    self._cook(stove)
                except RestaurantError as exc:
                    self._save()
                    return self._result(False, str(exc))
            if (self._bool(assignment.get("server")) and stove["status"] == "ready"
                    and stove["dish_key"] == customer["dish_key"]):
                return self._dispatch("serve", {"station_index": stove["index"], "customer_id": customer["id"]})
        self._save()
        return self._result()

    def _auto_status(self, phase, message):
        auto = self._runtime.setdefault("automation", {})
        changed = auto.get("phase") != phase or auto.get("message") != message
        auto.update(phase=phase, message=message, last_check=time.time())
        if changed:
            self._event("automation", message, phase not in {"blocked", "error", "uncertain", "retrying"})
        self._save()
        if phase in {"blocked", "error", "uncertain"}:
            self._notify_once(f"alert:{phase}", "需要处理", message)

    def _notify_once(self, key, title, text):
        if not self._config.get("notify"):
            return
        day = datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Shanghai")).date().isoformat()
        notices = self._runtime.setdefault("notifications", {})
        if notices.get("day") != day:
            notices.clear()
            notices.update(day=day, sent=[])
        if key in notices["sent"]:
            return
        # 先落盘，防止通知渠道超时或进程重启后刷屏；失败不阻断经营。
        notices["sent"].append(key)
        self._save()
        try:
            self.post_message(mtype=NotificationType.Plugin, title=f"【思齐餐厅】{title}", text=text)
        except Exception:
            self._event("notification", "通知发送失败，请检查 MP 通知渠道；当天不重复发送", False)
            self._save()

    def _notify_closed(self):
        state = self._snapshot["state"]
        if state.get("session_status") != "closed":
            return
        left = sum(c.get("status") == "left" for c in state.get("customer_plan", []))
        text = f"顾客 {state.get('customers_served', 0)}/{state.get('customers_total', 0)}"
        if left:
            text += f" · 流失 {left}"
        text += (f"\n净收益 {state.get('net_earnings_today', 0)} 魔力"
                 f" · 补货 {self._auto_account().get('spent', 0):g} 魔力")
        self._notify_once("closed", "今日经营完成", text)

    def _notify_visits(self, visits):
        info = self._snapshot.get("visits") or {}
        # Count confirmed visits only; count_floor may include an uncertain write.
        names = {}
        for record in info.get("records") or []:
            name = str(record.get("target_username") or "").strip() if isinstance(record, dict) else ""
            if name:
                names.setdefault(name.casefold(), name)
        problems = []
        for item in visits["attempts"].values():
            name = item["username"]
            if item.get("status") == "success":
                names.setdefault(name.casefold(), name)
            elif item.get("status") == "sending":
                problems.append(f"待核对：{name}")
            else:
                reason = " ".join(str(item.get("message") or "请查看插件记录").split())
                if len(reason) > 40:
                    reason = reason[:39] + "…"
                label = "跳过" if item.get("status") == "skipped" else "失败"
                problems.append(f"{label}：{name}（{reason}）")
        count = max(int(info.get("count") or 0), len(names))
        limit = min(3, int(info.get("limit", 3)))
        lines = [f"已到访 {count}/{limit} 家"]
        if names:
            lines.append("、".join(names.values()))
        lines.extend(problems[:3])
        if len(problems) > 3:
            lines.append(f"另有 {len(problems)-3} 项，详情见插件")
        self._notify_once("visits", "今日下馆子", "\n".join(lines))

    def _visit_account(self):
        day = datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Shanghai")).date().isoformat()
        visits = self._runtime.setdefault("auto_visits", {})
        if visits.get("day") != day:
            visits.clear()
            visits.update(day=day, attempts={}, count_floor=0, message="等待下馆子", retry_at=0)
            self._save()
        return visits

    def _visit_status(self, message, done=False):
        visits = self._visit_account()
        if visits.get("message") != message:
            self._event("auto_visit", message, True)
        visits["message"] = message
        visits["last_check"] = time.time()
        visits["done"] = done
        self._save()
        if done:
            self._notify_visits(visits)

    def _auto_visit_step(self):
        if not self._config.get("auto_visit") or self._stopped or self._stop_auto.is_set():
            return
        visits = self._visit_account()
        if visits.get("retry_at", 0) > time.time():
            return
        info = self._snapshot.get("visits") or {}
        # 配额必须来自站点，不在缺字段时假定仍有 3 次机会。
        count = self._int(info.get("count"), "站点下馆子次数", 0, 10000)
        limit = min(3, self._int(info.get("limit"), "站点下馆子上限", 0, 10000))
        used = max(count, visits["count_floor"])
        if info.get("reached_limit") or used >= limit:
            uncertain = any(a.get("status") == "sending" for a in visits["attempts"].values())
            suffix = "（含结果待核对的预留次数）" if uncertain else ""
            self._visit_status(f"今日下馆子次数已满：{used} / {limit} 次{suffix}", done=True)
            return
        records = info.get("records") or []
        excluded = {str(r.get("target_username") or "").casefold() for r in records if isinstance(r, dict)}
        excluded.add(str(self._snapshot.get("user", {}).get("username") or "").casefold())
        excluded.update(visits["attempts"])
        configured = self._config["visit_targets"]
        if configured:
            targets = [n for n in configured if n.casefold() not in excluded]
            if not targets:
                self._visit_status("今日指定名单已处理；未配置的位置不随机补人", done=True)
                return
            target = targets[0]
            response = self._request("inspect_restaurant_target", {"target_username": target}, read=True)
            candidate = response.get("candidate")
            if not response["success"] or not candidate or not candidate.get("can_visit"):
                message = str((candidate or {}).get("message") or response.get("message") or "餐馆不可到访")
                visits["attempts"][target.casefold()] = {"username": target, "status": "skipped", "message": message}
                self._visit_status(f"跳过 {target}：{message}")
                self._next_auto = time.time() + 1
                return
            # 使用站点返回的规范用户名，防止大小写别名造成重复。
            target = self._username({"target_username": candidate.get("username") or target})
            if target.casefold() in excluded:
                visits["attempts"][targets[0].casefold()] = {"username": target, "status": "skipped", "message": "本人或今日已到访"}
                self._save()
                return
        else:
            if len(visits["attempts"]) >= 12:
                self._visit_status("今日随机候选已尝试 12 人，停止继续尝试，请查看到访记录", done=True)
                return
            response = self._request("list_visitable_restaurants", {"limit": 6}, read=True)
            if not response["success"]:
                raise RestaurantError(str(response.get("message") or "获取随机餐馆失败"))
            choices = []
            for item in response.get("restaurants") or []:
                if not isinstance(item, dict) or item.get("can_visit") is False or not item.get("username"):
                    continue
                name = self._username({"target_username": item["username"]})
                if name.casefold() not in excluded:
                    choices.append(name)
                    excluded.add(name.casefold())
            if not choices:
                visits["retry_at"] = time.time() + 1800
                self._visit_status("暂无可用随机餐馆，本次结束；下次 Cron 且至少 30 分钟后重查")
                return
            target = random.choice(choices)
        if self._stopped or self._stop_auto.is_set():
            return
        # 请求前记录目标并预占一次；未知结果及重启均不得换人突破三次上限。
        item = {"username": target, "status": "sending", "message": "请求已记录，结果待核对"}
        visits["attempts"][target.casefold()] = item
        visits["count_floor"] = used + 1
        self._save()
        result = self._dispatch("visit_restaurant", {"target_username": target, "confirm": "yes"})
        item.update(status="success" if result["success"] else "failed", message=result["message"])
        if not result["success"]:
            visits["count_floor"] = used
        self._visit_status(f"{target}：{result['message']}")
        self._next_auto = time.time() + 1

    def _auto_account(self):
        # 预算按北京时间自然日计算，不能由保存配置或重新启用重置。
        day = datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Shanghai")).date().isoformat()
        auto = self._runtime.setdefault("automation", {})
        if auto.get("budget_day") != day:
            auto.update(budget_day=day, spent=0)
            self._save()
        return auto

    def _purchase_cost(self, shortages):
        if shortages and self._runtime.get("pending_purchase"):
            raise RestaurantError("采购结果待核对，已暂停补货")
        prices = {i["key"]: float(i["price"]) for i in self._snapshot["config"].get("ingredients", [])}
        total = 0
        for key, quantity in shortages.items():
            price = prices.get(key, -1)
            if not math.isfinite(price) or price <= 0:
                raise RestaurantError("食材价格异常，暂停自动补货")
            total += price * quantity
        auto = self._auto_account()
        if total > 0:
            if not self._config["auto_purchase"]:
                raise RestaurantError("食材不足，自动补货未开启")
            if auto.get("spent", 0) + total > self._config["daily_budget"]:
                raise RestaurantError("食材缺口超出今日剩余采购预算，请补货或调整预算")
            if float(self._snapshot.get("user", {}).get("magic", 0)) - total < self._config["magic_reserve"]:
                raise RestaurantError("补货后余额将低于保留魔力，请补货或调整保留值")
        return total

    def _preflight(self):
        """开业前检查所有可能菜单的保守库存上界，不提前扣费或假定未来订单。"""
        state = self._snapshot["state"]
        inventory = self._snapshot["inventory"]
        customers = int(state.get("customers_total") or 0)
        needs = {}
        for key in state.get("unlocked", {}).get("dishes", []):
            dish = self._dish(key)
            if not inventory.get("tools", {}).get(dish["tool"]):
                raise RestaurantError("菜单所需工具未解锁，暂不开业")
            for item in dish["ingredients"]:
                needs[item["key"]] = max(needs.get(item["key"], 0), int(item["quantity"]) * customers)
        if not needs:
            raise RestaurantError("未读取到可用菜单，暂不开业")
        shortages = {k: n - int(inventory.get("ingredients", {}).get(k, 0))
                     for k, n in needs.items() if n > int(inventory.get("ingredients", {}).get(k, 0))}
        self._purchase_cost(shortages)

    def run_automation(self):
        """Cron / 一次运行唤醒后才访问站点，闭店结束；营业期每轮至多一次写入。"""
        if (self._stopped or self._stop_auto.is_set() or not self.get_state()
                or not self._runtime.get("run", {}).get("active") or time.time() < self._next_auto):
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._stopped or self._stop_auto.is_set():
                return
            self._ensure_fresh()
            self._auto_account()
            run = self._runtime["run"]
            if self._runtime.get("pending"):
                self._auto_status("uncertain", "写入结果待核对，后台继续读回确认；原请求不会重发")
                self._next_auto = time.time() + (2 if self._snapshot["state"].get("session_status") == "open" else 60)
                if self._snapshot["state"].get("session_status") == "closed":
                    run["active"] = False
                    self._save()
                return
            wrote = self._auto_step() if run.get("operate") else False
            run["live"] = self._snapshot["state"].get("session_status") == "open"
            self._save()
            # 有顾客或厨房工作时优先经营，不让外出查询占用顾客耐心。
            status = self._snapshot["state"].get("session_status")
            if status == "open" and not run.get("operate"):
                run["active"] = False
                self._auto_status("waiting", "餐厅仍在营业，下馆子等待下次 Cron 检查")
                return
            if not wrote and status != "open":
                if run.get("visits") and not self._runtime.get("pending_purchase"):
                    self._next_auto = time.time() + 1
                    self._auto_visit_step()
                    run["failures"] = 0
                    visits = self._visit_account()
                    if not visits.get("done") and visits.get("retry_at", 0) <= time.time():
                        return
                run["active"] = False
                self._auto_status("closed" if status == "closed" else "waiting",
                                  "今日已闭店，本次任务结束；等待下次 Cron 检查" if status == "closed" else
                                  "本次检查完成；等待下次 Cron 检查")
                self._save()
            run["failures"] = 0
        except RestaurantError as exc:
            run = self._runtime.get("run", {})
            run["failures"] = run.get("failures", 0) + 1
            live = (run.get("live") or self._snapshot.get("state", {}).get("session_status") == "open" or
                    (self._runtime.get("pending") or {}).get("action") == "start_session")
            pending = bool(self._runtime.get("pending"))
            transient = isinstance(exc, RestaurantReadError) and exc.retryable and not pending
            delay = min(5, run["failures"] * 2) if live else 60
            # 被限流时同样退避，不能在营业中每 2 秒继续触发 429。
            if isinstance(exc, RestaurantReadError) and "HTTP 429" in str(exc):
                delay = 60
            stopped = not live and run["failures"] >= 3
            self._next_auto = time.time() + delay
            if transient:
                suffix = ("本次已停止，等待下次 Cron 或保存后运行一次" if stopped
                          else f"{delay} 秒后自动重查")
                message = f"{exc}；连续失败 {run['failures']} 次，{suffix}"
            else:
                message = str(exc)
            phase = ("uncertain" if pending else
                     "retrying" if transient and run["failures"] < 3 else "blocked")
            self._auto_status(phase, message)
            if stopped:
                run["active"] = False
                self._save()
        except Exception:
            # 不将响应、Cookie 或请求对象写入日志。
            self._auto_status("error", "自动经营遇到异常，稍后读回检查；不重试结果不明的写入")
            self._next_auto = time.time() + (5 if self._snapshot.get("state", {}).get("session_status") == "open" else 60)
        finally:
            self._lock.release()

    def _auto_write_result(self, result, description):
        if not result["success"]:
            raise RestaurantError(result["message"] or "站点拒绝操作")
        self._auto_status("running", description)

    def _auto_step(self):
        if self._stopped or self._stop_auto.is_set():
            return
        state = self._snapshot["state"]
        status = state.get("session_status")
        if status == "ready":
            if not state.get("customers_total"):
                self._auto_status("waiting", "今日暂无顾客，等待下次 Cron 检查")
                return
            self._preflight()
            self._auto_write_result(self._dispatch("start_session", {}), "今日已自动开业")
            return True
        if status != "open":
            self._auto_status("closed", "今日已闭店，本次任务结束；等待下次 Cron 检查")
            self._notify_closed()
            if status == "closed":
                for stove in self._runtime.get("kitchen", []):
                    stove.update(self._empty(stove["index"]))
                self._runtime["cleaning"] = {}
                self._save()
            return
        now = time.time()
        customers = sorted((c for c in state.get("customer_plan", [])
                            if c.get("status") == "waiting" and c.get("seat")),
                           key=lambda c: float(c.get("deadline") or 0))
        cleaning = self._runtime["cleaning"]
        # 到期离席也必须通知站点；不提前离席、不伪造服务。
        for customer in customers:
            if (float(customer.get("deadline") or 0) <= now
                    and cleaning.get(str(customer["seat"]), 0) <= now):
                self._auto_write_result(self._write("customer_left", {"customer_id": customer["id"]},
                                                    customer=customer), "已处理到期离席顾客")
                return True
        waiting = [c for c in customers if float(c.get("deadline") or 0) > now]
        stoves = self._runtime["kitchen"]
        # 按手动规则跨灶台上菜，最急订单优先；每份真实烹饪成品只提交一次。
        for customer in waiting:
            if cleaning.get(str(customer["seat"]), 0) > now:
                continue
            stove = next((s for s in stoves if s["status"] == "ready" and s["dish_key"] == customer["dish_key"]), None)
            if stove:
                self._auto_write_result(self._dispatch("serve", {"station_index": stove["index"],
                                                               "customer_id": customer["id"]}),
                                        f"灶台 {stove['index']} 已完成上菜")
                return True
        # 已备菜/烹饪/成品都占用一份需求，避免多个灶台重复做同一份订单。
        covered = {}
        for stove in stoves:
            if stove["status"] != "idle":
                covered[stove["dish_key"]] = covered.get(stove["dish_key"], 0) + 1
        for customer in waiting:
            key = customer["dish_key"]
            if covered.get(key, 0):
                covered[key] -= 1
                continue
            stove = next((s for s in stoves if s["status"] == "idle"), None)
            if not stove:
                break
            self._dish(key)
            stove.update(dish_key=key, status="prepping")
        # 无须等待清理结束才能备菜，但上菜严格受 10 秒清理限制。
        shortages = {}
        errors = []
        for stove in stoves:
            if stove["status"] != "prepping":
                continue
            dish = self._dish(stove["dish_key"])
            usage = self._usage()
            missing = {i["key"]: int(i["quantity"]) - stove["ingredients"].get(i["key"], 0)
                       - (int(self._snapshot["inventory"].get("ingredients", {}).get(i["key"], 0)) - usage.get(i["key"], 0))
                       for i in dish["ingredients"]}
            missing = {k: n for k, n in missing.items() if n > 0}
            if missing:
                # 只补当前实际订单；库存预留由 _prepare 原子更新。
                for key, n in missing.items():
                    shortages[key] = max(shortages.get(key, 0), n)
                continue
            try:
                self._prepare(stove)
                self._cook(stove)
            except RestaurantError as exc:
                errors.append(str(exc))
        self._save()  # 任何后续采购前，先持久化已经启动的烹饪。
        if shortages:
            try:
                self._purchase_cost(shortages)
                if self._auto_account().get("purchase_retry_at", 0) > time.time():
                    raise RestaurantError("补货被拒绝，等待 60 秒后重查")
                key, quantity = next(iter(shortages.items()))
                quantity = min(quantity, 10000)
                cost = self._purchase_cost({key: quantity})
                auto = self._auto_account()
                # 先占预算再写；崩溃/未知结果保持占用，绝不靠重启突破每日限额。
                auto["spent"] = auto.get("spent", 0) + cost
                self._save()
                if self._stopped or self._stop_auto.is_set():
                    auto["spent"] -= cost
                    self._save()
                    return
                result = self._dispatch("purchase_ingredient", {"ingredient_key": key, "quantity": quantity, "max_cost": cost})
                if not result["success"]:
                    auto["spent"] -= cost
                    auto["purchase_retry_at"] = time.time() + 60
                    self._save()
                self._auto_write_result(result, f"按实际订单补货，今日采购已占用 {auto['spent']:g} 魔力")
                return True
            except RestaurantError as exc:
                if self._runtime.get("pending"):
                    raise
                errors.append(str(exc))
        if errors:
            self._auto_status("blocked", errors[0] + "；已在烹饪的订单继续处理")
        elif any(s["status"] == "cooking" for s in stoves):
            self._auto_status("running", "按订单并行烹饪，完成后自动上菜")
        elif waiting and all(s["status"] == "ready" for s in stoves):
            self._auto_status("blocked", "成品暂不匹配当前订单，等待匹配顾客；可暂停托管后手动清理")
        else:
            self._auto_status("running", "等待烹饪、餐位清理或顾客入座")

    @serialized
    def api_resolve(self, payload: dict = None) -> dict:
        if (payload or {}).get("acknowledged") is not True:
            raise RestaurantError("请先核对站点状态并确认解除锁定")
        self._ensure_fresh(force=True)
        for slot in ("pending", "pending_purchase"):
            pending = self._runtime.get(slot)
            if not pending:
                continue
            # 不确定的成品不再二次提交；只释放该灶台的本地预留。
            if pending.get("stove"):
                stove = self._stove(pending["stove"])
                stove.update(self._empty(stove["index"]))
            self._runtime[slot] = None
            self._runtime.pop("active_request_id", None)
            if pending.get("request_id"):
                self._runtime.setdefault("receipts", {})[pending["request_id"]] = {
                    "success": False, "message": "不确定请求已核对，不得重放"}
            self._event("resolve", "用户核对后解除锁定；原请求未重发", True)
            self._next_auto = 0
            self._save()
        return self._result(message="已解除锁定；原请求未重发")

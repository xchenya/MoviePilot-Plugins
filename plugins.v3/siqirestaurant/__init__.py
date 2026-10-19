# SPDX-License-Identifier: GPL-3.0-only
"""思齐餐厅：V3 原生面板、服务器端厨房状态和受限的站点操作。"""
import copy
import hashlib
import math
import threading
import time
from datetime import datetime
from functools import wraps
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.sdk.plugin import _PluginBase
from app.sdk.config import settings
from app.db.oper.site import SiteOper


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


class PublicConfig(BaseModel):
    enabled: bool = False
    use_proxy: bool = False
    cookie_configured: bool = False
    site_configured: bool = False


class ConfigResult(BaseModel):
    success: bool
    message: str = ""
    config: PublicConfig


class RestaurantError(Exception):
    pass


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
    plugin_desc = "在 MoviePilot 内经营思齐餐厅，管理厨房、员工、食材、下馆子及经营日志。"
    plugin_icon = "https://si-qi.xyz/favicon.ico"
    plugin_version = "1.0.0"
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

    def init_plugin(self, config: dict = None):
        with self._lock:
            values = config or {}
            self._config = {"enabled": self._bool(values.get("enabled", False)),
                            "use_proxy": self._bool(values.get("use_proxy", False)),
                            "cookie": str(values.get("cookie") or "").strip()}
            self._runtime = self.get_data("runtime") or {}
            self._snapshot = {}
            self._last_fetch = 0
            self._stopped = False

    @staticmethod
    def _bool(value):
        return value is True or value == 1 or str(value).lower() in {"true", "yes", "on"}

    def get_state(self):
        return self._config.get("enabled", False)

    def get_command(self):
        return []

    def get_service(self):
        # 第一阶段不注册无人值守任务；页面关闭后不发起站点操作。
        return []

    def get_form(self):
        return None, self.api_config()

    def get_page(self):
        return []

    def get_render_mode(self):
        return "vue", f"dist/assets-v{self.plugin_version}"

    def stop_service(self):
        self._stopped = True

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
                "site_configured": bool(site)}

    def api_save_config(self, payload: dict = None) -> dict:
        with self._lock:
            payload = payload or {}
            config = dict(self._config)
            for key in ("enabled", "use_proxy"):
                if key in payload:
                    config[key] = self._bool(payload[key])
            if payload.get("clear_cookie") is True:
                config["cookie"] = ""
            elif str(payload.get("cookie") or "").strip():
                config["cookie"] = str(payload["cookie"]).strip()
            self.update_config(config)
            self._config = config
            self._snapshot = {}
            self._last_fetch = 0
            return {"success": True, "message": "配置已保存", "config": self.api_config()}

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
            self._runtime = {"context": context, "day": "", "kitchen": [], "cleaning": {},
                             "pending": None, "receipts": {}, "events": []}
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
        headers = {"Cookie": cookie, "User-Agent": ua, "Referer": "https://si-qi.xyz/siqi_restaurant.php",
                   "Accept": "application/json", "Origin": "https://si-qi.xyz"}
        options = dict(headers=headers, timeout=(10, 25), allow_redirects=False,
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
            if response.status_code != 200:
                raise RestaurantError(f"站点 HTTP {response.status_code}，请检查登录状态或代理")
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
                raise RestaurantError("站点返回格式异常，请检查 Cookie 或站点验证页面")
            return result
        except (requests.RequestException, ValueError, RestaurantError) as exc:
            if not read:
                # 不抄录响应内容、请求头或异常 URL，避免泄漏 Cookie。
                raise RestaurantError("站点写入结果不明，已暂停操作；请刷新并核对后解锁，勿重复提交") from exc
            if isinstance(exc, RestaurantError):
                raise
            raise RestaurantError("读取站点失败，请检查网络、Cookie 和代理") from exc

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
                "uncertain": bool(self._runtime.get("pending")),
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
                                    "request_id": self._runtime.get("active_request_id")}
        self._save()  # 先记录请求意图；进程中断后也禁止盲目重放。
        try:
            response = self._request(action, payload)
        except RestaurantError:
            self._event(action, "结果不明；未重试，等待核对", False)
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

    def _dispatch(self, action, args):
        if action in {"list_visitable_restaurants", "inspect_restaurant_target"}:
            payload = {"limit": 6} if action.startswith("list_") else {"target_username": self._username(args)}
            response = self._request(action, payload, read=True)
            return self._result(response["success"], str(response.get("message") or ""),
                                restaurants=response.get("restaurants") or [], candidate=response.get("candidate"))
        if self._runtime.get("pending"):
            raise RestaurantError("上次写入结果不明；请刷新、核对站点后解锁")
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

    @serialized
    def api_resolve(self, payload: dict = None) -> dict:
        if (payload or {}).get("acknowledged") is not True:
            raise RestaurantError("请先核对站点状态并确认解除锁定")
        self._ensure_fresh(force=True)
        pending = self._runtime.get("pending")
        if pending:
            # 不确定的成品不再二次提交；只释放该灶台的本地预留。
            if pending.get("stove"):
                stove = self._stove(pending["stove"])
                stove.update(self._empty(stove["index"]))
            self._runtime["pending"] = None
            self._runtime.pop("active_request_id", None)
            if pending.get("request_id"):
                self._runtime.setdefault("receipts", {})[pending["request_id"]] = {
                    "success": False, "message": "不确定请求已核对，不得重放"}
            self._event("resolve", "用户核对后解除锁定；原请求未重发", True)
            self._save()
        return self._result(message="已解除锁定；原请求未重发")

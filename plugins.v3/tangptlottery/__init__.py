"""TangPT daily lottery with native MoviePilot V3 scheduling and notifications."""
from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.db.oper.site import SiteOper
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase
try:
    from app.schemas.types import MessageType
except ImportError:  # Earlier V3 hosts used the old public enum name.
    from app.schemas.types import NotificationType as MessageType

from . import storage
from .protocol import DRAW_URL, ORIGIN, PAGE_URL, LotteryError, integer, number, parse_page, receipt

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class TangptLottery(_PluginBase):
    """Serialize draws and persist intent before every non-idempotent POST."""

    plugin_name = "不可躺自动抽奖"
    plugin_desc = "唐门每日定时抽奖、魔力保留、每日奖品统计与汇总通知。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya"
    plugin_config_prefix = "tangptlottery_"
    plugin_order = 32
    auth_level = 2

    def __init__(self):
        super().__init__()
        self._lifecycle = threading.RLock()
        self._run_lock = threading.Lock()
        self._cancel = threading.Event()
        self._generation = 0
        self._config = self.defaults()
        self._error = ""
        self._once = False
        self._diagnose_once = False
        self._acknowledge = False
        self._trigger = None

    @staticmethod
    def defaults():
        """Require opt-in; use a small daily target and conservative request pacing."""
        return {"enabled": False, "notify": True, "run_once": False, "diagnose_only": False,
                "cron": "0 8 * * *", "daily_target": 10, "batch": 10, "reserve": 100000,
                "max_cost": 20000, "interval": 30, "use_proxy": False, "acknowledge_pending": False}

    @staticmethod
    def _bool(value):
        """Handle serialized false values without Python truthiness surprises."""
        return value is True or value == 1 or str(value).lower() in {"true", "yes", "on"}

    def init_plugin(self, config=None):
        """Cancel the previous generation and reset one-shot switches before use."""
        with self._lifecycle:
            self._cancel.set()
            self._generation += 1
            self._cancel = threading.Event()
            self._once = self._diagnose_once = self._acknowledge = False
            self._trigger, self._error = None, ""
            values = {**self.defaults(), **(config or {})}
            try:
                for key in ("enabled", "notify", "run_once", "diagnose_only", "use_proxy", "acknowledge_pending"):
                    values[key] = self._bool(values[key])
                for key, lo, hi in (("daily_target", 1, 1000), ("batch", 1, 100), ("interval", 5, 900)):
                    values[key] = integer(values[key])
                    if not lo <= values[key] <= hi:
                        raise LotteryError(f"{key} 须在 {lo}–{hi} 之间")
                if values["batch"] not in (1, 10, 20, 50, 100):
                    raise LotteryError("连抽数量仅支持 1、10、20、50、100")
                values["reserve"], values["max_cost"] = number(values["reserve"]), number(values["max_cost"])
                if values["max_cost"] <= 0:
                    raise LotteryError("单抽费用上限必须大于零")
                values["cron"] = str(values["cron"]).strip()
                self._trigger = CronTrigger.from_crontab(values["cron"], timezone=LOCAL_TZ)
                self._once = values["run_once"] or values["diagnose_only"] or values["acknowledge_pending"]
            except Exception as exc:
                self._error = str(exc) if isinstance(exc, LotteryError) else "配置无效，请检查五段 Cron 表达式"
            self._config = values
            self._diagnose_once, self._acknowledge = values["diagnose_only"], values["acknowledge_pending"]
            changed = values["run_once"] or self._diagnose_once or self._acknowledge
            values["run_once"] = values["diagnose_only"] = values["acknowledge_pending"] = False
            if changed:
                try:
                    if self.update_config(copy.deepcopy(values)) is False:
                        raise LotteryError("一次性开关复位失败")
                except Exception:
                    self._error = "一次性开关复位失败，已取消执行"
            if self._error:
                self._once = False
                logger.error(f"不可躺抽奖：{self._error}")

    def get_state(self):
        """A one-shot check may run while daily scheduling is disabled."""
        return not self._error and (self._config["enabled"] or self._once)

    def get_service(self):
        """Let MP own cron/date jobs, with stable per-instance identifiers."""
        with self._lifecycle:
            if self._error or self._cancel.is_set():
                return []
            jobs, prefix = [], self.__class__.__name__
            options = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 120}
            if self._config["enabled"]:
                jobs.append({"id": prefix + ".Daily", "name": "不可躺每日抽奖", "trigger": self._trigger,
                             "func": partial(self.run, generation=self._generation), "kwargs": dict(options)})
            if self._once:
                jobs.append({"id": prefix + ".Once", "name": "不可躺执行一次",
                             "trigger": DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=3)),
                             "func": partial(self.run, generation=self._generation, once=True), "kwargs": dict(options)})
            return jobs

    def stop_service(self):
        """Interrupt waits; an in-flight receipt must still be committed."""
        with self._lifecycle:
            self._cancel.set()
            self._once = self._diagnose_once = self._acknowledge = False

    @staticmethod
    def get_command():
        """No remote chat commands."""
        return []

    def get_api(self):
        """Native configuration and pages need no custom HTTP endpoints."""
        return []

    def get_form(self):
        """Use native MP fields and its single save button."""
        from .ui import form
        return form(), self.defaults()

    def get_page(self):
        """Opening the detail page reads only local records, never the PT site."""
        from .ui import page
        try:
            return page(storage.load(self._path()), self._day(), self._error)
        except LotteryError as exc:
            return page({}, self._day(), str(exc))

    def _path(self):
        """Keep durable state in the MP instance data directory."""
        return self.get_data_path() / "lottery-state.json"

    @staticmethod
    def _day():
        """Local target day, not a claim about the site's undocumented reset time."""
        return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    def _session(self, config):
        """Take credentials from the matching MP site, bound to a fixed HTTPS host."""
        oper = SiteOper()
        site = oper.get_by_domain("tangpt.top") or oper.get_by_domain("www.tangpt.top")
        cookie = str(getattr(site, "cookie", "") or "").strip()
        if not site or not cookie or cookie.lower() == "cookie":
            raise LotteryError("请在 MP 站点管理添加不可躺（tangpt.top）并更新 Cookie")
        try:
            source = urlsplit(str(getattr(site, "url", "") or ""))
            valid = (source.scheme == "https" and source.hostname in ("www.tangpt.top", "tangpt.top")
                     and source.port in (None, 443) and not source.username and not source.password)
        except ValueError:
            valid = False
        if not valid:
            raise LotteryError("站点地址必须使用 https://www.tangpt.top 或 https://tangpt.top")
        session = requests.Session()
        session.trust_env = False
        for pair in cookie.split(";"):
            name, sep, value = pair.strip().partition("=")
            if sep and name:
                session.cookies.set(name, value, domain="www.tangpt.top", path="/")
        session.headers.update({"User-Agent": getattr(site, "ua", None) or "Mozilla/5.0",
                                "Referer": PAGE_URL, "Origin": ORIGIN, "X-Requested-With": "XMLHttpRequest"})
        if config["use_proxy"]:
            session.proxies.update(getattr(settings, "PROXY", None) or {})
        return session

    @staticmethod
    def _fetch(session):
        """Single uncached GET; no automatic read retry or background polling."""
        try:
            response = session.get(PAGE_URL, timeout=(10, 30), allow_redirects=False,
                                   headers={"Accept": "text/html", "Cache-Control": "no-cache"})
            if response.status_code != 200:
                raise LotteryError(f"读取抽奖页 HTTP {response.status_code}，请核对 Cookie、代理或站点状态")
            if len(response.content) > 4 * 1024 * 1024:
                raise LotteryError("抽奖页面过大，已停止")
            response.encoding = "utf-8"
            return parse_page(response.text)
        except requests.RequestException as exc:
            raise LotteryError("读取抽奖页失败，请检查网络或代理；未发起新抽奖") from exc

    @staticmethod
    def _post(session, pending):
        """Submit exactly once: the observed endpoint has no idempotency key."""
        try:
            response = session.post(DRAW_URL, data={"count": str(pending["count"])},
                                    headers={"Accept": "application/json"}, timeout=(10, 60), allow_redirects=False)
            if response.status_code != 200:
                raise LotteryError(f"抽奖 HTTP {response.status_code}，结果待核对；本次未重试")
            if len(response.content) > 2 * 1024 * 1024:
                raise LotteryError("抽奖回执过大，结果待核对")
            return receipt(response.json(), pending)
        except (requests.RequestException, ValueError) as exc:
            raise LotteryError("抽奖请求超时或回执无效，结果待核对；本次未重试") from exc

    def _commit(self, state, candidate):
        """Change live state only after the complete candidate reaches disk."""
        storage.save(self._path(), candidate)
        state.clear()
        state.update(candidate)

    @staticmethod
    def _observe(state, snap, day):
        """Save an account-specific quota observation without changing daily totals."""
        state["active_uid"] = snap.uid
        state["snapshot"] = {"uid": snap.uid, "day": day, "balance": snap.balance,
                             "remaining": snap.remaining, "cost": snap.cost}

    def _reserve(self, state, snap, day, count):
        """Charge local quota before POST; an unknown outcome cannot free it."""
        candidate = copy.deepcopy(state)
        daily = candidate["days"].setdefault(snap.uid + ":" + day, storage.empty_day())
        daily["attempted"] += count
        candidate["pending"] = {"uid": snap.uid, "day": day, "count": count,
                                "cost": snap.cost, "before": snap.balance, "created": time.time()}
        self._commit(state, candidate)

    def _record(self, state, result, settled):
        """Atomically pair confirmed statistics with removal of the pending write."""
        candidate = copy.deepcopy(state)
        pending = candidate["pending"]
        daily = candidate["days"][pending["uid"] + ":" + pending["day"]]
        for key in ("draws", "spent", "change", "compensated"):
            daily[key] = round(daily[key] + settled[key], 2)
        for label, count in settled["prizes"].items():
            daily["prizes"][label] = daily["prizes"].get(label, 0) + count
        remaining = max(0, candidate["snapshot"]["remaining"] - settled["draws"])
        candidate["snapshot"].update(balance=settled["balance"], remaining=remaining)
        candidate["pending"] = None
        self._commit(state, candidate)
        for key in ("draws", "spent", "change", "compensated"):
            result[key] = round(result[key] + settled[key], 2)
        for label, count in settled["prizes"].items():
            result["prizes"][label] = result["prizes"].get(label, 0) + count
        result.update(balance=settled["balance"], remaining=remaining)

    def run(self, generation=None, once=False):
        """Exclude concurrent and stale invocations, including hot reload overlap."""
        if not self._run_lock.acquire(timeout=75 if once else 0):
            return
        try:
            with self._lifecycle:
                if (self._error or self._cancel.is_set()
                        or (generation is not None and generation != self._generation)
                        or not (self._once if once else self._config["enabled"])):
                    return
                config, cancel = copy.deepcopy(self._config), self._cancel
                config["diagnose_only"] = bool(once and self._diagnose_once)
                acknowledge = bool(once and self._acknowledge)
            deadline = time.monotonic() + (75 if once else 0)
            while not cancel.is_set():
                with storage.exclusive(self._path().with_suffix(".lock")) as acquired:
                    if acquired:
                        with self._lifecycle:
                            if cancel.is_set():
                                return
                            if once:
                                self._once = self._diagnose_once = self._acknowledge = False
                        self._execute(config, cancel, acknowledge)
                        return
                if time.monotonic() >= deadline or cancel.wait(0.25):
                    logger.info("不可躺抽奖：已有任务运行，本次跳过")
                    return
        except Exception:
            logger.error("不可躺抽奖：任务异常停止，请检查插件数据目录")
        finally:
            self._run_lock.release()

    def _execute(self, config, cancel, acknowledge=False):
        """Use one session per invocation; refresh preconditions between batches."""
        state, session = None, None
        result = {"time": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"), "day": self._day(),
                  "draws": 0, "spent": 0, "change": 0, "compensated": 0, "prizes": {},
                  "balance": None, "remaining": None, "status": "进行中", "message": "", "uncertain": False}
        try:
            state = storage.load(self._path())
            if state.get("pending") and not (config["diagnose_only"] or acknowledge):
                raise LotteryError("存在待核对请求，自动抽奖已暂停；请到站点核对后解除暂停")
            session = self._session(config)
            snap = self._fetch(session)
            account = snap.uid
            if result["day"] != self._day():
                raise LotteryError("已跨日，本轮停止，等待下一次定时")
            self._observe(state, snap, result["day"])
            result.update(uid=account, balance=snap.balance, remaining=snap.remaining)
            if acknowledge:
                if state.get("pending") and state["pending"]["uid"] != account:
                    raise LotteryError("请切回待核对请求所属账号后解除暂停")
                candidate = copy.deepcopy(state)
                candidate["pending"] = None
                self._commit(state, candidate)
                result.update(status="已核对", message="已解除暂停；原请求仍占用当日目标，本次不抽奖")
                return
            if config["diagnose_only"]:
                result.update(status="连接正常", message=f"单抽 {snap.cost:g} 魔力 · 站点剩余 {snap.remaining} 次"
                              + (" · 活动开放" if snap.ready else " · 活动未开放"))
                return
            while not cancel.is_set():
                if self._day() != result["day"]:
                    result.update(status="已停止", message="已跨日，等待下一次定时")
                    break
                if snap.uid != account:
                    raise LotteryError("登录账号发生变化，本轮已停止")
                self._observe(state, snap, result["day"])
                result.update(balance=snap.balance, remaining=snap.remaining)
                if not snap.ready:
                    result.update(status="已停止", message="站点当前未开放抽奖")
                    break
                if snap.cost > config["max_cost"]:
                    result.update(status="已停止", message="站点单抽费用超过配置上限，请核对价格")
                    break
                key = account + ":" + result["day"]
                used = state["days"].get(key, {}).get("attempted", 0)
                left = min(config["daily_target"] - used, snap.remaining)
                if left <= 0:
                    result.update(status="已完成", message="已达到插件每日目标或站点剩余次数为零")
                    break
                affordable = max(0, int((snap.balance - config["reserve"]) // snap.cost))
                choices = [n for n in snap.batches if n <= min(config["batch"], left, affordable)]
                if not choices:
                    result.update(status="已停止", message="魔力不足或已达到最低保留魔力")
                    break
                if cancel.is_set():
                    break
                self._reserve(state, snap, result["day"], max(choices))
                if cancel.is_set():
                    break
                settled = self._post(session, state["pending"])
                self._record(state, result, settled)
                if state["days"][key]["attempted"] >= config["daily_target"] or result["remaining"] <= 0:
                    result.update(status="已完成", message="已达到插件每日目标或站点上限")
                    break
                if cancel.wait(config["interval"]):
                    break
                if self._day() != result["day"]:
                    result.update(status="已停止", message="已跨日，等待下一次定时")
                    break
                snap = self._fetch(session)
            if cancel.is_set():
                result.update(status="已停止", message="任务已停用或配置已变更，已返回的成功回执已记录")
        except Exception as exc:
            result.update(status="异常停止", message=str(exc) if isinstance(exc, LotteryError)
                          else "站点响应异常或状态保存失败，请检查站点记录")
            logger.warning(f"不可躺抽奖：{result['message']}")
        finally:
            if session is not None:
                session.close()
            if state is not None:
                result["uncertain"] = bool(state.get("pending"))
                state["last"] = copy.deepcopy(result)
                state["history"] = (state["history"] + [copy.deepcopy(result)])[-60:]
                cutoff = (datetime.now(LOCAL_TZ) - timedelta(days=60)).strftime("%Y-%m-%d")
                pending_key = (state["pending"]["uid"] + ":" + state["pending"]["day"]) if state.get("pending") else None
                state["days"] = {key: value for key, value in state["days"].items()
                                 if key.rsplit(":", 1)[-1] >= cutoff or key == pending_key}
                try:
                    storage.save(self._path(), state)
                except LotteryError:
                    result.update(status="异常停止", message="状态保存失败，请检查磁盘并核对站点后再运行", uncertain=True)
            if config["notify"]:
                self._notify(result)

    def _notify(self, result):
        """One compact summary; notification errors never trigger another draw."""
        lines = [f"{result['status']} · 本次 {result['draws']:g} 抽"]
        if result["draws"]:
            lines.append(f"消耗 {result['spent']:,.0f} 魔力 · 余额变化 {result['change']:+,.1f}")
            if result["compensated"]:
                lines.append(f"其中折算奖励 {result['compensated']:,.0f} 魔力")
            prizes = sorted(result["prizes"].items(), key=lambda item: (-item[1], item[0]))
            lines.extend(f"{name} ×{count}" for name, count in prizes[:8])
            if len(prizes) > 8:
                lines.append(f"另有 {len(prizes) - 8} 类奖品，详见插件每日统计")
        if result["balance"] is not None:
            lines.append(f"当前魔力 {result['balance']:,.1f} · 站点剩余约 {result['remaining']} 次")
        if result["message"]:
            lines.append(result["message"])
        if result["uncertain"]:
            lines.append("结果待核对，已暂停自动抽奖；不会自动重发。")
        try:
            self.post_message(mtype=MessageType.Plugin, title="【不可躺】每日抽奖", text="\n".join(lines))
        except Exception:
            logger.warning("不可躺抽奖：通知发送失败，抽奖状态已保留")

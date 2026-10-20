"""PTLGS daily wheel for MoviePilot V3, based on the supplied userscript 1.8.0."""
from __future__ import annotations

import copy
import threading
import time
import uuid
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
from app.schemas.types import NotificationType

from . import storage
from .protocol import WheelError, daily_counts, integer, number, parse_page, rewards

URL = "https://ptlgs.org/luckywheel.php"
DEFINITE_REJECTIONS = {1, 2, 3, 5, 6, 7}


class PtlgsLuckyWheel(_PluginBase):
    """Use MP-owned scheduling and credentials; keep purchases serial and durable."""

    plugin_name = "PTLGS 幸运大转盘"
    plugin_desc = "每日定时抽奖、工分保留、原订单重试及奖品汇总通知。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.1.0"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya"
    plugin_config_prefix = "ptlgsluckywheel_"
    plugin_order = 31
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
        """Fifty actual draws per UTC day, with a local-time schedule after reset."""
        return {"enabled": False, "notify": True, "run_once": False,
                "diagnose_only": False, "cron": "5 8 * * *", "timezone": "Asia/Shanghai",
                "daily_target": 50, "batch": 10, "reserve": 10000,
                "interval": 35, "retries": 3, "use_proxy": False,
                "acknowledge_pending": False}

    @staticmethod
    def _bool(value):
        """Avoid treating the serialized string 'false' as enabled."""
        return value is True or value == 1 or str(value).lower() in {"true", "yes", "on"}

    def init_plugin(self, config=None):
        """Cancel previous work and validate a fresh immutable run configuration."""
        with self._lifecycle:
            self._cancel.set()
            self._generation += 1
            self._cancel = threading.Event()
            self._once = False
            self._diagnose_once = False
            self._trigger = None
            self._error = ""
            values = {**self.defaults(), **(config or {})}
            try:
                for name in ("enabled", "notify", "run_once", "diagnose_only", "use_proxy", "acknowledge_pending"):
                    values[name] = self._bool(values[name])
                for name, lower, upper in (("daily_target", 1, 500), ("batch", 1, 10),
                                           ("interval", 3, 900), ("retries", 0, 5)):
                    values[name] = integer(values[name])
                    if not lower <= values[name] <= upper:
                        raise WheelError(f"{name} 须在 {lower}–{upper} 之间")
                if values["batch"] not in (1, 3, 10):
                    raise WheelError("连抽数量仅支持 1、3、10")
                values["reserve"] = number(values["reserve"])
                values["timezone"] = str(values["timezone"]).strip()
                ZoneInfo(values["timezone"])
                values["cron"] = str(values["cron"]).strip()
                self._trigger = CronTrigger.from_crontab(values["cron"], timezone=values["timezone"])
                self._once = values["run_once"] or values["diagnose_only"] or values["acknowledge_pending"]
            except Exception as exc:
                self._error = str(exc) if isinstance(exc, WheelError) else "配置无效，请检查五段 Cron 和 IANA 时区"
            self._config = values
            self._acknowledge = bool(values.get("acknowledge_pending"))
            self._diagnose_once = bool(values.get("diagnose_only"))
            changed = values.get("run_once") or self._diagnose_once or self._acknowledge
            values["run_once"] = values["diagnose_only"] = values["acknowledge_pending"] = False
            if changed:
                try:
                    if self.update_config(copy.deepcopy(values)) is False:
                        raise WheelError("一次性开关复位失败，已取消执行")
                except Exception:
                    self._error = "一次性开关复位失败，已取消执行"
            if self._error:
                self._once = False
                logger.error(f"PTLGS 大转盘：{self._error}")

    def get_state(self):
        """Allow an explicit one-shot diagnostic/run while the daily switch is off."""
        return not self._error and (self._config.get("enabled", False) or self._once)

    def get_service(self):
        """MP owns both Cron and one-shot jobs; no private scheduler or worker thread."""
        with self._lifecycle:
            if self._error or self._cancel.is_set():
                return []
            jobs = []
            prefix = self.__class__.__name__
            options = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 120}
            if self._config["enabled"]:
                jobs.append({"id": prefix + ".Daily", "name": "PTLGS 每日抽奖",
                             "trigger": self._trigger,
                             "func": partial(self.run, generation=self._generation), "kwargs": dict(options)})
            if self._once:
                jobs.append({"id": prefix + ".Once", "name": "PTLGS 运行一次",
                             "trigger": DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=3)),
                             "func": partial(self.run, generation=self._generation, once=True), "kwargs": dict(options)})
            return jobs

    def stop_service(self):
        """Cancel interruptible waits; allow an already-sent response to be recorded."""
        with self._lifecycle:
            self._cancel.set()
            self._once = False
            self._diagnose_once = False
            self._acknowledge = False

    @staticmethod
    def get_command():
        """No chat command is needed for this scheduled job."""
        return []

    def get_api(self):
        """The native MP configuration and detail pages need no custom endpoints."""
        return []

    def get_form(self):
        """Use the host's Cron picker and save control."""
        from .ui import form
        return form(), self.defaults()

    def get_page(self):
        """Render only cached results; opening the page never submits a draw."""
        from .ui import page
        try:
            return page(storage.load(self._path()), self._error, today=self._day())
        except WheelError as exc:
            return page({}, str(exc), today=self._day())

    def _path(self):
        """Per-instance durable state, separate from updateable plugin source."""
        return self.get_data_path() / "wheel-state.json"

    @staticmethod
    def _day():
        """Site resets at 00:00 UTC, regardless of MP's schedule timezone."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _session(self, config):
        """Use MP's PTLGS site record; never export credentials into plugin results."""
        site = SiteOper().get_by_domain("ptlgs.org")
        cookie = str(getattr(site, "cookie", "") or "").strip()
        if not site or not cookie or cookie.lower() == "cookie":
            raise WheelError("请在 MP 站点管理添加 PTLGS 并更新 Cookie")
        try:
            source = urlsplit(str(getattr(site, "url", "") or "https://ptlgs.org"))
            valid = (source.scheme == "https" and source.hostname == "ptlgs.org"
                     and source.port in (None, 443) and not source.username and not source.password)
        except ValueError:
            valid = False
        if not valid:
            raise WheelError("PTLGS 站点地址必须使用 https://ptlgs.org")
        session = requests.Session()
        session.trust_env = False
        # Use the jar so response Set-Cookie refreshes are honored by later GET/POSTs.
        # A static Cookie header would shadow those refreshed session cookies.
        for pair in cookie.split(";"):
            name, separator, value = pair.strip().partition("=")
            if separator and name:
                session.cookies.set(name, value, domain="ptlgs.org", path="/")
        session.headers.update({"User-Agent": getattr(site, "ua", None) or "Mozilla/5.0",
                                "Referer": URL, "Origin": "https://ptlgs.org",
                                "X-Requested-With": "XMLHttpRequest"})
        if config["use_proxy"]:
            session.proxies.update(getattr(settings, "PROXY", None) or {})
        return session

    def _fetch(self, session):
        """Read account/quota/token afresh before each new batch."""
        try:
            response = session.get(URL, timeout=(10, 30), allow_redirects=False,
                                   headers={"Cache-Control": "no-cache", "Accept": "text/html"})
            if response.status_code != 200:
                raise WheelError(f"读取大转盘 HTTP {response.status_code}，请核对 Cookie、代理或站点状态")
            if len(response.content) > 4 * 1024 * 1024:
                raise WheelError("站点页面过大，已停止")
            return parse_page(response.text)
        except requests.RequestException as exc:
            raise WheelError("读取大转盘失败，请检查网络或代理；未发起新抽奖") from exc

    @staticmethod
    def _post(session, snapshot, pending):
        """Only this method sends a purchase; requests performs no automatic retries."""
        count = pending["count"]
        body = {"action": "spin_multi" if count > 1 else "spin", "csrf": snapshot.csrf,
                "request_key": pending["key"]}
        if count > 1:
            body["count"] = str(count)
        return session.post(URL, data=body, timeout=(10, 30), allow_redirects=False)

    def _purchase(self, session, snapshot, state, config, cancel):
        """Bounded same-key retries, including timeout, malformed JSON and throttling."""
        pending = state["pending"]
        if pending["uid"] != snapshot.uid:
            raise WheelError("待确认订单属于其他账号，请切回原账号核对")
        if pending["day"] != self._day() or time.time() - pending["created"] > 900:
            raise WheelError("存在超过 15 分钟或跨日的待确认订单，请到站点核对后使用配置中的清除开关")
        for attempt in range(config["retries"] + 1):
            if cancel.is_set():
                raise WheelError("任务已停止，待确认订单已保留")
            if pending["day"] != self._day() or time.time() - pending["created"] > 900:
                raise WheelError("已跨日或订单重试窗口已结束，请核对待确认订单")
            data, ret, http_status = None, None, None
            try:
                response = self._post(session, snapshot, pending)
                http_status = response.status_code
                if http_status == 200:
                    result = response.json()
                    if isinstance(result, dict) and type(result.get("ret")) is int:
                        ret, data = result["ret"], result.get("data")
            except (requests.RequestException, ValueError):
                pass  # Never log a URL, Cookie, CSRF token or arbitrary server text.
            if ret == 0:
                if not isinstance(data, dict):
                    raise WheelError("站点返回成功但缺少明细，保留原订单待核对")
                return data
            if ret in DEFINITE_REJECTIONS:
                # With prior transport ambiguity, a later rejection does not prove
                # the original attempt did not commit (e.g. a now-expired CSRF).
                if not pending.get("uncertain"):
                    state["pending"] = None
                    storage.save(self._path(), state)
                raise WheelError(f"站点拒绝本次抽奖（ret={ret}），请检查 Cookie、余额、活动或今日次数")
            pending["uncertain"] = True
            storage.save(self._path(), state)
            if http_status in (301, 302, 303, 307, 308, 401, 403):
                raise WheelError(f"抽奖 HTTP {http_status}，请核对登录状态；原订单已保留")
            if attempt == config["retries"]:
                break
            wait = min(300, max(config["interval"], 30) * (2 ** attempt))
            if http_status == 429:
                try:
                    retry_after = integer(response.headers.get("Retry-After", wait))
                except WheelError:
                    retry_after = wait
                if retry_after > 300:
                    raise WheelError("站点要求较长等待，结束本轮并保留原订单")
                wait = max(wait, retry_after)
            logger.warning(f"PTLGS 大转盘：结果未确认，{wait} 秒后重试原订单（{attempt + 1}/{config['retries']}）")
            if cancel.wait(wait):
                raise WheelError("任务已停止，待确认订单已保留")
            snapshot = self._fetch(session)
            if snapshot.uid != pending["uid"]:
                raise WheelError("登录账号已变化，原订单未重试")
        raise WheelError("重试次数已用完，结果仍待确认；已保留原订单，未创建新订单")

    def _record(self, state, data, result):
        """Commit confirmed count, rewards and pending removal in one atomic replace."""
        pending = state["pending"]
        count = pending["count"]
        if "count" in data and integer(data["count"]) != count:
            raise WheelError("返回抽奖次数与原订单不符，保留订单待核对")
        after = number(data["bonus"])
        limit, remaining = daily_counts(data.get("daily"))
        try:
            won = rewards(data, count)
        except WheelError:
            won = {"奖品明细缺失（请查看站点记录）": count}
        cost = round(pending["cost"] * count, 1)
        delta = round(after - pending["before"], 1)
        key = pending["uid"] + ":" + pending["day"]
        day = state["days"].setdefault(key, {"draws": 0, "site_used": 0, "spent": 0, "change": 0, "prizes": {}})
        day["draws"] += count
        day["site_used"] = max(day["site_used"], pending["used_before"] + count, limit - remaining)
        day["spent"] = round(day["spent"] + cost, 1)
        day["change"] = round(day["change"] + delta, 1)
        for label, amount in won.items():
            day["prizes"][label] = day["prizes"].get(label, 0) + amount
            result["prizes"][label] = result["prizes"].get(label, 0) + amount
        result["draws"] += count
        result["spent"] = round(result["spent"] + cost, 1)
        result["change"] = round(result["change"] + delta, 1)
        result["balance"], result["remaining"] = after, remaining
        state["active_uid"] = pending["uid"]
        state["snapshot"] = {"uid": pending["uid"], "day": pending["day"],
                             "balance": after, "remaining": remaining, "limit": limit}
        state["pending"] = None
        state["last"] = copy.deepcopy(result)
        storage.save(self._path(), state)

    def run(self, generation=None, once=False):
        """Fill the configured daily target; repeated Cron calls cannot add a quota."""
        # A save-and-run can arrive while the canceled previous request is still
        # returning. Give that request time to record its receipt before taking over.
        if not self._run_lock.acquire(timeout=45 if once else 0):
            return
        try:
            with self._lifecycle:
                if (self._error or self._cancel.is_set()
                        or (generation is not None and generation != self._generation)
                        or not (self._once if once else self._config["enabled"])):
                    return
                config, cancel = copy.deepcopy(self._config), self._cancel
                config["diagnose_only"] = bool(once and self._diagnose_once)
                acknowledge = once and self._acknowledge
            deadline = time.monotonic() + (45 if once else 0)
            while not cancel.is_set():
                with storage.exclusive(self._path().with_suffix(".lock")) as acquired:
                    if acquired:
                        with self._lifecycle:
                            if cancel.is_set():
                                return
                            if once:
                                self._once = False
                                self._diagnose_once = False
                                self._acknowledge = False
                        self._execute(config, cancel, acknowledge)
                        return
                if time.monotonic() >= deadline:
                    logger.info("PTLGS 大转盘：已有任务运行，本次跳过")
                    return
                if cancel.wait(0.25):
                    return
        except Exception:
            # Unexpected infrastructure errors must never become extra purchases.
            logger.error("PTLGS 大转盘：任务异常停止，请检查插件数据目录和宿主日志")
        finally:
            self._run_lock.release()

    def _execute(self, config, cancel, acknowledge=False):
        """Own one session and one durable state for a complete daily invocation."""
        state, session = None, None
        result = {"time": datetime.now(ZoneInfo(config["timezone"])).isoformat(timespec="seconds"),
                  "day": self._day(), "draws": 0, "spent": 0, "change": 0, "prizes": {},
                  "balance": None, "remaining": None, "status": "进行中", "message": "", "uncertain": False}
        try:
            state = storage.load(self._path())
            session = self._session(config)
            snapshot = self._fetch(session)
            account = snapshot.uid
            if result["day"] != self._day():
                raise WheelError("站点已跨日，请重新检查连接或等待下一次定时")
            self._observe(state, snapshot, result["day"])
            result.update(uid=account, balance=snapshot.balance, remaining=snapshot.remaining)
            if acknowledge:
                pending = state.get("pending")
                if pending and pending["uid"] != account:
                    raise WheelError("请切换回待确认订单的原账号后再清除")
                state["pending"] = None
                result.update(status="已核对", message="已清除待确认标记；本次只核对，不发起抽奖")
                storage.save(self._path(), state)
                return
            if config["diagnose_only"]:
                result.update(status="诊断成功", message=f"登录正常，单抽 {snapshot.cost:g} 工分；今日剩余 {snapshot.remaining}/{snapshot.limit}")
                return
            # A pending order must be resolved first even if its previous success
            # consumed the last remaining draw or reduced the balance to the reserve.
            if state.get("pending"):
                data = self._purchase(session, snapshot, state, config, cancel)
                self._record(state, data, result)
                if cancel.wait(config["interval"]):
                    result.update(status="已停止", message="配置已变更或任务已停用")
                    return
                snapshot = self._fetch(session)
            while not cancel.is_set():
                if result["day"] != self._day():
                    result.update(status="已停止", message="站点已跨日，本轮结束，等待下一次定时")
                    break
                if snapshot.uid != account:
                    raise WheelError("登录账号发生变化，本轮已停止")
                self._observe(state, snapshot, result["day"])
                if not snapshot.ready:
                    result.update(status="已停止", message="站点活动暂不可抽奖")
                    break
                key = account + ":" + self._day()
                used = max(snapshot.limit - snapshot.remaining,
                           state["days"].get(key, {}).get("site_used", 0))
                target_left = min(config["daily_target"] - used, snapshot.remaining)
                if target_left <= 0:
                    result.update(status="已完成", message=f"今日已抽 {used} 次，已达到目标或站点上限")
                    break
                affordable = max(0, int((snapshot.balance - config["reserve"]) // snapshot.cost))
                options = [n for n in snapshot.batches if n <= min(config["batch"], target_left, affordable)]
                if not options:
                    result.update(status="已停止", message="工分不足或已达到最低保留工分")
                    break
                if cancel.is_set():
                    break
                count = max(options)
                state["pending"] = {"key": str(uuid.uuid4()), "count": count,
                                    "uid": account, "day": result["day"], "created": time.time(),
                                    "cost": snapshot.cost, "before": snapshot.balance,
                                    "used_before": used, "uncertain": False}
                # Persistence must succeed before any POST is sent.
                storage.save(self._path(), state)
                data = self._purchase(session, snapshot, state, config, cancel)
                self._record(state, data, result)
                if cancel.is_set():
                    break
                if state["days"][key]["site_used"] >= config["daily_target"] or result["remaining"] == 0:
                    result.update(status="已完成", message="已达到每日目标或站点上限")
                    break
                if cancel.wait(config["interval"]):
                    break
                snapshot = self._fetch(session)
            if cancel.is_set():
                result.update(status="已停止", message="配置已变更或任务已停用；已提交结果仍已记录")
        except Exception as exc:
            result.update(status="异常停止", message=str(exc) if isinstance(exc, WheelError)
                          else "站点返回异常或状态保存失败，本轮停止，请查看站点抽奖记录")
            logger.warning(f"PTLGS 大转盘：{result['message']}")
        finally:
            if session is not None:
                session.close()
            if state is not None:
                result["uncertain"] = bool(state.get("pending"))
                state["last"] = copy.deepcopy(result)
                state["history"] = (state["history"] + [copy.deepcopy(result)])[-60:]
                # Retain per-day statistics for 60 UTC days; never prune pending.
                cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
                state["days"] = {key: value for key, value in state["days"].items() if key.split(":")[-1] >= cutoff}
                try:
                    storage.save(self._path(), state)
                except WheelError:
                    result.update(status="异常停止", message="状态保存失败，请核对站点记录后再运行", uncertain=True)
            if config["notify"]:
                self._notify(result)

    @staticmethod
    def _observe(state, snapshot, day):
        """Cache account and dated quota without resetting the daily prize ledger."""
        state["active_uid"] = snapshot.uid
        state["snapshot"] = {"uid": snapshot.uid, "day": day, "balance": snapshot.balance,
                             "remaining": snapshot.remaining, "limit": snapshot.limit}

    def _notify(self, result):
        """One concise MP notification per run; failure cannot repeat a purchase."""
        lines = [f"{result['status']} · 本次 {result['draws']} 抽",
                 f"消耗 {result['spent']:,.0f} 工分 · 工分变化 {result['change']:+,.1f}"]
        if result.get("balance") is not None:
            lines.append(f"当前工分 {result['balance']:,.1f} · 今日剩余 {result['remaining']} 抽")
        prizes = [(label, count) for label, count in result["prizes"].items() if label != "谢谢参与"]
        if prizes:
            lines.append("奖品：" + "、".join(f"{label} ×{count}" for label, count in sorted(prizes, key=lambda x: -x[1])))
        if result.get("message"):
            lines.append(result["message"])
        if result["uncertain"]:
            lines.append("存在待确认订单，下次优先核对原订单。")
        try:
            self.post_message(mtype=NotificationType.Plugin, title="【PTLGS】大转盘", text="\n".join(lines))
        except Exception:
            logger.warning("PTLGS 大转盘：通知发送失败，抽奖记录已保留，不会因此重抽")

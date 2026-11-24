import threading
import time
from datetime import datetime

import requests
from apscheduler.triggers.interval import IntervalTrigger
from app.db.oper.site import SiteOper
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase

try:
    from app.schemas.types import MessageType
except ImportError:  # Earlier V3 hosts used the old enum name.
    from app.schemas.types import NotificationType as MessageType

from .protocol import COST, END, HOME, PRIZES, START, TZ, cooldown, inspect_page, receipt


class HdhomeLottery(_PluginBase):
    plugin_name = "家园站庆抽奖"
    plugin_desc = "使用站点 Cookie 参与家园十二周年抽奖，按活动冷却和预算执行。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.1.0"
    plugin_author = "xchenya"
    author_url = "https://github.com/xchenya"
    plugin_config_prefix = "hdhomelottery_"
    plugin_order = 30
    auth_level = 2
    _lock = threading.RLock()
    defaults = dict(enabled=False, prize="", limit=1, reserve=0, resume=False,
                    cooldown_seconds=61, notify_on_win=False)

    def init_plugin(self, config=None):
        with self._lock:
            self.cfg = {**self.defaults, **(config or {})}
            self.stopped = False
            self.state = self.get_data("event202611") or {}
            if self.cfg.get("resume"):
                self.cfg["resume"] = False
                self.update_config(self.cfg)
                self.state.pop("pause", None)
                self.save_data("event202611", self.state)

    def get_state(self):
        return self.cfg.get("enabled") is True

    def get_service(self):
        if not self.get_state() or time.time() >= END:
            return []
        return [dict(id="HdhomeLottery.draw", name=self.plugin_name, func=self.tick,
                     trigger=IntervalTrigger(seconds=1, end_date=datetime.fromtimestamp(END, TZ)),
                     kwargs={"max_instances": 1, "coalesce": True})]

    def get_form(self):
        fields = [
            ("VSwitch", dict(model="enabled", label="启用自动抽奖")),
            ("VSelect", dict(model="prize", label="目标奖品", items=[
                {"title": v, "value": k} for k, v in PRIZES.items()])),
            ("VTextField", dict(model="limit", label="本次活动最多提交次数（每次 1 万魔力）", type="number", min=1)),
            ("VTextField", dict(model="reserve", label="抽奖后至少保留魔力", type="number", min=0)),
            ("VTextField", dict(model="cooldown_seconds", label="抽奖冷却（秒）", type="number",
                                min=1, step=1, hint="默认 61 秒，实际等待至少满足站点冷却", persistent_hint=True)),
            ("VSwitch", dict(model="notify_on_win", label="中奖时发送 MP 通知")),
            ("VSwitch", dict(model="resume", label="已核对站内记录，解除暂停（保留已用次数）")),
        ]
        return [dict(component="VForm", content=[
            dict(component="VAlert", text="北京时间 11 月 26 日 00:00 截止。中奖即停。友站邀请仅供从未拥有该站账号的本人使用。"),
            *[dict(component=name, props=props) for name, props in fields]])], self.defaults.copy()

    def get_page(self):
        s = self.get_data("event202611") or {}
        return [dict(component="VCardText", text=f"累计提交 {s.get('count', 0)} 次 · "
                     f"{s.get('pause') or s.get('last') or '等待运行'}")]

    def get_api(self):
        return []

    @staticmethod
    def get_command():
        return []

    def stop_service(self):
        with self._lock:
            self.stopped = True

    def pause(self, reason):
        self.state["pause"] = reason
        self.save_data("event202611", self.state)
        logger.info(f"家园站庆抽奖：{reason}")

    def tick(self):
        with self._lock:
            now = time.time()
            s = self.state
            if (self.stopped or not self.get_state() or not START <= now < END
                    or s.get("pause") or now < s.get("next", 0)):
                return
            target = str(self.cfg.get("prize"))
            try:
                limit, reserve = int(self.cfg["limit"]), int(self.cfg["reserve"])
                raw_delay = str(self.cfg["cooldown_seconds"]).strip()
                delay = int(raw_delay) if raw_delay.isdecimal() else 0
                if target not in PRIZES or limit < 1 or reserve < 0 or delay < 1:
                    raise ValueError
            except (TypeError, ValueError):
                self.pause("请设置目标奖品、正整数次数、非负保留魔力和正整数冷却秒数，再解除暂停")
                return
            if s.get("count", 0) >= limit:
                return
            try:
                self.draw(target, reserve, delay)
            except requests.RequestException:
                self.pause("网络异常，请核对我的抽奖记录后解除暂停")
            except ValueError as exc:
                self.pause(str(exc))
            except Exception as exc:
                self.pause("运行异常（" + type(exc).__name__ + "），请核对站内记录")

    def draw(self, target, reserve, delay):
        site = SiteOper().get_by_domain("hdhome.org")
        cookie = getattr(site, "cookie", None)
        if not cookie:
            raise ValueError("请在 MP 站点管理更新家园 Cookie")
        with requests.Session() as session:
            session.headers.update({"Cookie": cookie, "User-Agent": getattr(site, "ua", None) or "Mozilla/5.0"})
            if getattr(site, "proxy", False):
                session.proxies.update(settings.PROXY or {})
            page = session.get(HOME, timeout=20, allow_redirects=False)
            if page.status_code != 200:
                raise ValueError("活动页未正常打开，请检查站点登录和网络")
            balance, url = inspect_page(page.content.decode(page.apparent_encoding or "utf-8"), target)
            if balance < reserve + COST:
                raise ValueError("余额不足，或本次抽奖将低于保留魔力")
            now = time.time()
            if now >= END:
                return
            s = self.state
            wait_seconds = max(delay, cooldown(now))
            s.update(count=s.get("count", 0) + 1, next=now + wait_seconds,
                     pause="提交结果待核对，请查看站内我的抽奖记录")
            self.save_data("event202611", s)
            result = session.get(url, headers={"Referer": HOME}, timeout=20, allow_redirects=False)
            outcome = receipt(result.content.decode(result.apparent_encoding or "utf-8")) if result.status_code == 200 else "结果待核对"
            s["last"] = f"{datetime.now(TZ):%m-%d %H:%M:%S} {PRIZES[target]} · {outcome}"
            s["next"] = time.time() + wait_seconds
            if outcome == "未中奖":
                s.pop("pause", None)
            else:
                s["pause"] = s["last"]
            self.save_data("event202611", s)
            logger.info("家园站庆抽奖：" + s["last"])
            if outcome == "已中奖" and self.cfg.get("notify_on_win") is True:
                try:
                    self.post_message(mtype=MessageType.Plugin, title="家园站庆抽奖 · 中奖", text=s["last"])
                except Exception:
                    logger.warning("家园站庆抽奖：中奖通知发送失败，中奖记录已保存")

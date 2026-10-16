"""思齐自动收垃圾（MoviePilot V3 移植版）。

原作者 bfjy，源码来自 bfjy2024/MoviePilot-Plugins，按原仓库 GPL-3.0
许可改造。V3 适配由 xchenya 维护；搬砖已获用户宿主日志验证，新调度未经真实联调。
"""
import json
import math
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler


from app.sdk.events import Event, eventmanager
from app.db.oper.site import SiteOper
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class ActionResponse(BaseModel):
    success: bool
    message: str = ""


class StatsResponse(BaseModel):
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)


class SiQiCleanBeach(_PluginBase):
    plugin_name = "思齐自动收垃圾"
    plugin_desc = "自动清理沙滩和可选搬砖，支持站点冷却或固定时间；新调度未经真实联调。"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/Moviepilot_A.png"
    plugin_version = "2.3.0"
    plugin_author = "bfjy（V3 适配：xchenya）"
    author_url = "https://bfjy2024.github.io/bfjy"
    plugin_config_prefix = "siqicleanbeach_"
    plugin_order = 30
    auth_level = 2

    SITE_DOMAIN = "si-qi.xyz"
    BASE_URL = "https://si-qi.xyz"
    MOWAN_URL = f"{BASE_URL}/mowan.php"
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"

    _enabled = False
    _cookie = ""
    _schedule_mode = "interval"
    _cron = "1 */2 * * *"
    _interval_minutes = 121
    _notify = True
    _run_once = False

    ITEM_ICONS = {
        "砖块": "🧱",
        "木材": "🪵",
        "塑料袋": "🛍️",
        "瓶子": "🧴",
        "螺丝": "🔩",
        "旧电池": "🔋",
        "破铜片": "🪙",
        "木工件": "🪚",
        "塑料件": "🪣",
        "简易工具": "🛠️",
        "能量碎片": "⚡",
        "魔丸胚胎": "🥚",
        "魔丸": "⚗️",
        "蚯蚓": "🪱"
    }

    ITEM_COLORS = {
        "砖块": "#a0522d",
        "木材": "#f39c12",
        "塑料袋": "#3498db",
        "瓶子": "#1abc9c",
        "螺丝": "#95a5a6",
        "旧电池": "#2c3e50",
        "破铜片": "#e67e22",
        "木工件": "#d4a574",
        "塑料件": "#5dade2",
        "简易工具": "#7f8c8d",
        "能量碎片": "#f1c40f",
        "魔丸胚胎": "#d7bde2",
        "魔丸": "#8e44ad",
        "蚯蚓": "#e67e22"
    }

    def __init__(self):
        super().__init__()
        # V3 支持插件分身；可变数据和运行锁均属于当前实例。
        self._lock = threading.Lock()
        self._schedule_lock = threading.RLock()
        self._scheduler = None
        self._next_run_at = None
        self._schedule_generation = 0
        self._auth_blocked = False
        self._stop_event = threading.Event()
        self._stopped = False
        self._session = None
        self._inventory_auth_failed = False
        self._enabled = False
        self._cookie = ""
        self._user_agent = self.USER_AGENT
        self._schedule_mode = "interval"
        self._cron = "1 */2 * * *"
        self._interval_minutes = 121
        self._auto_brick = False
        self._notify = True
        self._run_once = False
        self._inventory: Dict[str, Dict[str, Any]] = {}
        self._stats: Dict[str, Any] = {
            "last_update": None,
            "last_result": "",
            "total_items_count": 0,
            "history": [],
        }

    def _queue_manual_run(self) -> bool:
        """预先占用运行锁，防止多个请求同时被报告为已启动。"""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._stop_event.clear()
            threading.Thread(target=self.run_clean_task, kwargs={"reserved": True}, daemon=True).start()
        except Exception:
            self._lock.release()
            raise
        return True

    def init_plugin(self, config: dict = None):
        config = config or {}
        running = self._lock.locked()
        self.stop_service()
        self._auth_blocked = False
        site_cookie = self.__get_site_cookie()

        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._schedule_mode = config.get("schedule_mode", "interval" if config else "auto")
        if self._schedule_mode not in {"auto", "cron", "interval"}:
            self._schedule_mode = "interval"
        self._cron = (config.get("cron") or "1 */2 * * *").strip()
        self._interval_minutes = self.__safe_int(config.get("interval_minutes"), 121, min_value=1)
        self._auto_brick = bool(config.get("auto_brick", False))
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))

        stats = config.get("stats", {})
        if stats and not running:
            self._stats.update(stats)
        
        inventory = config.get("inventory", {})
        if inventory and not running:
            self._inventory = inventory

        if self._schedule_mode == "auto" and self._stats.get("due_schedule_version") != 1:
            # 旧版本的下次检查时间可能带121/1440分钟限制，升级后先只读同步。
            self._stats.pop("beach_due_at", None)
            self._stats.pop("brick_due_at", None)
            self._stats["due_schedule_version"] = 1
        self._stopped = False

        logger.info(
            f"思齐自动收垃圾插件初始化完成：enabled={self._enabled}, "
            f"schedule_mode={self._schedule_mode}, interval_minutes={self._interval_minutes}"
        )
        if not running:
            self._stop_event.clear()

        if self._run_once:
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "auto_brick": self._auto_brick,
                "cookie": self._cookie,
                "schedule_mode": self._schedule_mode,
                "cron": self._cron,
                "interval_minutes": self._interval_minutes,
                "notify": self._notify,
                "run_once": False,
                "stats": self._stats,
                "inventory": self._inventory
            })
            logger.info("收到配置页立即运行请求，后台启动收垃圾任务")
            if not self._queue_manual_run():
                logger.warning("已有思齐清理任务正在执行，本次立即运行请求已跳过")
        self.__schedule_next()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/siqi_clean_beach",
                "event": EventType.PluginAction,
                "desc": "立即清理思齐沙滩",
                "category": "站点",
                "data": {
                    "action": "siqi_clean_beach"
                }
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/SiQiCleanBeach/run",
                "endpoint": self.run_once_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即清理思齐沙滩",
                "description": "按当前插件配置立即执行一次清理沙滩任务。",
                "response_model": ActionResponse
            },
            {
                "path": "/SiQiCleanBeach/stats",
                "endpoint": self.get_stats_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取收垃圾统计数据",
                "description": "获取思齐收垃圾的统计数据。",
                "response_model": StatsResponse
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []

        if self._schedule_mode == "auto":
            return []  # 自动模式自行安排一次性到期任务，避免重复注册周期任务。

        if self._schedule_mode == "interval":
            try:
                trigger = IntervalTrigger(minutes=self._interval_minutes)
                logger.info(f"使用间隔触发器：每{self._interval_minutes}分钟执行一次")
                return [{
                    "id": "SiQiCleanBeach",
                    "name": "思齐自动收垃圾",
                    "trigger": trigger,
                    "func": self.run_clean_task,
                    "kwargs": {"scheduled": True}
                }]
            except Exception as e:
                logger.warning(f"间隔触发器创建失败：{e}")
                return []
        else:
            if not self._cron:
                return []
            try:
                trigger = CronTrigger.from_crontab(self._cron)
                logger.info(f"使用Cron触发器：{self._cron}")
                return [{
                    "id": "SiQiCleanBeach",
                    "name": "思齐自动收垃圾",
                    "trigger": trigger,
                    "func": self.run_clean_task,
                    "kwargs": {"scheduled": True}
                }]
            except ValueError as e:
                logger.warning(f"Cron配置无效：{e}")
                return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_cookie = self.__get_site_cookie()
        cookie_value = self._cookie or site_cookie or ""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "run_once",
                                            "label": "立即运行一次",
                                            "hint": "保存配置后执行，并自动关闭"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "schedule_mode",
                                            "label": "定时模式",
                                            "items": [
                                                {"title": "按站点冷却（推荐）", "value": "auto"},
                                                {"title": "固定时间（Cron）", "value": "cron"},
                                                {"title": "旧版固定间隔（兼容）", "value": "interval"},
                                            ],
                                            "hint": "自动模式按沙滩两小时冷却、搬砖每日零点独立定时，到期后约15秒执行；等待期间不访问站点。"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "Cron表达式",
                                            "placeholder": "5位 Cron 表达式",
                                            "hint": "固定时间模式生效，例如 5 0,2,4,6,8,10,12,14,16,18,20,22 * * *；使用宿主时区"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "interval_minutes",
                                            "label": "旧版执行间隔（分钟）",
                                            "type": "number",
                                            "min": 1,
                                            "hint": "间隔模式下生效，例如 121",
                                            "value": 121
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VSwitch", "props": {"model": "auto_brick", "label": "自动搬砖（默认关闭）"}}
                            ]}
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "思齐 Cookie",
                                            "rows": 3,
                                            "placeholder": "填写包含 c_secure_pass 的完整 Cookie",
                                            "hint": "留空时读取站点管理中的思齐 Cookie"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": self._enabled,
            "auto_brick": self._auto_brick,
            "cookie": cookie_value,
            "schedule_mode": self._schedule_mode,
            "cron": self._cron,
            "interval_minutes": self._interval_minutes,
            "notify": self._notify,
            "run_once": False,
            "stats": self._stats,
            "inventory": self._inventory
        }

    def get_page(self) -> List[dict]:
        inventory = self._inventory
        stats = self._stats
        
        last_update = stats.get("last_update", "")
        if last_update:
            try:
                last_update = datetime.fromtimestamp(last_update).strftime("%Y-%m-%d %H:%M:%S")
            except:
                last_update = str(last_update)

        filtered_inventory = inventory
        
        total_items = len(filtered_inventory)
        total_count = sum(item.get("count", 0) for item in filtered_inventory.values())
        has_items = {k: v for k, v in filtered_inventory.items() if v.get("count", 0) > 0}
        has_items_count = len(has_items)

        sorted_items = sorted(
            has_items.items(),
            key=lambda x: x[1].get("count", 0),
            reverse=True
        )

        history = stats.get("history", [])[-5:]

        if self._schedule_mode == "auto":
            schedule_info = "按站点冷却"
        elif self._schedule_mode == "interval":
            schedule_info = f"每{self._interval_minutes}分钟"
        else:
            schedule_info = f"Cron: {self._cron}"

        last_result = stats.get("last_result", "-")
        if "clean_result" in stats and "brick_result" in stats:
            last_result = f"清理：{stats['clean_result']}；搬砖：{stats['brick_result']}"

        return [
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "🏖️ 思齐收垃圾数据面板"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "props": {"class": "mb-4"},
                                "content": [
                                    self.__stat_card("📦", "物品总数", f"{total_count:,}", "个", "primary"),
                                    self.__stat_card("📊", "物品种类", f"{total_items}", "种", "info"),
                                    self.__stat_card("✅", "有物品", f"{has_items_count}", "种", "success"),
                                    self.__stat_card("🕐", "库存刷新", last_update or "-", "", "warning"),
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    self.__info_col("⏰ 定时模式", schedule_info),
                                    self.__info_col("🏖️ 沙滩下次执行时间", self.__due_text("beach_due_at", compact=True)),
                                    self.__info_col("🧱 搬砖下次执行时间", self.__due_text("brick_due_at", compact=True) if self._auto_brick else "未开启"),
                                    self.__info_col("⏳ 沙滩时间来源", stats.get("beach_due_source", "等待首次同步")),
                                    self.__info_col("📝 最后结果", last_result),
                                    self.__info_col("🗑️ 清理结果", stats.get("clean_result", "-")),
                                    self.__info_col("🧱 搬砖结果", stats.get("brick_result", "-")),
                                    self.__info_col("🧱 本次 / 今日 / 库存", f"{stats.get('bricks_moved', 0)} / {stats.get('daily_bricks') if stats.get('daily_bricks') is not None else '未知'} / {inventory.get('砖块', {}).get('count', '未知')}"),
                                    self.__info_col("📦 库存状态", "本次已刷新" if stats.get("inventory_refreshed") else "缓存，非本次刷新"),
                                    self.__info_col("🔔 通知", "开启" if self._notify else "关闭"),
                                    self.__info_col("🍪 Cookie", "已配置" if self._cookie else "未配置"),
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "🎯 物品清单"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12},
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {
                                                    "style": "display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px;"
                                                },
                                                "content": self.__inventory_items(sorted_items) if sorted_items else [
                                                    {
                                                        "component": "div",
                                                        "props": {"class": "text-center text-medium-emphasis pa-4", "style": "grid-column: 1 / -1; color: #999;"},
                                                        "text": "🏝️ 暂无物品数据"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VCard",
                "props": {"variant": "tonal"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "📋 执行记录"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VTable",
                                "props": {"hover": True, "dense": True},
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {"component": "th", "text": "时间"},
                                                    {"component": "th", "text": "结果"},
                                                    {"component": "th", "text": "物品总数"},
                                                    {"component": "th", "text": "状态"},
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "tbody",
                                        "content": self.__history_rows(history) if history else [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {
                                                        "component": "td",
                                                        "props": {"colspan": 4, "class": "text-center text-medium-emphasis"},
                                                        "text": "暂无执行记录"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        # 已发出的请求不能撤回；阻断当前任务后续请求。
        with self._schedule_lock:
            self._stop_event.set()
            self._stopped = True
            self._schedule_generation += 1
            if self._scheduler is not None:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None
            self._next_run_at = None
        logger.info("思齐自动收垃圾插件停止，已取消本地到期任务")

    def __schedule_next(self, not_before: float = 0):
        with self._schedule_lock:
            if not self._enabled or self._stopped or self._schedule_mode != "auto" or self._auth_blocked:
                return
            now = time.time()
            keys = ["beach_due_at"] + (["brick_due_at"] if self._auto_brick else [])
            dates = [self._stats.get(key) for key in keys]
            due = min(value if self.__valid_due(value) else now + 15 for value in dates)
            if self._scheduler is None:
                self._scheduler = BackgroundScheduler()
                self._scheduler.start()
            self._next_run_at = max(now + 15, not_before, due)
            self._scheduler.add_job(
                self.__run_due_job, trigger="date", id="siqi_due", replace_existing=True,
                run_date=datetime.fromtimestamp(self._next_run_at, timezone.utc),
                args=[self._schedule_generation], misfire_grace_time=None, max_instances=1,
            )

    def __run_due_job(self, generation: int):
        result = self.run_clean_task(scheduled=True, generation=generation)
        if result["status"] in {"running", "waiting"}:
            self.__schedule_next(not_before=time.time() + 30)

    def __retry_due(self, action: str) -> float:
        key = f"{action}_retry_count"
        count = min(self.__safe_int(self._stats.get(key), 0, min_value=0) + 1, 4)
        self._stats[key] = count
        return time.time() + (300, 900, 1800, 3600)[count - 1]

    def __inventory_items(self, sorted_items: list) -> List[Dict[str, Any]]:
        """生成物品卡片网格 - 优化文字颜色对比度"""
        items = []
        for name, data in sorted_items:
            icon = self.ITEM_ICONS.get(name, "📦")
            color = self.ITEM_COLORS.get(name, "#3498db")
            count = data.get("count", 0)
            
            # 根据颜色亮度决定文字颜色
            # 对于亮色背景使用深色文字，暗色背景使用亮色文字
            dark_colors = ["#2c3e50", "#7f8c8d", "#8e44ad", "#d4a574"]
            text_color = "#ffffff" if color in dark_colors else "#2c3e50"
            
            items.append({
                "component": "div",
                "props": {
                    "style": f"""
                        background: linear-gradient(145deg, {color}25, {color}08);
                        border-radius: 16px;
                        padding: 20px 16px;
                        text-align: center;
                        border: 1px solid {color}30;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                        transition: transform 0.2s, box-shadow 0.2s;
                    """
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"style": f"font-size: 40px; margin-bottom: 6px; display: block;"},
                        "text": icon
                    },
                    {
                        "component": "div",
                        "props": {"style": f"font-size: 14px; font-weight: 600; color: {text_color}; margin-bottom: 4px; letter-spacing: 0.3px;"},
                        "text": name
                    },
                    {
                        "component": "div",
                        "props": {"style": f"font-size: 24px; font-weight: bold; color: {color}; text-shadow: 0 1px 4px rgba(0,0,0,0.1);"},
                        "text": f"{count:,}"
                    },
                    {
                        "component": "div",
                        "props": {
                            "style": f"width: 100%; height: 4px; background: {color}20; border-radius: 4px; margin-top: 10px; overflow: hidden;"
                        },
                        "content": [
                            {
                                "component": "div",
                                "props": {
                                    "style": f"width: {min(100, count / 10)}%; height: 100%; background: linear-gradient(90deg, {color}, {color}80); border-radius: 4px;"
                                }
                            }
                        ]
                    }
                ]
            })
        return items

    @staticmethod
    def __stat_card(icon: str, label: str, value: str, suffix: str, color: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [
                {
                    "component": "VCard",
                    "props": {
                        "color": color,
                        "variant": "tonal",
                        "class": "pa-3"
                    },
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "d-flex align-center"},
                            "content": [
                                {
                                    "component": "div",
                                    "props": {"class": "text-h4 mr-2"},
                                    "text": icon
                                },
                                {
                                    "component": "div",
                                    "content": [
                                        {
                                            "component": "div",
                                            "props": {"class": "text-caption text-medium-emphasis"},
                                            "text": label
                                        },
                                        {
                                            "component": "div",
                                            "props": {"class": "text-h6 font-weight-bold"},
                                            "text": f"{value}{suffix}"
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    @staticmethod
    def __info_col(label: str, value: Any) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis"},
                    "text": label
                },
                {
                    "component": "div",
                    "props": {"class": "text-h6"},
                    "text": str(value or "-")
                }
            ]
        }

    def __history_rows(self, history: list) -> List[Dict[str, Any]]:
        rows = []
        for record in reversed(history):
            time_str = record.get("time", "")
            if isinstance(time_str, (int, float)):
                try:
                    time_str = datetime.fromtimestamp(time_str).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    time_str = str(time_str)
            
            status_color = "success" if record.get("status") == "completed" else "warning"
            status_text = {"completed": "✅ 全部完成", "partial": "⚠️ 部分完成", "auth_failed": "🔐 认证失败", "cancelled": "⏹ 已停止"}.get(record.get("status"), "⚠️ 失败")
            result_text = record.get("result", "-")
            total_count = record.get("total_count", 0)
            
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": time_str},
                    {"component": "td", "text": result_text},
                    {"component": "td", "text": f"{total_count:,}" if total_count > 0 else "-"},
                    {
                        "component": "td",
                        "content": [
                            {
                                "component": "VChip",
                                "props": {
                                    "color": status_color,
                                    "size": "small",
                                    "variant": "tonal"
                                },
                                "text": status_text
                            }
                        ]
                    }
                ]
            })
        return rows

    def run_once_api(self) -> Dict[str, Any]:
        try:
            if not self._queue_manual_run():
                return {"success": False, "message": "已有收垃圾任务正在执行"}
        except Exception as exc:
            logger.error(f"启动收垃圾任务失败：{exc.__class__.__name__}")
            return {"success": False, "message": "无法启动后台任务，请检查日志"}
        return {"success": True, "message": "任务已启动，完成后可查看详情或等待通知"}
    def get_stats_api(self) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {
                "stats": self._stats,
                "inventory": self._inventory
            }
        }

    @eventmanager.register(EventType.PluginAction)
    def run_once_command(self, event: Event = None):
        event_data = event.event_data if event else {}
        if not isinstance(event_data, dict) or event_data.get("action") != "siqi_clean_beach":
            return
        channel = event_data.get("channel")
        userid = event_data.get("user")
        try:
            launched = self._queue_manual_run()
        except Exception:
            logger.exception("启动思齐收垃圾命令失败")
            launched = False
        self.post_message(
            channel=channel,
            userid=userid,
            mtype=NotificationType.Plugin,
            title="【思齐自动收垃圾插件】",
            text="任务已启动，完成后会发送通知。" if launched else "已有收垃圾任务正在执行或无法启动。"
        )
    @staticmethod
    def __valid_due(value) -> bool:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and 0 < value < 253402300800 and math.isfinite(value))

    def __due_text(self, key: str, compact: bool = False) -> str:
        if self._schedule_mode == "auto" and self._auth_blocked:
            return "等待更新 Cookie"
        due = self._stats.get(key)
        if not self.__valid_due(due):
            return "等待首次同步" if due is None else "时间异常，等待重新同步"
        if self._schedule_mode == "auto" and self.__valid_due(self._next_run_at):
            due = max(due, self._next_run_at)
        try:
            if compact:
                return f"{datetime.fromtimestamp(due):%Y-%m-%d %H:%M}"
            remaining = max(0, int(due - time.time()))
            return f"{datetime.fromtimestamp(due):%Y-%m-%d %H:%M:%S}（约{remaining // 3600}:{remaining // 60 % 60:02d}:{remaining % 60:02d}）"
        except (ValueError, OverflowError, OSError):
            return "时间异常，等待重新同步"

    def run_clean_task(self, reserved: bool = False, scheduled: bool = False,
                       generation: Optional[int] = None) -> Dict[str, Any]:
        with self._schedule_lock:
            if scheduled and (not self._enabled or self._stopped or self._auth_blocked
                              or (generation is not None and generation != self._schedule_generation)):
                return {"status": "disabled", "message": "定时任务已取消或暂停"}
            if not reserved and not self._lock.acquire(blocking=False):
                return {"status": "running", "message": "已有任务正在执行"}
            if not reserved:
                self._stop_event.clear()
            run_generation = self._schedule_generation
        auto = scheduled and self._schedule_mode == "auto"
        now = time.time()
        beach_at, brick_at = self._stats.get("beach_due_at"), self._stats.get("brick_due_at")
        clean_due = not auto or not self.__valid_due(beach_at) or now >= beach_at
        brick_due = self._auto_brick and (not auto or not self.__valid_due(brick_at) or now >= brick_at)
        if auto and not clean_due and not brick_due:
            self._lock.release()
            return {"status": "waiting", "message": "等待站点冷却到期"}
        clean = {"success": True, "message": "沙滩冷却中，正常等待", "skipped": True, "trash": 0}
        brick = {"success": True, "message": "未到每日搬砖时间，正常等待" if self._auto_brick else "未开启",
                 "skipped": True, "bricks_moved": 0}
        refreshed = False
        clean_ran = brick_ran = False
        beach_started_at = None
        preflight_failed = False
        prefetched = False
        self._stats["inventory_refreshed"] = False
        self._stats["beach_cooldown_refreshed"] = False
        self._inventory_auth_failed = False
        try:
            cookie = (self._cookie or self.__get_site_cookie() or "").strip()
            if not cookie or "c_secure_pass=" not in cookie:
                clean = {"success": False, "auth_failed": True, "message": "缺少有效 Cookie"}
            else:
                # 每轮共用连接池，避免50次搬砖反复建立TLS连接。
                self._session = requests.Session()
                if auto and clean_due and (not self.__valid_due(beach_at) or self._stats.get("beach_needs_sync")):
                    prefetched = True
                    inventory = self.__fetch_inventory(cookie)
                    if inventory is not None:
                        self._inventory = inventory
                        self._stats["last_update"] = time.time()
                        refreshed = True
                    if self._stats.get("beach_cooldown_refreshed"):
                        clean_due = time.time() >= self._stats["beach_due_at"]
                    else:
                        preflight_failed = True
                        clean_due = False
                        clean = {"success": False, "auth_failed": self._inventory_auth_failed,
                                 "message": "Cookie失效，请重新登录" if self._inventory_auth_failed else "沙滩冷却同步失败，未发送清理请求"}
                if clean_due:
                    clean_ran = True
                    refreshed = False
                    clean = self.__enter_beach(cookie)
                    if clean.get("success"):
                        # 网页在进入沙滩成功时开始两小时冷却，收集失败也不能立即重进。
                        beach_started_at = clean["_received_at"]
                        clean = self.__collect_trash(cookie)
                    elif "冷却" in clean.get("message", "") and not clean.get("auth_failed"):
                        clean.update(success=True, skipped=True)
                if clean.get("auth_failed"):
                    brick["message"] = "认证失败，停止后续请求"
                    brick["success"] = False
                    brick["auth_failed"] = True
                else:
                    if brick_due:
                        brick_ran = True
                        brick = self.__move_bricks(cookie)
                        if not brick.get("skipped"):
                            refreshed = False
                    if (not brick.get("auth_failed") and not self._stop_event.is_set()
                            and (not prefetched or clean_ran or (brick_ran and not brick.get("skipped")))):
                        inventory = self.__fetch_inventory(cookie)
                        if inventory is not None:
                            self._inventory = inventory
                            self._stats["last_update"] = time.time()
                            refreshed = True
            if self._inventory_auth_failed:
                clean.update(success=False, auth_failed=True, message="Cookie失效，请重新登录")
            if clean.get("auth_failed"):
                brick.update(success=False, auth_failed=True, message="认证失败，停止后续请求")
            status = "auth_failed" if clean.get("auth_failed") or brick.get("auth_failed") else (
                "cancelled" if clean.get("cancelled") or brick.get("cancelled") else (
                    "completed" if clean.get("success") and brick.get("success") else "partial"
                )
            )
        except Exception as exc:
            logger.error(f"思齐任务异常：{exc.__class__.__name__}")
            status = "error"
            clean["message"] = "任务异常，请检查日志"
        finally:
            try:
                total = sum(item.get("count", 0) for item in self._inventory.values())
                stock = self._inventory.get("砖块", {}).get("count")
                clean_text = clean.get("message", "未执行")
                if clean.get("success") and not clean.get("skipped"):
                    clean_text = f"收集{clean['trash']}个垃圾" if clean.get("trash") is not None else "收集成功（数量未知）"
                brick_text = brick.get("message", "未知")
                daily = brick.get("daily_bricks") if brick_ran else self._stats.get("daily_bricks")
                moved = brick.get("bricks_moved", 0)
                message = (f"清理：{clean_text}；搬砖：{brick_text}；本次{moved}块，"
                           f"今日{daily if daily is not None else '未知'}/50，库存{stock if stock is not None else '未知'}"
                           f"（{'本次已刷新' if refreshed else '缓存，非本次刷新'}）")
                record = not (auto and status == "completed" and clean.get("skipped") and brick.get("skipped"))
                if record:
                    self._stats.update(clean_result=clean_text, brick_result=brick_text,
                                       bricks_moved=moved, last_result=message, last_run=time.time())
                self._stats.update(inventory_refreshed=refreshed, total_items_count=total)
                if brick_ran:
                    self._stats["daily_bricks"] = daily
                if not record:
                    status = "waiting"
                result = self.__new_result(status=status, message=message)
                result["data"] = {"clean": clean, "brick": brick, "trash": clean.get("trash", 0),
                                  "total_count": total, "brick_inventory": stock, "inventory_refreshed": refreshed}
                if record:
                    history = self._stats.get("history", [])
                    history.append({"time": result["timestamp"], "result": message, "status": status,
                                    "total_count": total, **result["data"]})
                    self._stats["history"] = history[-20:]
                if self._stats.get("beach_cooldown_refreshed"):
                    self._stats["beach_retry_count"] = 0
                elif beach_started_at is not None:
                    self._stats["beach_due_at"] = beach_started_at + 7200 + 15
                    self._stats["beach_due_source"] = "进入沙滩成功时间＋两小时"
                    self._stats["beach_retry_count"] = 0
                    self._stats["beach_needs_sync"] = False
                elif clean_due or preflight_failed or clean.get("auth_failed"):
                    self._stats["beach_due_at"] = self.__retry_due("beach")
                    self._stats["beach_due_source"] = "同步或执行失败，等待重查"
                    self._stats["beach_needs_sync"] = True
                if brick_due:
                    if ((brick.get("daily_bricks") == 50 or self._stats.get("brick_uncertain_reset") is not None)
                            and self.__valid_brick_state({**brick, "bricks_moved": 0})
                            and self.__valid_due(brick.get("_received_at"))):
                        self._stats["brick_due_at"] = brick["_received_at"] + brick["next_brick_reset_ts"] - brick["server_now"] + 15
                        self._stats["brick_retry_count"] = 0
                    else:
                        self._stats["brick_due_at"] = self.__retry_due("brick")
                if status == "auth_failed" and run_generation == self._schedule_generation:
                    self._auth_blocked = True
                elif status == "completed" and run_generation == self._schedule_generation:
                    self._auth_blocked = False
                self.__finish_task(result, notify=record)
            finally:
                try:
                    if self._session is not None:
                        self._session.close()
                finally:
                    self._session = None
                    self._lock.release()
                    self.__schedule_next()
        return result

    def __request_action(self, cookie: str, action: str) -> Dict[str, Any]:
        """只接受 JSON；不跟随写请求重定向，也不重试写请求。"""
        if self._stop_event.is_set():
            return {"success": False, "cancelled": True, "message": "插件停止或配置已重载，停止后续请求"}
        started = time.monotonic()
        logger.info(f"思齐请求开始：action={action}")
        try:
            cookies = self.__cookie_to_dict(cookie)
            http = self._session if self._session is not None else requests
            response = http.post(
                self.MOWAN_URL,
                headers={"content-type": "application/x-www-form-urlencoded",
                         "user-agent": self._user_agent, "accept": "application/json",
                         "origin": self.BASE_URL, "referer": self.MOWAN_URL},
                cookies=cookies, data={"action": action},
                timeout=(10, 30),
                verify=True, allow_redirects=False,
            )
            logger.info(f"思齐请求结束：action={action}, HTTP {response.status_code}, 耗时{time.monotonic() - started:.2f}秒")
            if response.status_code in {401, 403} or "login" in response.headers.get("Location", "").lower():
                return {"success": False, "auth_failed": True, "message": "Cookie失效或访问被拒绝"}
            if response.status_code != 200:
                return {"success": False, "message": f"HTTP {response.status_code}"}
            try:
                data = response.json()
            except ValueError:
                soup = BeautifulSoup(response.text, "html.parser")
                auth = bool(soup.select_one("form[action*='login'], input[type='password']"))
                return {"success": False, "auth_failed": auth,
                        "message": "Cookie失效，请重新登录" if auth else "返回非JSON响应"}
            if isinstance(data, dict) and "success" not in data and action in {"enter_beach", "collect_all_trash"}:
                # 保留原沙滩接口的 JSON status 合约，搬砖仍要求布尔 success。
                if data.get("status") == "success":
                    data["success"] = True
            if not isinstance(data, dict) or not isinstance(data.get("success"), bool):
                return {"success": False, "message": "响应缺少布尔 success 字段"}
            message = str(data.get("message", ""))[:500]
            for secret in [cookie, *cookies.values()]:
                if secret:
                    message = message.replace(secret, "[已隐藏]")
            data["message"] = message
            data["_received_at"] = time.time()
            if not data["success"]:
                data["auth_failed"] = bool(re.search(r"登录|cookie.*(?:失效|过期|无效|invalid|expired)|login|unauth|not logged in", message, re.I))
                data["message"] = message or "服务端业务失败"
            return data
        except requests.Timeout as exc:
            logger.warning(f"思齐请求超时：action={action}, 类型={exc.__class__.__name__}, 耗时{time.monotonic() - started:.2f}秒")
            return {"success": False, "timeout": True, "message": "请求超时，操作结果待核对"}
        except (requests.RequestException, ValueError) as exc:
            # 网络异常文本可能带敏感请求信息，只保存异常类型。
            return {"success": False, "message": f"请求失败：{exc.__class__.__name__}"}

    def __sync_game_state(self, cookie: str) -> Dict[str, Any]:
        # 状态查询可安全重试一次；任何游戏写入请求均不重试。
        for attempt in range(2):
            result = self.__request_action(cookie, "sync_game_state")
            if not result.get("timeout"):
                return result
            if attempt == 0:
                logger.warning("思齐状态同步超时，2秒后仅重试一次状态查询")
                time.sleep(2)
        return {**result, "message": "状态同步连续两次超时"}

    def __enter_beach(self, cookie: str) -> Dict[str, Any]:
        return self.__request_action(cookie, "enter_beach")

    def __collect_trash(self, cookie: str) -> Dict[str, Any]:
        result = self.__request_action(cookie, "collect_all_trash")
        if result.get("success"):
            data = result.get("data")
            data = data if isinstance(data, dict) else {}
            items = result.get("collected_items", data.get("collected_items"))
            count = data.get("collected", result.get("collected"))
            if isinstance(items, dict) and all(
                    isinstance(name, str) and name and not isinstance(value, bool)
                    and (isinstance(value, int) and value >= 0
                         or isinstance(value, str) and re.fullmatch(r"[0-9]+", value))
                    for name, value in items.items()):
                count = sum(int(value) for value in items.values())
            if count is None:
                found = re.search(r'收集了?\s*(\d+)\s*个?垃圾', result.get("message", ""))
                count = int(found.group(1)) if found else None
            if isinstance(count, str) and re.fullmatch(r"[0-9]+", count):
                count = int(count)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                count = None  # JSON业务成功与数量是否已知分别记录，不用库存变化猜测本次数量。
            result["trash"] = count
        return result

    @staticmethod
    def __valid_brick_state(data: Dict[str, Any], sync: bool = False) -> bool:
        fields = ["daily_bricks", "server_now", "next_brick_reset_ts"]
        fields += ["last_brick_time"] if sync else ["bricks_moved"]
        if any(isinstance(data.get(k), bool) or not isinstance(data.get(k), int) or data[k] < 0 for k in fields):
            return False
        reset = data.get("last_daily_reset")
        return (isinstance(reset, (str, int)) and not isinstance(reset, bool) and reset != ""
                and 0 <= data["daily_bricks"] <= 50
                and data["server_now"] > 0
                and 0 < data["next_brick_reset_ts"] - data["server_now"] <= 172800)

    def __move_bricks(self, cookie: str) -> Dict[str, Any]:
        result = {"success": False, "message": "状态同步失败", "bricks_moved": 0}
        state = self.__sync_game_state(cookie)
        if not state.get("success"):
            if state.get("timeout"):
                state["message"] = "搬砖前状态同步超时，未发送搬砖请求"
            return {**result, **state, "bricks_moved": 0}
        if not self.__valid_brick_state(state, sync=True):
            return {**result, "message": "状态同步字段缺失或异常"}
        result.update(daily_bricks=state["daily_bricks"], last_daily_reset=state["last_daily_reset"],
                      server_now=state["server_now"], next_brick_reset_ts=state["next_brick_reset_ts"],
                      _received_at=state["_received_at"])
        if state["daily_bricks"] >= 50:
            return {**result, "success": True, "skipped": True, "message": "已达每日上限，正常跳过"}
        uncertain = self._stats.get("brick_uncertain_reset")
        if uncertain is not None and uncertain == state["last_daily_reset"]:
            return {**result, "message": "上次写入结果不确定，等待服务端每日重置后再执行"}
        self._stats.pop("brick_uncertain_reset", None)
        # 最多50次，串行间隔2秒；每次必须有服务端数量进展。
        for attempt in range(50):
            if attempt:
                time.sleep(2)
            response = self.__request_action(cookie, "move_brick")
            if response.get("timeout"):
                synced = self.__sync_game_state(cookie)
                if synced.get("success") and self.__valid_brick_state(synced, sync=True):
                    if synced["last_daily_reset"] == state["last_daily_reset"] and synced["daily_bricks"] > state["daily_bricks"]:
                        result["bricks_moved"] += synced["daily_bricks"] - state["daily_bricks"]
                        result["recovered_from_sync"] = True
                        self._stats["brick_last_run_server"] = synced["server_now"]
                    result.update({k: synced[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts", "_received_at")})
                self._stats["brick_uncertain_reset"] = result["last_daily_reset"]
                return {**result, "auth_failed": synced.get("auth_failed", False),
                        "message": ("搬砖超时，状态已同步并停止" if synced.get("success") and self.__valid_brick_state(synced, sync=True)
                                    else "搬砖超时，后续状态同步失败，结果仍不确定") + "；本轮不重试，待服务端每日重置"}
            if response.get("cancelled"):
                return {**result, "cancelled": True, "message": response["message"]}
            if not response.get("success"):
                # 失败也可能携带当天计数，但不把它算成本次成功增量。
                if self.__valid_brick_state({**response, "bricks_moved": 0}):
                    result.update({k: response[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts", "_received_at")})
                    if response["daily_bricks"] == 50 and not response.get("auth_failed"):
                        return {**result, "success": True, "message": "已达每日上限，正常跳过"}
                self._stats["brick_uncertain_reset"] = result["last_daily_reset"]
                return {**result, "auth_failed": response.get("auth_failed", False), "message": response["message"]}
            if not self.__valid_brick_state(response):
                self._stats["brick_uncertain_reset"] = state["last_daily_reset"]
                return {**result, "message": "搬砖响应字段缺失或异常，停止"}
            moved = response["bricks_moved"]
            result.update({k: response[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts", "_received_at")})
            if (response["last_daily_reset"] != state["last_daily_reset"] or moved <= 0
                    or response["daily_bricks"] - state["daily_bricks"] != moved
                    or response["server_now"] < state["server_now"]):
                self._stats["brick_uncertain_reset"] = response["last_daily_reset"]
                return {**result, "message": "状态无进展、增量不一致或跨日重置，停止"}
            result["bricks_moved"] += moved
            logger.info(f"搬砖已确认：本次增量{moved}块，累计{result['bricks_moved']}块，今日{response['daily_bricks']}/50")
            self._stats["brick_last_run_server"] = response["server_now"]
            state = response
            if state["daily_bricks"] >= 50:
                return {**result, "success": True, "message": "搬砖完成，已达每日上限"}
        return {**result, "message": "已达最大请求次数，停止"}

    def __fetch_inventory(self, cookie: str) -> Optional[Dict[str, Any]]:
        """从库存 DOM 解析数据，避免正则匹配嵌套 div 时截断内容。"""
        try:
            http = self._session if self._session is not None else requests
            response = http.get(
                self.MOWAN_URL,
                headers={
                    "accept": "text/html,application/xhtml+xml",
                    "user-agent": self._user_agent,
                },
                cookies=self.__cookie_to_dict(cookie),
                timeout=(10, 30),
                verify=True,
                allow_redirects=False,
            )
            if response.status_code != 200:
                if response.status_code in {401, 403} or "login" in response.headers.get("Location", "").lower():
                    self._inventory_auth_failed = True
                logger.warning(f"思齐库存请求 HTTP {response.status_code}")
                return None
            soup = BeautifulSoup(response.text, "html.parser")
            if soup.select_one("form[action*='login'], input[type='password']"):
                self._inventory_auth_failed = True
                logger.warning("库存页面疑似跳转至登录页面，请更新 Cookie")
                return None
            self.__read_beach_cooldown(soup)
            inventory: Dict[str, Any] = {}
            for item in soup.select(".inventory-item"):
                name_node = item.select_one(".item-name")
                count_node = item.select_one(".item-count")
                if name_node is None or count_node is None:
                    logger.warning("库存条目字段缺失，保留本地缓存")
                    return None
                name = name_node.get_text(" ", strip=True)
                raw_count = count_node.get_text(" ", strip=True)
                matched = re.fullmatch(r"(\d+|\d{1,3}(?:,\d{3})+)\s*(?:个|块)?", raw_count)
                if not name or name in inventory or not matched:
                    logger.warning("库存条目名称或数量异常，保留本地缓存")
                    return None
                count = int(matched.group(1).replace(",", ""))
                icon_node = item.select_one(".item-icon")
                inventory[name] = {
                    "name": name,
                    "count": count,
                    "icon": icon_node.get_text(" ", strip=True) if icon_node else self.ITEM_ICONS.get(name, "📦"),
                }
            # 页面结构变化时返回 None，避免用空数据覆盖用户历史库存。
            if not inventory and not soup.select_one(".inventory-grid"):
                logger.warning("未找到思齐库存容器，保留本地缓存并等待更新")
                return None
            logger.info(f"已解析思齐库存：{len(inventory)} 种物品")
            return inventory
        except requests.RequestException as exc:
            logger.warning(f"思齐库存请求失败：{exc.__class__.__name__}")
            return None
        except Exception as exc:
            logger.error(f"思齐库存解析失败：{exc.__class__.__name__}")
            return None

    def __read_beach_cooldown(self, soup):
        """只解析初始化数字，不执行站点 JavaScript，不采信变化中的倒计时文本。"""
        for script in soup.find_all("script"):
            bootstrap = re.search(r"\b(?:let|const|var)\s+gameData\s*=\s*\{(.*?)\};", script.get_text(), re.S)
            if not bootstrap:
                continue
            source = bootstrap.group(1)
            server_time = re.search(r"\bserverTimeOffset\s*:\s*(\d+)\s*-\s*Math\.floor\(Date\.now\(\)\s*/\s*1000\)\s*(?=,|\Z)", source)
            if not server_time:
                continue
            values = {"serverTimeOffset": int(server_time.group(1))}
            for key in ("lastBeachTime", "beachInterval"):
                found = re.search(r"\b" + key + r"\s*:\s*(\d+)\s*(?=,|\Z)", source)
                if found:
                    values[key] = int(found.group(1))
            if len(values) != 3:
                continue
            last, interval, server = values["lastBeachTime"], values["beachInterval"], values["serverTimeOffset"]
            if not (server > 0 and 0 <= last <= server and 0 < interval <= 86400):
                continue
            self._stats["beach_due_at"] = time.time() + max(0, last + interval - server) + 15
            self._stats["beach_cooldown_refreshed"] = True
            self._stats["beach_needs_sync"] = False
            self._stats["beach_due_source"] = "站点初始化时间（服务端校时）"
            return

    def __get_site_cookie(self):
        site_cookie = ""
        try:
            site_oper = SiteOper()
            site = site_oper.get_by_domain(self.SITE_DOMAIN)
            ua = getattr(site, "ua", None) if site else None
            self._user_agent = ua.strip() if isinstance(ua, str) and ua.strip() else self.USER_AGENT
            if site and site.cookie:
                site_cookie = site.cookie
        except Exception as e:
            logger.error(f"获取站点 Cookie 异常：{e.__class__.__name__}")
        return site_cookie

    @staticmethod
    def __cookie_to_dict(cookie: str) -> Dict[str, str]:
        if "\r" in (cookie or "") or "\n" in (cookie or ""):
            raise ValueError("Cookie 包含非法换行符")
        cookies = {}
        for item in (cookie or "").split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            if key:
                cookies[key] = value.strip()
        return cookies

    @staticmethod
    def __safe_int(value: Any, default: int, min_value: int = None) -> int:
        try:
            result = int(value) if value is not None else default
        except (ValueError, TypeError, OverflowError):
            result = default
        if min_value is not None:
            result = max(result, min_value)
        return result

    @staticmethod
    def __new_result(status: str = "running", message: str = "") -> Dict[str, Any]:
        return {
            "status": status,
            "message": message,
            "timestamp": time.time()
        }

    def __finish_task(self, result: Dict[str, Any], notify: bool = True):
        """无论成功、失败或鉴权失效，都更新可见的最后结果。"""
        self._update_stats()
        if self._notify and notify:
            try:
                self.__send_notification(result)
            except Exception:
                logger.exception("发送思齐收垃圾通知失败")
    def _update_stats(self):
        try:
            self.update_config({
                "enabled": self._enabled,
                "auto_brick": self._auto_brick,
                "cookie": self._cookie,
                "schedule_mode": self._schedule_mode,
                "cron": self._cron,
                "interval_minutes": self._interval_minutes,
                "notify": self._notify,
                "run_once": False,
                "stats": self._stats,
                "inventory": self._inventory
            })
        except Exception as e:
            logger.error(f"更新统计数据失败：{e.__class__.__name__}")

    def __send_notification(self, result: Dict[str, Any]):
        title = "🏖️【思齐自动收垃圾插件】"
        status_map = {
            "completed": "✅ 全部完成",
            "partial": "⚠️ 部分成功",
            "cancelled": "⏹ 已停止",
            "failed": "❌ 失败",
            "auth_failed": "🔐 认证失败",
            "error": "💥 异常"
        }
        status_text = status_map.get(result.get("status"), result.get("status", "未知"))
        text = f"状态：{status_text}\n消息：{result.get('message')}"

        if result.get("data"):
            data = result["data"]
            if data.get("trash"):
                text += f"\n\n🗑️ 收集垃圾：{data['trash']} 个"
            if data.get("total_count"):
                text += f"\n📦 当前物品总数：{data['total_count']:,} 个"

        total_count = sum(item.get("count", 0) for item in self._inventory.values())
        text += f"\n\n📊 物品种类：{len(self._inventory)} 种"
        text += f"\n📦 物品总数：{total_count:,} 个"
        if self._schedule_mode == "auto":
            text += f"\n🏖️ 沙滩下次执行时间：{self.__due_text('beach_due_at', compact=True)}"
            if self._auto_brick:
                text += f"\n🧱 搬砖下次执行时间：{self.__due_text('brick_due_at', compact=True)}"

        self.post_message(
            mtype=NotificationType.Plugin,
            title=title,
            text=text
        )

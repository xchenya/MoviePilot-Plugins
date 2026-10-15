"""思齐自动收垃圾（MoviePilot V3 移植版）。

原作者 bfjy，源码来自 bfjy2024/MoviePilot-Plugins，按原仓库 GPL-3.0
许可改造。V3 适配由 xchenya 维护；搬砖已获用户宿主日志验证，新调度未经真实联调。
"""
import json
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


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
    plugin_version = "2.2.0"
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
        self._session = None
        self._enabled = False
        self._cookie = ""
        self._user_agent = self.USER_AGENT
        self._schedule_mode = "interval"
        self._cron = "1 */2 * * *"
        self._interval_minutes = 121
        self._auto_brick = False
        self._brick_cooldown_minutes = 1440
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
            threading.Thread(target=self.run_clean_task, kwargs={"reserved": True}, daemon=True).start()
        except Exception:
            self._lock.release()
            raise
        return True

    def init_plugin(self, config: dict = None):
        config = config or {}
        site_cookie = self.__get_site_cookie()

        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._schedule_mode = config.get("schedule_mode", "interval" if config else "auto")
        if self._schedule_mode not in {"auto", "cron", "interval"}:
            self._schedule_mode = "interval"
        self._cron = (config.get("cron") or "1 */2 * * *").strip()
        self._interval_minutes = self.__safe_int(config.get("interval_minutes"), 121, min_value=1)
        self._auto_brick = bool(config.get("auto_brick", False))
        self._brick_cooldown_minutes = self.__safe_int(config.get("brick_cooldown_minutes"), 1440, min_value=1)
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))

        stats = config.get("stats", {})
        if stats:
            self._stats.update(stats)
        
        inventory = config.get("inventory", {})
        if inventory:
            self._inventory = inventory

        logger.info(
            f"思齐自动收垃圾插件初始化完成：enabled={self._enabled}, "
            f"schedule_mode={self._schedule_mode}, interval_minutes={self._interval_minutes}"
        )

        if self._run_once:
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "auto_brick": self._auto_brick,
                "brick_cooldown_minutes": self._brick_cooldown_minutes,
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
            return [{"id": "SiQiCleanBeach", "name": "思齐站点冷却调度",
                     "trigger": IntervalTrigger(minutes=1), "func": self.run_clean_task,
                     "kwargs": {"scheduled": True}}]

        if self._schedule_mode == "interval":
            try:
                trigger = IntervalTrigger(minutes=self._interval_minutes)
                logger.info(f"使用间隔触发器：每{self._interval_minutes}分钟执行一次")
                return [{
                    "id": "SiQiCleanBeach",
                    "name": "思齐自动收垃圾",
                    "trigger": trigger,
                    "func": self.run_clean_task,
                    "kwargs": {}
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
                    "kwargs": {}
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
                                            "hint": "站点冷却与固定时间二选一；旧间隔仅作兼容。自动模式每分钟在本地检查，到期才请求站点。"
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
                                            "label": "间隔分钟数",
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
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {"model": "brick_cooldown_minutes", "label": "旧版搬砖冷却（分钟）", "type": "number", "min": 1, "hint": "仅旧版固定间隔模式使用。站点冷却/固定时间模式以服务端每日50块及重置时间为准。"}}
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
            "brick_cooldown_minutes": self._brick_cooldown_minutes,
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
            schedule_info = "按站点冷却（每分钟本地检查）"
        elif self._schedule_mode == "interval":
            schedule_info = f"每{self._interval_minutes}分钟"
        else:
            schedule_info = f"Cron: {self._cron}"

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
                                    self.__info_col("🏖️ 沙滩下次可执行", self.__due_text("beach_due_at")),
                                    self.__info_col("🧱 搬砖下次可执行", self.__due_text("brick_due_at") if self._auto_brick else "未开启"),
                                    self.__info_col("⏳ 沙滩时间来源", stats.get("beach_due_source", "等待首次同步")),
                                    self.__info_col("📝 最后结果", stats.get("last_result", "-")),
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
        # 公共定时任务由 MoviePilot 宿主负责停止，进行中的请求有明确超时。
        logger.info("思齐自动收垃圾插件停止，定时任务将由宿主取消")

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
            status_text = {"completed": "✅ 完成", "partial": "⚠️ 部分完成", "auth_failed": "🔐 认证失败"}.get(record.get("status"), "⚠️ 失败")
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
    def __due_text(self, key: str) -> str:
        due = self._stats.get(key)
        if not isinstance(due, (int, float)):
            return "等待首次同步"
        remaining = max(0, int(due - time.time()))
        return f"{datetime.fromtimestamp(due):%Y-%m-%d %H:%M:%S}（约{remaining // 3600}:{remaining // 60 % 60:02d}:{remaining % 60:02d}）"

    def run_clean_task(self, reserved: bool = False, scheduled: bool = False) -> Dict[str, Any]:
        if not reserved and not self._lock.acquire(blocking=False):
            return {"status": "running", "message": "已有任务正在执行"}
        auto = scheduled and self._schedule_mode == "auto"
        now = time.time()
        beach_at, brick_at = self._stats.get("beach_due_at"), self._stats.get("brick_due_at")
        clean_due = not auto or not isinstance(beach_at, (int, float)) or now >= beach_at
        brick_due = self._auto_brick and (not auto or not isinstance(brick_at, (int, float)) or now >= brick_at)
        if auto and not clean_due and not brick_due:
            self._lock.release()
            return {"status": "waiting", "message": "等待站点冷却到期"}
        clean = {"success": False, "message": "未执行", "trash": 0}
        brick = {"success": True, "message": "未开启", "bricks_moved": 0}
        refreshed = False
        self._stats["inventory_refreshed"] = False
        self._stats["beach_cooldown_refreshed"] = False
        try:
            cookie = (self._cookie or self.__get_site_cookie() or "").strip()
            if not cookie or "c_secure_pass=" not in cookie:
                clean = {"success": False, "auth_failed": True, "message": "缺少有效 Cookie"}
            else:
                # 每轮共用连接池，避免50次搬砖反复建立TLS连接。
                self._session = requests.Session()
                if clean_due:
                    clean = self.__enter_beach(cookie)
                    if clean.get("success"):
                        clean = self.__collect_trash(cookie)
                else:
                    clean = {"success": True, "message": "沙滩冷却中，未发送清理请求", "skipped": True}
                if clean.get("auth_failed"):
                    brick["message"] = "认证失败，停止后续请求"
                    brick["success"] = False
                    brick["auth_failed"] = True
                else:
                    if brick_due:
                        brick = self.__move_bricks(cookie)
                    elif self._auto_brick:
                        brick["message"] = "未到下次搬砖检查时间，未发送搬砖请求"
                    if not brick.get("auth_failed"):
                        inventory = self.__fetch_inventory(cookie)
                        if inventory is not None:
                            self._inventory = inventory
                            self._stats["last_update"] = time.time()
                            refreshed = True
            if clean.get("auth_failed"):
                brick.update(success=False, auth_failed=True, message="认证失败，停止后续请求")
            status = "auth_failed" if clean.get("auth_failed") or brick.get("auth_failed") else (
                "completed" if (clean.get("success") or "冷却" in clean.get("message", "")) and brick.get("success") else "partial"
            )
        except Exception as exc:
            logger.error(f"思齐任务异常：{exc.__class__.__name__}")
            status = "error"
            clean["message"] = "任务异常，请检查日志"
        finally:
            try:
                total = sum(item.get("count", 0) for item in self._inventory.values())
                stock = self._inventory.get("砖块", {}).get("count")
                clean_text = f"收集{clean.get('trash', 0)}个垃圾" if clean.get("success") and not clean.get("skipped") else clean.get("message", "未执行")
                brick_text = brick.get("message", "未知")
                daily = brick.get("daily_bricks")
                moved = brick.get("bricks_moved", 0)
                message = (f"清理：{clean_text}；搬砖：{brick_text}；本次{moved}块，"
                           f"今日{daily if daily is not None else '未知'}/50，库存{stock if stock is not None else '未知'}"
                           f"（{'本次已刷新' if refreshed else '缓存，非本次刷新'}）")
                self._stats.update(clean_result=clean_text, brick_result=brick_text,
                                   bricks_moved=moved, daily_bricks=daily,
                                   inventory_refreshed=refreshed, total_items_count=total,
                                   last_result=message, last_run=time.time())
                result = self.__new_result(status=status, message=message)
                result["data"] = {"clean": clean, "brick": brick, "trash": clean.get("trash", 0),
                                  "total_count": total, "brick_inventory": stock, "inventory_refreshed": refreshed}
                history = self._stats.get("history", [])
                history.append({"time": result["timestamp"], "result": message, "status": status,
                                "total_count": total, **result["data"]})
                self._stats["history"] = history[-20:]
                if not self._stats.get("beach_cooldown_refreshed") and clean_due:
                    self._stats["beach_due_at"] = time.time() + self._interval_minutes * 60
                    self._stats["beach_due_source"] = "未读到站点冷却，回退配置间隔"
                if brick_due:
                    delay = 300
                    if (brick.get("daily_bricks") == 50 or self._stats.get("brick_uncertain_reset") is not None):
                        reset, server = brick.get("next_brick_reset_ts"), brick.get("server_now")
                        if isinstance(reset, int) and isinstance(server, int) and reset > server:
                            delay = reset - server + 5
                    self._stats["brick_due_at"] = time.time() + delay
                self.__finish_task(result)
            finally:
                try:
                    if self._session is not None:
                        self._session.close()
                finally:
                    self._session = None
                    self._lock.release()
        return result

    def __request_action(self, cookie: str, action: str) -> Dict[str, Any]:
        """只接受 JSON；不跟随写请求重定向，也不重试写请求。"""
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
            count = data.get("collected") if isinstance(data, dict) else result.get("collected")
            if count is None:
                found = re.search(r'收集了?\s*(\d+)\s*个?垃圾', result.get("message", ""))
                count = int(found.group(1)) if found else None
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                return {"success": False, "message": "收集响应缺少有效数量"}
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
                and data["next_brick_reset_ts"] > data["server_now"] > 0)

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
                      server_now=state["server_now"], next_brick_reset_ts=state["next_brick_reset_ts"])
        if state["daily_bricks"] >= 50:
            return {**result, "success": True, "message": "已达每日上限，正常跳过"}
        uncertain = self._stats.get("brick_uncertain_reset")
        if uncertain is not None and uncertain == state["last_daily_reset"]:
            return {**result, "message": "上次写入结果不确定，等待服务端每日重置后再执行"}
        self._stats.pop("brick_uncertain_reset", None)
        last_run = self._stats.get("brick_last_run_server", 0)
        if self._schedule_mode == "interval" and last_run and state["server_now"] - last_run < self._brick_cooldown_minutes * 60:
            return {**result, "success": True, "message": "搬砖冷却中，正常跳过"}
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
                    result.update({k: synced[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts")})
                self._stats["brick_uncertain_reset"] = result["last_daily_reset"]
                return {**result, "auth_failed": synced.get("auth_failed", False),
                        "message": ("搬砖超时，状态已同步并停止" if synced.get("success") and self.__valid_brick_state(synced, sync=True)
                                    else "搬砖超时，后续状态同步失败，结果仍不确定") + "；本轮不重试，待服务端每日重置"}
            if not response.get("success"):
                # 失败也可能携带当天计数，但不把它算成本次成功增量。
                if self.__valid_brick_state({**response, "bricks_moved": 0}):
                    result.update({k: response[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts")})
                    if response["daily_bricks"] == 50 and not response.get("auth_failed"):
                        return {**result, "success": True, "message": "已达每日上限，正常跳过"}
                self._stats["brick_uncertain_reset"] = result["last_daily_reset"]
                return {**result, "auth_failed": response.get("auth_failed", False), "message": response["message"]}
            if not self.__valid_brick_state(response):
                self._stats["brick_uncertain_reset"] = state["last_daily_reset"]
                return {**result, "message": "搬砖响应字段缺失或异常，停止"}
            moved = response["bricks_moved"]
            result.update({k: response[k] for k in ("daily_bricks", "server_now", "last_daily_reset", "next_brick_reset_ts")})
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
                logger.warning(f"思齐库存请求 HTTP {response.status_code}")
                return None
            soup = BeautifulSoup(response.text, "html.parser")
            if soup.select_one("form[action*='login'], input[type='password']"):
                logger.warning("库存页面疑似跳转至登录页面，请更新 Cookie")
                return None
            self.__read_beach_cooldown(soup)
            inventory: Dict[str, Any] = {}
            for item in soup.select(".inventory-item"):
                name_node = item.select_one(".item-name")
                count_node = item.select_one(".item-count")
                if name_node is None or count_node is None:
                    continue
                name = name_node.get_text(" ", strip=True)
                if not name:
                    continue
                raw_count = count_node.get_text(" ", strip=True).replace(",", "")
                matched = re.search(r"\d+", raw_count)
                count = int(matched.group()) if matched else 0
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
            server_time = re.search(r"\bserverTimeOffset\s*:\s*(\d+)\s*-\s*Math\.floor\(Date\.now\(\)\s*/\s*1000\)", source)
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
            self._stats["beach_due_at"] = time.time() + max(0, last + interval - server) + 5
            self._stats["beach_cooldown_refreshed"] = True
            self._stats["beach_due_source"] = "站点初始化时间（服务端校时，5秒余量）"
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
        except (ValueError, TypeError):
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

    def __finish_task(self, result: Dict[str, Any]):
        """无论成功、失败或鉴权失效，都更新可见的最后结果。"""
        self._update_stats()
        if self._notify:
            try:
                self.__send_notification(result)
            except Exception:
                logger.exception("发送思齐收垃圾通知失败")
    def _update_stats(self):
        try:
            self.update_config({
                "enabled": self._enabled,
                "auto_brick": self._auto_brick,
                "brick_cooldown_minutes": self._brick_cooldown_minutes,
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
            "completed": "✅ 成功",
            "partial": "⚠️ 部分成功",
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
            text += f"\n🏖️ 沙滩下次检查：{self.__due_text('beach_due_at')}"
            if self._auto_brick:
                text += f"\n🧱 搬砖下次检查：{self.__due_text('brick_due_at')}"

        self.post_message(
            mtype=NotificationType.Plugin,
            title=title,
            text=text
        )

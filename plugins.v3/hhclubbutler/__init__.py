# -*- coding: utf-8 -*-
"""
HHCLUB 憨憨保种区管家插件（MoviePilot V3）
v1.4：
1. 移除全部积分/憨豆预估与公式，只保留目标体积模式
2. 优选逻辑：高倍率档优先（0-1人 > 2-3人 > 4-5人）
3. 面板"达标可得"改为"上次憨豆/上次积分"（rescuesettleinfo 实结值）
4. 新增仿QB风格保种管理页：列出在保种子，支持手动删除（同步删下载器任务+文件）
"""

import json
import os
import re
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup

from app.sdk.config import settings
from app.sdk._legacy.site import SiteOper
from app.sdk.services import DownloaderHelper
from app.sdk.logging import logger
from app.plugins import _PluginBase
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.types import EventType
from app.sdk.events import eventmanager, Event
from app.schemas.types import NotificationType
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.adapters.web.security.access import verify_resource_token, verify_token
from .matching import (associate_rescue_seeds, normalize_name, translated_release_key,
                       translated_size_matches, is_trusted_hh_tracker, release_name)

import requests

def _require_bear_admin(identity=Depends(verify_token)) -> None:
    if not getattr(identity, "super_user", False):
        raise HTTPException(status_code=403, detail="管理员权限不足")

def _require_resource_admin(request: Request, identity=Depends(verify_resource_token)) -> None:
    """V3 resource Cookie used by independently opened HTML pages.

    MoviePilot issues this short-lived HttpOnly cookie to logged-in users.
    No global API token is put into links, HTML or JavaScript.
    """
    if not getattr(identity, "super_user", False):
        raise HTTPException(status_code=403, detail="管理员权限不足")
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("X-HHClub-Request") != "1":
            raise HTTPException(status_code=403, detail="拒绝跨站修改请求")


class RescueCopyItem(BaseModel):
    downloader: str = ""
    hash: str = ""
    hash_short: str = ""
    name: str = ""
    tracker: str = ""
    match_type: str = ""
    trusted_tracker: bool = False
    completed: bool = False
    progress: float | None = None
    size_gb: float | None = None
    can_remove: bool = False
    can_delete_files: bool = False


class RescueSeedItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    size: float = 0
    seeders: int = 0
    seed_id: int | None = None
    downloader: str = ""
    downloaders: list[str] = Field(default_factory=list)
    matched: bool = False
    match_status: str = "unmatched"
    match_reason: str = ""
    can_delete: bool = False
    can_manage: bool = False
    can_delete_group: bool = False
    cross_seed_count: int = 0
    auxiliary_count: int = 0
    candidates: list[RescueCopyItem] = Field(default_factory=list)
    hash: str = ""



class RescueGroupTarget(BaseModel):
    downloader: str
    hash: str


class RescueGroupDeleteRequest(BaseModel):
    """Explicit all-hashes manifest from a confirmed manager-page snapshot."""
    request_id: str
    seed_id: int
    title: str
    targets: list[RescueGroupTarget] = Field(default_factory=list)
    confirm: bool = False
    delete_file: bool = True


class RescueSeedList(BaseModel):
    success: bool
    message: str = ""
    warning: str = ""
    data: list[RescueSeedItem] | None = None
    loading: bool = False
    elapsed_seconds: int = 0
    updated_at: str = ""
    retry_after_seconds: int = 3


class SettlementRecord(BaseModel):
    date: str = ""
    bean: float = 0
    pt: float = 0


class SettlementData(BaseModel):
    loading: bool = False
    elapsed_seconds: int = 0
    retry_after_seconds: int = 3
    labels: list[str] = Field(default_factory=list)
    bean: list[float | None] = Field(default_factory=list)
    pt: list[float | None] = Field(default_factory=list)
    days: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    total_bean: float = 0
    total_pt: float = 0
    updated_at: str = ""
    last_fetch_date: str = ""
    records_total: int = 0
    records: list[SettlementRecord] = Field(default_factory=list)
    fetch_state: str = ""
    attempt_count: int = 0
    diag: dict = Field(default_factory=dict)
    error: str = ""




class ActionResult(BaseModel):
    success: bool
    result: str = ""


class ResultData(BaseModel):
    result: str


class OperationResult(BaseModel):
    success: bool
    message: str = ""
    data: dict | None = None



def size_to_gb(text: str) -> Optional[float]:
    m = re.search(r'([\d.]+)\s*(TB|GB|MB|KB)', text or '', re.I)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2).upper()
    if unit == 'TB':
        return v * 1024
    if unit == 'GB':
        return v
    if unit == 'MB':
        return v / 1024
    if unit == 'KB':
        return v / 1048576
    return v


def tier_of(seeders: Optional[int]) -> int:
    n = seeders or 1
    if n <= 1:
        return 0
    if n <= 3:
        return 1
    if n <= 5:
        return 2
    return 99


TIER_NAMES = ("0-1人", "2-3人", "4-5人")
TIER_BADGE = {
    0: '<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:#22c55e;color:#fff;font-size:11px;">0-1人 ×3.0</span>',
    1: '<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:#3b82f6;color:#fff;font-size:11px;">2-3人 ×2.0</span>',
    2: '<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:#ef4444;color:#fff;font-size:11px;">4-5人 ×1.5</span>',
}

# Hosts 加速：标记区，只管理本插件写入的条目
HOSTS_MARK_START = '# >>> HHClubButler Hosts >>>'
HOSTS_MARK_END = '# <<< HHClubButler Hosts <<<'


class HHClubButler(_PluginBase):
    plugin_name = "憨憨保种区管家"
    plugin_desc = "自动优选添加及换种工具\n保种管理器/Hosts加速"
    plugin_icon = "https://raw.githubusercontent.com/xchenya/MoviePilot-Plugins/main/plugins.v3/hhclubbutler/icon.png"
    plugin_version = "3.0.13"
    plugin_author = "六个橙子"
    author_url = "https://github.com/SixOrg"
    plugin_config_prefix = "hhclubbutler_"
    plugin_order = 20
    auth_level = 1

    _enabled: bool = False
    _onlyonce: bool = False
    _notify: bool = False
    _cron: str = "30 14 * * *"
    _cookie: str = ""
    _site_url: str = ""
    _uid: str = ""
    _mode: str = "incremental"
    _target_volume: float = 0
    _seeder_cond: str = ""
    _exclude_zero: bool = False
    _downloader: str = ""          # 兼容旧配置（单选）
    _downloaders: list = []        # 管理下载器（多选）
    _push_downloader: str = ""     # 推送下载器（单选）
    _save_path: str = ""
    _tag: str = "hh"
    _upload_limit: int = 0
    _download_limit: int = 0
    _use_proxy: bool = False
    _download_options_error: str = ""
    _auto_clean_days: float = 0.0
    _hosts_enabled: bool = False
    _hosts_config: str = ""
    _hosts_errors: str = ""
    _scheduler = None

    _running: bool = False
    _last_result: str = "尚未运行"
    _last_overview: dict = None
    _last_overview_ts: float = 0.0
    _overview_hours: float = 6.0
    _overview_thread: Optional[threading.Thread] = None
    _overview_stop: Optional[threading.Event] = None

    def __init__(self):
        super().__init__()
        # V3 supports plugin clones: never share execution or refresh state between instances.
        self._run_lock = threading.Lock()
        self._enabled = False
        self._running = False
        self._last_result = "尚未运行"
        self._last_overview = None
        self._last_overview_ts = 0.0
        self._scheduler = None
        self._overview_thread = None
        self._overview_stop = None
        # Bound memory cache and a single in-flight read job per plugin instance.
        self._list_lock = threading.Lock()
        self._list_state = "idle"
        self._list_cache = None
        self._list_snapshot = None
        self._list_requested_clients = set()
        self._list_requested_full = False
        self._list_updated_at = 0.0
        self._list_started_at = 0.0
        self._list_finished_at = 0.0
        self._list_error = ""
        self._list_generation = 0
        self._list_thread = None
        self._list_cache_ttl = 180.0
        self._list_warning = ""
        # Short HTTP requests start/recover a single deletion job by request_id.
        # Never automatically repeat a destructive command when response is lost.
        self._delete_lock = threading.Lock()
        self._delete_jobs = {}
        self._delete_active_id = None
        self._delete_generation = 0
        self._delete_guard = {}
        self._delete_resolved = []
        self._delete_guard_loaded = False
        self._stats_lock = threading.Lock()
        self._stats_job_lock = threading.Lock()
        self._stats_job = {"state": "idle"}
        self._overview_refresh_lock = threading.Lock()
        self._overview_launch_lock = threading.Lock()
        self._overview_manual_thread = None
        self._stopped = False

    def init_plugin(self, config: dict = None):
        self.stop_service()
        self._stopped = False
        self._last_overview = None
        self._last_overview_ts = 0
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify"))
        self._cron = config.get("cron") or "30 14 * * *"
        self._cookie = config.get("cookie") or ""
        self._site_url = (config.get("site_url") or "").rstrip("/")
        self._uid = config.get("uid") or ""
        self._mode = config.get("mode") or "incremental"
        if self._mode not in ("incremental", "wash"):
            self._mode = "incremental"
        try:
            self._target_volume = float(config.get("target_volume") or 0)
        except (TypeError, ValueError):
            self._target_volume = 0
        self._seeder_cond = str(config.get("seeder_cond") or "").strip()
        self._exclude_zero = bool(config.get("exclude_zero"))
        _dl_old = str(config.get("downloader") or "")
        _dls = config.get("downloaders")
        if isinstance(_dls, list):
            _dls = [str(x) for x in _dls if str(x).strip()]
        else:
            _dls = []
        if not _dls and _dl_old:
            _dls = [_dl_old]
        self._downloader = _dl_old
        self._downloaders = _dls
        self._push_downloader = str(config.get("push_downloader") or "") or (_dls[0] if _dls else "")
        self._save_path = config.get("save_path") or ""
        self._tag = str(config.get("tag", "hh") or "").strip()
        self._use_proxy = bool(config.get("use_proxy", False))
        self._download_options_error = ""
        try:
            self._upload_limit = self._parse_speed_limit(config.get("upload_limit"))
            self._download_limit = self._parse_speed_limit(config.get("download_limit"))
        except (TypeError, ValueError, OverflowError):
            self._upload_limit = self._download_limit = 0
            self._download_options_error = "上传和下载限速须为 0～2147483647 的整数（KB/s），自动优选已停止"
            logger.warning(self._download_options_error)
        try:
            self._auto_clean_days = float(config.get("auto_clean_days") or 0)
        except (TypeError, ValueError):
            self._auto_clean_days = 0
        self._auto_clean_days = max(0.0, min(365.0, self._auto_clean_days))
        self._hosts_enabled = bool(config.get("hosts_enabled")) and self._enabled
        self._hosts_config = str(config.get("hosts_config") or "").strip()
        # Even on disable, remove the hosts block previously installed by this plugin.
        self._apply_hosts()
        self._overview_hours = 6.0
        if self._enabled:
            self._start_overview_thread()

        logger.info(f"憨憨保种区管家配置生效：启用={self._enabled} 通知={self._notify} "
                    f"模式={self._mode} 目标体积={self._target_volume:g} GB")

        if self._onlyonce:
            self._onlyonce = False
            self.update_config({
                **config,
                "enabled": self._enabled,
                "onlyonce": False,
                "notify": self._notify,
                "cron": self._cron,
                "mode": self._mode,
                "target_volume": self._target_volume,
                "seeder_cond": self._seeder_cond,
                "exclude_zero": self._exclude_zero,
                "uid": self._uid,
                "cookie": self._cookie,
                "site_url": self._site_url,
                "downloader": self._downloader,
                "downloaders": self._downloaders,
                "push_downloader": self._push_downloader,
                "save_path": self._save_path,
                "tag": self._tag,
                "use_proxy": self._use_proxy,
                "auto_clean_days": self._auto_clean_days,
            })
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.run,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="憨憨保种区管家（立即运行）"
            )
            self._scheduler.start()

    @staticmethod
    def _parse_speed_limit(value) -> int:
        if value is None or value == "":
            return 0
        if isinstance(value, bool):
            raise ValueError("限速必须是非负整数")
        number = float(value)
        if not 0 <= number <= 2147483647 or not number.is_integer():
            raise ValueError("限速必须是非负整数")
        return int(number)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/hhan_rescue",
            "event": EventType.PluginAction,
            "desc": "憨憨保种区管家运行",
            "category": "插件命令",
            "data": {"action": "HHClubButler.run"}
        }]

    @eventmanager.register(EventType.PluginAction)
    def _handle_command(self, event: Event):
        data = event.event_data or {}
        if self._enabled and data.get("action") == "HHClubButler.run":
            self.run()

    def get_api(self) -> List[Dict[str, Any]]:
        # 独立窗口不能附加 Bearer header；使用 V3 的 HttpOnly 资源 Cookie。
        # 这些端点的 allow_anonymous 仅表示由显式 Depends 处理认证，并非公开访问。
        page_deps = [Depends(_require_resource_admin)]
        return [
            {"path": "/run", "endpoint": self.api_run, "methods": ["POST"],
             "dependencies": [Depends(_require_bear_admin)],
             "auth": "bear", "summary": "立即运行优选", "response_model": ActionResult},
            {"path": "/result", "endpoint": self.api_result, "methods": ["GET"],
             "auth": "bear", "summary": "最近运行结果", "response_model": ResultData},
            {"path": "/refresh_overview", "endpoint": self.api_refresh_overview,
             "methods": ["POST"], "auth": "bear", "summary": "刷新概况",
             "response_model": OperationResult},
            {"path": "/list_rescue_seeds", "endpoint": self.api_list_rescue_seeds,
             "methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "当前保种种子", "response_model": RescueSeedList},
            {"path": "/delete_rescue_seed", "endpoint": self.api_delete_rescue_seed,
             "methods": ["POST"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "提交经确认的后台删除任务",
             "response_model": OperationResult},
            {"path": "/delete_rescue_group", "endpoint": self.api_delete_rescue_group,
             "methods": ["POST"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "按已确认的 Hash 清单删除全部辅种任务及文件",
             "response_model": OperationResult},
            {"path": "/delete_rescue_status", "endpoint": self.api_delete_rescue_status,
             "methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "查询删除任务状态（绝不执行删除）",
             "response_model": OperationResult},
            {"path": "/rescue_panel", "endpoint": self.api_rescue_panel,
             "methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "保种管理器", "response_model": None,
             "response_class": HTMLResponse,
             "responses": {200: {"content": {"text/html": {"schema": {"type": "string"}}}}}},
            {"path": "/monthly_stats", "endpoint": self.api_monthly_stats,
             "methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "结算统计页", "response_model": None,
             "response_class": HTMLResponse,
             "responses": {200: {"content": {"text/html": {"schema": {"type": "string"}}}}}},
            {"path": "/monthly_stats_data", "endpoint": self.api_monthly_stats_data,
             "methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps,
             "summary": "结算统计数据", "response_model": SettlementData},
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self.get_state():
            return []
        return [{
            "id": "HHClubButler",
            "name": "憨憨保种区管家保种优选服务",
            "trigger": CronTrigger.from_crontab(self._cron),
            "func": self.run,
            "kwargs": {}
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        downloaders = []
        try:
            for config in DownloaderHelper().get_configs().values():
                downloaders.append({"title": config.name, "value": config.name})
        except Exception as e:
            logger.warning(f"获取下载器列表失败：{HHClubButler._safe_error(e)}")
        form = [
            {
                'component': 'VForm',
                'content': [
                    {**self._overview_form_cards()},
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 3},
                             'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 3},
                             'content': [{'component': 'VSwitch', 'props': {'model': 'hosts_enabled', 'label': 'Hosts 加速'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 3},
                             'content': [{'component': 'VSwitch', 'props': {'model': 'onlyonce', 'label': '立即运行一次'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 3},
                             'content': [{'component': 'VSwitch', 'props': {'model': 'notify', 'label': '发送通知'}}]},
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VCronField', 'props': {
                                 'model': 'cron', 'label': '执行周期',
                                 'placeholder': '30 14 * * *（每天14:30，保种区14:10更新后）'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VTextarea', 'props': {
                                 'model': 'hosts_config', 'label': 'Hosts配置（插件加载缓慢请配置）',
                                 'rows': 1,
                                 'no-resize': False,
                                 'hint': '开启并填写可加速站点（支持配置其他站）',
                                 'persistent-hint': True,
                                 'placeholder': '格式：IP 域名，每行一条；留空不生效，关闭自动还原，适用其他站点加速\n示例：104.17.141.143 hhanclub.net'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VSelect', 'props': {
                                 'model': 'downloaders', 'label': '管理下载器（多选）', 'items': downloaders,
                                 'multiple': True,
                                 'hint': '统计/优选/管理/删除覆盖所选下载器',
                                 'persistent-hint': True}}]},
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VSelect', 'props': {
                                 'model': 'push_downloader', 'label': '推送下载器（单选）', 'items': downloaders,
                                 'hint': '新增任务的下载器，默认=管理下载器第一个',
                                 'persistent-hint': True}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'save_path', 'label': '保存路径（跟随推送下载器）',
                                 'placeholder': '如 /downloads/下载/保种'}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'tag', 'label': '自定义标签',
                                 'placeholder': 'hh',
                                 'hint': '仅用于插件新添加的任务，默认 hh；留空不打标签',
                                 'persistent-hint': True}}]},
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'upload_limit', 'label': '单任务上传限速（KB/s）',
                                 'type': 'number', 'min': 0, 'max': 2147483647, 'step': 1,
                                 'hint': '仅用于新任务；0=不设单任务限制，仍受下载器全局限制',
                                 'persistent-hint': True}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'download_limit', 'label': '单任务下载限速（KB/s）',
                                 'type': 'number', 'min': 0, 'max': 2147483647, 'step': 1,
                                 'hint': '与 MP 限速单位一致；上传、下载分别设置',
                                 'persistent-hint': True}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                             'content': [{'component': 'VSwitch', 'props': {
                                 'model': 'use_proxy', 'label': '使用 MP 代理',
                                 'hint': '用于站点页面、结算及种子文件请求；需先在 MP 配置代理',
                                 'persistent-hint': True}}]},
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 6},
                             'content': [{'component': 'VSelect', 'props': {
                                 'model': 'mode', 'label': '优选模式',
                                 'items': [
                                     {'title': '增量优选（不删保种&补齐体积）', 'value': 'incremental'},
                                     {'title': '换种优选（删低档位&补高档位）', 'value': 'wash'}
                                 ]}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 6},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'target_volume',
                                 'label': '目标体积（GB，总保种上限）',
                                 'type': 'number',
                                 'hint': '含已做种总体积，0=不限',
                                 'persistent-hint': True}}]},
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 6},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'seeder_cond',
                                 'label': '做种人数',
                                 'hint': '支持单值或区间，例如 1 或 1-5，留空=系统自行优选',
                                 'persistent-hint': True}}]},
                            {'component': 'VCol', 'props': {'cols': 12, 'md': 6},
                             'content': [{'component': 'VTextField', 'props': {
                                 'model': 'auto_clean_days',
                                 'label': '自动清理未完成下载（天）',
                                 'hint': '超过N天仍未下载完成自动删除（含未完成文件）；留空或0=不清理',
                                 'persistent-hint': True}}]},
                        ]
                    },
                ]
            }
        ]
        defaults = {
            "enabled": False, "onlyonce": False, "notify": True,
            "cron": "30 14 * * *", "mode": "incremental",
            "target_volume": 0, "seeder_cond": "", "exclude_zero": False,
            "downloader": "", "downloaders": [], "push_downloader": "",
            "save_path": "", "tag": "hh", "auto_clean_days": 0,
            "upload_limit": 0, "download_limit": 0, "use_proxy": False,
            "hosts_enabled": False, "hosts_config": "",
        }
        return form, defaults

    def _get_hosts_path(self) -> str:
        if os.name == "nt":
            root = os.environ.get("SystemRoot") or "C:\\Windows"
            return os.path.join(root, "System32", "drivers", "etc", "hosts")
        return "/etc/hosts"

    def _parse_hosts_config(self, text: str) -> Tuple[List[str], List[str]]:
        import ipaddress
        valid, errors = [], []
        for line in (text or "").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            try:
                ipaddress.ip_address(parts[0])
            except ValueError:
                errors.append(f"{s} — IP 地址无效")
                continue
            if len(parts) < 2:
                errors.append(f"{s} — 缺少域名")
                continue
            valid.append(" ".join(parts))
        return valid, errors

    def _read_hosts_lines(self, path: str) -> List[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().splitlines()
        except Exception:
            return []

    def _write_hosts_lines(self, path: str, lines: List[str]) -> bool:
        try:
            content = "\n".join(lines) + "\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.warning(f"Hosts 文件写入失败（权限不足或只读）：{HHClubButler._safe_error(e)}")
            return False

    @staticmethod
    def _strip_hosts_block(lines: List[str]) -> List[str]:
        out, in_block = [], False
        for line in lines:
            s = line.strip()
            if s == HOSTS_MARK_START:
                in_block = True
                continue
            if s == HOSTS_MARK_END:
                in_block = False
                continue
            if not in_block:
                out.append(line)
        return out

    def _apply_hosts(self):
        try:
            path = self._get_hosts_path()
            if not self._hosts_enabled:
                cur = self._read_hosts_lines(path)
                if cur:
                    stripped = self._strip_hosts_block(cur)
                    if stripped != cur:
                        if self._write_hosts_lines(path, stripped):
                            logger.info("Hosts 加速已关闭，已还原系统 hosts 文件")
                        else:
                            self._hosts_errors = "Hosts 还原失败（写入被拒绝），请检查 hosts 文件权限"
                    else:
                        logger.info("Hosts 加速未启用，系统 hosts 无需还原")
                self._hosts_errors = ""
                return
            valid, errors = self._parse_hosts_config(self._hosts_config)
            self._hosts_errors = "；".join(errors[:5]) if errors else ""
            if not valid:
                logger.info("Hosts 加速已开启但配置为空或无效，未写入（留空不生效）")
                return
            cur = self._read_hosts_lines(path)
            lines = self._strip_hosts_block(cur)
            lines.append(HOSTS_MARK_START)
            lines.extend(valid)
            lines.append(HOSTS_MARK_END)
            if self._write_hosts_lines(path, lines):
                logger.info(f"Hosts 加速已写入 {len(valid)} 条 → {path}")
                self._hosts_errors = ""
            else:
                self._hosts_errors = "Hosts 写入失败（权限不足），请以管理员/root 权限运行或手动配置"
        except Exception as e:
            logger.error(f"Hosts 加速应用异常：{HHClubButler._safe_error(e)}")
            self._hosts_errors = f"Hosts 加速应用异常：{HHClubButler._safe_error(e)}"

    def _overview_form_cards(self) -> dict:
        if not self._last_overview or not self._last_overview.get("ok"):
            return {'component': 'VCard', 'props': {'flat': True},
                    'content': [{'component': 'VCardText', 'props': {},
                                 'text': '尚未运行或未获取到数据（运行一次后此处显示最近概况）'}]}
        ov = self._last_overview
        d = ov["dist"]
        c = ov.get("count", 0) or sum(x["count"] for x in d.values()) or 1
        c01 = d["0-1人"]["count"] / c * 100.0
        c23 = d["2-3人"]["count"] / c * 100.0
        c45 = d["4-5人"]["count"] / c * 100.0

        def stat_col(label, num, sub=""):
            return {'component': 'VCol', 'props': {'cols': 6, 'md': 3},
                    'content': [
                        {'component': 'div',
                         'props': {'style': 'text-align:center;font-size:11px;color:rgba(var(--v-theme-on-surface),.6);white-space:nowrap;'},
                         'text': label},
                        {'component': 'div',
                         'props': {'style': 'text-align:center;font-size:17px;font-weight:700;white-space:nowrap;'},
                         'text': f'{num} {sub}'},
                    ]}

        def legend_col(key, align):
            color_map = {"0-1人": "#22c55e", "2-3人": "#3b82f6", "4-5人": "#ef4444"}
            sq = color_map.get(key, "#999")
            return {'component': 'VCol', 'props': {'cols': 12, 'md': 4},
                    'content': [{'component': 'div',
                                 'props': {'style': f'display:flex;align-items:center;justify-content:{align == "left" and "flex-start" or align == "right" and "flex-end" or "center"};font-size:11px;color:rgba(var(--v-theme-on-surface),.6);white-space:nowrap;'},
                                 'content': [
                                     {'component': 'div', 'props': {'style': f'width:8px;height:8px;background:{sq};margin-right:4px;flex-shrink:0;'}, 'text': ''},
                                     {'component': 'span', 'props': {}, 'text': f'{key} {d[key]["count"]}个 {d[key]["gb"]:.1f}GB'},
                                 ]}]}

        last_bean = ov.get("last_bean")
        last_pt = ov.get("last_pt")
        last_date = ov.get("last_date", "")
        bean_txt = f'{last_bean:.0f}' if isinstance(last_bean, (int, float)) else '—'
        pt_txt = f'{last_pt:.0f}' if isinstance(last_pt, (int, float)) else '—'

        return {'component': 'VCard', 'props': {'flat': True},
                'content': [
                    {'component': 'VCardText', 'props': {'class': 'pt-2'},
                     'content': [
                         {'component': 'VRow', 'content': [
                             stat_col("🌱 在保种子", ov.get("count", 0), "个"),
                             stat_col("💾 总体积", f'{ov.get("total_gb", 0.0):.1f}', "GB"),
                             stat_col("🥜 上次憨豆", bean_txt, ""),
                             stat_col("⭐ 上次积分", pt_txt, ""),
                         ]},
                         {'component': 'div',
                          'props': {'style': 'margin-top:8px;margin-bottom:4px;font-size:11px;color:rgba(var(--v-theme-on-surface),.6);'},
                          'text': f'初始做种人数分布' + (f' · 上次结算 {last_date}' if last_date else '')},
                         {'component': 'div',
                          'props': {'style': 'width:100%;display:flex;border-radius:4px;overflow:hidden;'},
                          'content': [
                              {'component': 'div', 'props': {'style': f'height:8px;width:{c01:.2f}%;background:#22c55e;'}, 'text': ''},
                              {'component': 'div', 'props': {'style': f'height:8px;width:{c23:.2f}%;background:#3b82f6;'}, 'text': ''},
                              {'component': 'div', 'props': {'style': f'height:8px;width:{c45:.2f}%;background:#ef4444;'}, 'text': ''},
                          ]},
                         {'component': 'VRow', 'props': {'no-gutters': True}, 'content': [
                             legend_col("0-1人", "left"),
                             legend_col("2-3人", "center"),
                             legend_col("4-5人", "right"),
                         ]},
                         {'component': 'VRow', 'props': {'class': 'd-flex align-center', 'no-gutters': True, 'style': 'margin-top:8px;'},
                          'content': [
                              {'component': 'VCol', 'props': {'cols': 'auto'},
                               'content': [{'component': 'div',
                                            'props': {'style': 'font-size:10.5px;color:rgba(var(--v-theme-on-surface),.4);'},
                                            'text': HHClubButler._refresh_note(self._last_overview_ts, self._overview_hours)}]},
                              {'component': 'VCol', 'props': {'cols': True},
                               'content': [{'component': 'div',
                                            'props': {'style': 'font-size:10.5px;color:rgba(var(--v-theme-on-surface),.4);text-align:right;'},
                                            'text': '左下角 [查看数据] 内置 [立即刷新] 及 [保种管理器]'}]},
                          ]},
                     ]},
                    {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal',
                                                     'text': f"最近运行状态：{self._last_result}"}}
                ]}

    @staticmethod
    def _overview_html(ov: dict, last_ts: float = 0.0, hours: float = 6.0) -> str:
        if not ov or not ov.get("ok"):
            return ('<div style="padding:12px 14px;border-radius:10px;'
                    'border:1px solid rgba(var(--v-theme-on-surface),.08);'
                    'background:rgba(var(--v-theme-surface),.55);'
                    'color:rgba(var(--v-theme-on-surface),.72);font-size:12px;">'
                    '憨憨保种区管家：未获取到数据（请确认插件已启用、下载器已选择、完成页/下载器可访问）</div>')
        d = ov["dist"]
        t_gb = ov.get("total_gb", 0.0) or 1.0
        C = {"0-1人": "#22c55e", "2-3人": "#3b82f6", "4-5人": "#ef4444"}
        ON = "rgb(var(--v-theme-on-surface))"
        ON60 = "rgba(var(--v-theme-on-surface),.6)"
        ON40 = "rgba(var(--v-theme-on-surface),.4)"

        def pct(k):
            return (d[k]["gb"] / t_gb * 100.0) if t_gb else 0.0

        last_bean = ov.get("last_bean")
        last_pt = ov.get("last_pt")
        last_date = ov.get("last_date", "")
        bean_txt = f'{last_bean:.0f}' if isinstance(last_bean, (int, float)) else '—'
        pt_txt = f'{last_pt:.0f}' if isinstance(last_pt, (int, float)) else '—'

        def td(label, num, sub):
            return (f'<td style="text-align:center;padding:4px 2px;width:25%;vertical-align:top;">'
                    f'<div style="font-size:10.5px;color:{ON60};white-space:nowrap;">{label}</div>'
                    f'<div style="font-size:17px;font-weight:700;color:{ON};line-height:1.4;white-space:nowrap;">{num}'
                    f'<span style="font-size:10px;font-weight:400;color:{ON40};"> {sub}</span></div></td>')

        cells = ('<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:2px 0 6px;"><tr>'
                 + td("🌱 在保种子", f'{ov["count"]}', "个")
                 + td("💾 总体积", f'{ov["total_gb"]:.1f}', "GB")
                 + td("🥜 上次憨豆", bean_txt, "")
                 + td("⭐ 上次积分", pt_txt, "")
                 + '</tr></table>')
        bar = ('<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:6px 0 6px;"><tr>'
               f'<td style="height:10px;width:{pct("0-1人"):.2f}%;background:{C["0-1人"]};border-radius:5px 0 0 5px;"></td>'
               f'<td style="height:10px;width:{pct("2-3人"):.2f}%;background:{C["2-3人"]};"></td>'
               f'<td style="height:10px;width:{pct("4-5人"):.2f}%;background:{C["4-5人"]};border-radius:0 5px 5px 0;"></td>'
               '</tr></table>')
        legend = ('<table style="width:100%;border-collapse:collapse;table-layout:fixed;font-size:10.5px;color:{ON60};"><tr>'
                  f'<td style="text-align:left;white-space:nowrap;"><span style="display:inline-block;width:7px;height:7px;border-radius:2px;background:{C["0-1人"]};margin-right:3px;"></span>0-1人 {d["0-1人"]["count"]}个 {d["0-1人"]["gb"]:.1f}GB</td>'
                  f'<td style="text-align:center;white-space:nowrap;"><span style="display:inline-block;width:7px;height:7px;border-radius:2px;background:{C["2-3人"]};margin-right:3px;"></span>2-3人 {d["2-3人"]["count"]}个 {d["2-3人"]["gb"]:.0f}GB</td>'
                  f'<td style="text-align:right;white-space:nowrap;"><span style="display:inline-block;width:7px;height:7px;border-radius:2px;background:{C["4-5人"]};margin-right:3px;"></span>4-5人 {d["4-5人"]["count"]}个 {d["4-5人"]["gb"]:.1f}GB</td>'
                  '</tr></table>')
        dist_title = (f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:2px 0 2px;"><tr>'
                      f'<td style="text-align:left;font-size:10.5px;color:{ON60};">初始做种人数分布'
                      + (f' · 上次结算 {last_date}' if last_date else '')
                      + '</td></tr></table>')
        return f'<div style="background:transparent;">{cells}{dist_title}{bar}{legend}</div>'

    @staticmethod
    def _refresh_note(last_ts: float = 0.0, hours: float = 6.0) -> str:
        if last_ts and last_ts > 0:
            mins = max(0, int((time.time() - last_ts) / 60))
            if mins >= 60:
                h, m = divmod(mins, 60)
                ago = f"{h} 小时 {m} 分钟前" if m else f"{h} 小时前"
            else:
                ago = f"{mins} 分钟前"
            if hours > 0:
                return f"每 {hours:g} 小时自动刷新一次 · 上次更新 {ago}"
            return f"上次更新 {ago}"
        return f"每 {hours:g} 小时自动刷新一次"


    def get_page(self) -> List[dict]:
        overview = None
        try:
            overview = self._get_overview_cached_or_refresh()
        except Exception as e:
            logger.error(f"获取憨憨保种区管家概况失败：{HHClubButler._safe_error(e)}")
        panel_link = (
            '<div style="padding:10px 0;display:flex;align-items:center;gap:10px;">'
            '<a href="/api/v1/plugin/HHClubButler/monthly_stats" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-flex;align-items:center;gap:6px;padding:7px 18px;background:rgba(66,165,245,.12);'
            'color:#42A5F5;text-decoration:none;border-radius:4px;font-size:13px;font-weight:500;border:1px solid rgba(66,165,245,.3);">'
            '📊 结算统计表</a>'
            '<a href="/api/v1/plugin/HHClubButler/rescue_panel" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-flex;align-items:center;gap:6px;padding:7px 18px;background:rgba(66,165,245,.12);'
            'color:#42A5F5;text-decoration:none;border-radius:4px;font-size:13px;font-weight:500;border:1px solid rgba(66,165,245,.3);">'
            '🖥️ 保种管理器</a>'
            '<span style="font-size:11px;color:rgba(var(--v-theme-on-surface),.45);">独立工作台 · 批量删除 · 搜索 · 筛选</span>'
            '</div>'
        )
        return [{
            'component': 'VRow', 'props': {'density': 'compact', 'no-gutters': True},
            'content': [
                {'component': 'VCol', 'props': {'cols': 12, 'md': 12},
                 'content': [
                     {'component': 'VRow', 'props': {'class': 'd-flex justify-space-between align-center', 'no-gutters': True},
                      'content': [
                          {'component': 'div', 'html': (
                              '<div style="font-size:10.5px;color:rgba(var(--v-theme-on-surface),.4);'
                              'margin-right:10px;white-space:nowrap;">'
                              + HHClubButler._refresh_note(self._last_overview_ts, self._overview_hours)
                              + '</div>')},
                          {'component': 'div', 'html': '<a style="cursor:pointer;color:#42A5F5;text-decoration:none;white-space:nowrap;">🔄 立即刷新</a>',
                           'events': {'click': {'api': 'plugin/HHClubButler/refresh_overview', 'method': 'post'}}}
                      ]},
                     {'component': 'div', 'html': HHClubButler._overview_html(
                         overview, self._last_overview_ts, self._overview_hours)},
                     {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal',
                                                      'text': f"最近运行状态：{self._last_result}"}},
                     {'component': 'div', 'html': panel_link},
                 ]},
            ]
        }]

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        return [{"key": "seeding", "name": "憨憨保种区管家"}]

    def get_dashboard(self, key: str, **kwargs):
        if key and key != "seeding":
            return None
        try:
            overview = self._get_overview_cached_or_refresh()
        except Exception as e:
            logger.error(f"仪表盘概况获取失败：{HHClubButler._safe_error(e)}")
            overview = {"count": 0, "total_gb": 0.0,
                        "dist": {"0-1人": {"count": 0, "gb": 0.0},
                                 "2-3人": {"count": 0, "gb": 0.0},
                                 "4-5人": {"count": 0, "gb": 0.0}}}
        elements = [
            {'component': 'div',
             'props': {'style': 'text-align:left;font-size:10.5px;color:rgba(var(--v-theme-on-surface),.4);margin-bottom:6px;white-space:nowrap;'},
             'text': HHClubButler._refresh_note(self._last_overview_ts, self._overview_hours)},
            {'component': 'div', 'html': HHClubButler._overview_html(
                overview, self._last_overview_ts, self._overview_hours)}
        ]
        return ({"cols": 12, "md": 6},
                {"refresh": 60, "title": "憨憨保种区管家", "border": True},
                elements)

    def stop_service(self):
        self._stopped = True
        with self._delete_lock:
            # Reconfiguration invalidates an in-flight job's permission to send
            # a deletion after a potentially long site lookup.
            self._delete_generation += 1
        with self._stats_job_lock:
            self._stats_job = {"state": "idle"}
        with self._list_lock:
            # A prior worker may still be waiting on a remote site: invalidate
            # its generation so it cannot overwrite cache after reconfiguration.
            self._list_generation += 1
            self._list_state = "idle"
            self._list_cache = None
            self._list_snapshot = None
            self._list_requested_clients = set()
            self._list_requested_full = False
            self._list_updated_at = 0.0
            self._list_error = ""
            self._list_warning = ""
            self._list_thread = None
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止插件服务失败：{HHClubButler._safe_error(e)}")
        try:
            if self._overview_stop:
                self._overview_stop.set()
            if self._overview_thread and self._overview_thread.is_alive():
                self._overview_thread.join(timeout=3)
        except Exception as e:
            logger.error(f"停止概况刷新线程失败：{HHClubButler._safe_error(e)}")
        finally:
            self._overview_stop = None
            self._overview_thread = None

    def _start_overview_thread(self):
        try:
            stop_event = threading.Event()
            self._overview_stop = stop_event
            self._overview_thread = threading.Thread(
                target=self._overview_loop, args=(stop_event,),
                daemon=True, name="HHClubButler-OverviewRefresh")
            self._overview_thread.start()
        except Exception as e:
            logger.error(f"启动概况刷新线程失败：{HHClubButler._safe_error(e)}")

    def _overview_loop(self, stop_event: threading.Event):
        # Use the captured event, not the mutable self._overview_stop.
        # An old thread cannot accidentally join a newly created loop after reload.
        while not stop_event.is_set():
            try:
                try:
                    self._ensure_monthly_stats()
                except Exception as e:
                    logger.error(f"结算日志重试检查失败：{HHClubButler._safe_error(e)}")
                if stop_event.is_set():
                    return
                hours = self._overview_hours
                if hours > 0:
                    wait = hours * 3600.0 - (time.time() - self._last_overview_ts)
                    if wait <= 0:
                        ok = self._refresh_overview()
                        # Failed refresh should retry instead of sleeping six hours.
                        wait = hours * 3600.0 if ok else 300.0
                    stop_event.wait(min(wait, 300.0))
                else:
                    stop_event.wait(300)
            except Exception as e:
                logger.error(f"概况刷新线程异常：{HHClubButler._safe_error(e)}")
                stop_event.wait(300)

    def _refresh_overview(self, manual: bool = False):
        if self._stopped or not self._overview_refresh_lock.acquire(blocking=False):
            return False
        try:
            return self._refresh_overview_impl(manual=manual)
        finally:
            self._overview_refresh_lock.release()

    def _refresh_overview_impl(self, manual: bool = False):
        generation = self._delete_generation
        try:
            # 顺带刷新结算统计表数据：当日已成功则直接命中本地缓存，未拉取过则翻页拉取一次并落盘；
            # 与完成页刷新互相隔离，失败不影响概况
            try:
                self._ensure_monthly_stats()
            except Exception as e:
                logger.error(f"结算统计表数据顺带刷新失败：{HHClubButler._safe_error(e)}")
            cur = self._get_current_seeding([])
            if cur.get("error"):
                logger.warning(f"憨憨保种区管家概况刷新失败（{cur['error']}），保留上次数据")
                return False
            if cur.get("degraded"):
                logger.warning(f"憨憨保种区管家概况刷新失败（{cur['degraded']}），保留上次数据")
                return False
            overview = self._build_overview_from_current(cur)
            if self._stopped or generation != self._delete_generation:
                return False
            self._last_overview = overview
            self._last_overview_ts = time.time()
            logger.info(f"憨憨保种区管家概况已{'手动' if manual else '自动'}刷新："
                        f"{cur.get('count', 0)} 个 / {cur.get('total_gb', 0.0):.1f} GB"
                        f" / 上次憨豆 {self._last_overview.get('last_bean', '—')}"
                        f" / 上次积分 {self._last_overview.get('last_pt', '—')}")
            return True
        except Exception as e:
            logger.error(f"概况{'手动' if manual else '自动'}刷新失败：{HHClubButler._safe_error(e)}")
            return False

    def _get_overview_cached_or_refresh(self) -> dict:
        # The plugin page and dashboard must never block on external sites.
        # The overview scheduler handles initial and periodic refreshes.
        return self._last_overview or {
            "count": 0, "total_gb": 0.0,
            "dist": {"0-1人": {"count": 0, "gb": 0.0},
                     "2-3人": {"count": 0, "gb": 0.0},
                     "4-5人": {"count": 0, "gb": 0.0}}}

    def api_run(self):
        if not self._enabled:
            return {"success": False, "result": "请先启用插件"}
        if self._running or self._run_lock.locked():
            return {"success": False, "result": "憨憨保种区管家正在运行中"}
        threading.Thread(target=self.run, daemon=True, name="HHClubButler-ManualRun").start()
        return {"success": True, "result": "已在后台启动优选，请查看运行日志"}

    def api_result(self):
        return {"result": self._last_result}

    def api_refresh_overview(self):
        """Start a read-only overview refresh without holding an HTTP request."""
        if self._stopped or not self._enabled:
            return {"success": False, "message": "插件未启用", "data": None}
        with self._overview_launch_lock:
            running = self._overview_manual_thread
            if self._overview_refresh_lock.locked() or (running and running.is_alive()):
                return {"success": True, "message": "概况正在后台刷新", "data": None}
            worker = threading.Thread(
                target=self._refresh_overview, kwargs={"manual": True},
                daemon=True, name="HHClubButler-ManualOverview")
            self._overview_manual_thread = worker
            worker.start()
        return {"success": True, "message": "已开始后台刷新，稍后重新查看概况", "data": None}

    def _prefetch_downloader_torrents(self) -> Optional[list]:
        try:
            torrents = self._fetch_all_downloader_torrents()
            return torrents or None
        except Exception as e:
            logger.warning(f"预取下载器种子失败：{HHClubButler._safe_error(e)}")
            return None

    def _collect_rescue_seeds(self, strict_downloaders: bool = False, *,
                              snapshot: dict | None = None,
                              refresh_downloaders: tuple = ()) -> list[dict]:
        """Complete site rescue inventory, with optional downloader annotations.

        This view must NEVER call _get_current_seeding: that intersection is
        intentionally reserved for auto-optimization and deletion guards.
        """
        started = time.monotonic()
        logs = []
        partial = bool(refresh_downloaders and snapshot is not None and "completed" in snapshot)
        if strict_downloaders and snapshot is not None:
            raise ValueError("删除核验不能使用列表快照")
        if refresh_downloaders and not partial:
            raise ValueError("没有可用的站点快照，请手动刷新完整列表")
        completed = snapshot["completed"] if partial else self._fetch_completed(logs)
        if not completed and any("失败" in line or "未获取到" in line for line in logs):
            raise RuntimeError("站点完成页抓取失败，拒绝使用不完整列表")
        logger.info(f"憨憨保种管理器：站点全部可保种记录 {len(completed)} 条，"
                    f"用时 {time.monotonic()-started:.1f}s")
        downloader_rows = []
        read_clients, read_hashes = set(), []
        warnings = []
        downloaded = {}
        services = self._get_manage_services()
        requested = set(refresh_downloaders if partial else self._downloaders or [])
        missing = requested - set(services)
        if missing:
            warnings.append("以下已选下载器不可用：" + "、".join(sorted(missing)))
            if strict_downloaders or partial:
                raise RuntimeError("管理下载器不可用，不能核实删除目标")
        if not services:
            if strict_downloaders or partial:
                raise RuntimeError("未配置有效的管理下载器，不能核实删除目标")
            warnings.append("未选择可用下载器，站点清单仍会完整显示")
        if partial:
            for name in set(self._downloaders or []) - requested:
                cached = snapshot.get("downloaders", {}).get(name)
                if cached is None:
                    raise ValueError("下载器快照不完整，请手动刷新完整列表")
                downloader_rows.extend(cached["rows"])
                warnings.extend(cached["warnings"])
                downloaded[name] = cached
        for name, service in services.items():
            if partial and name not in requested:
                continue
            row_start, warning_start = len(downloader_rows), len(warnings)
            try:
                torrents, error = service.instance.get_torrents()
                if error or torrents is None:
                    if strict_downloaders or partial:
                        raise RuntimeError(f"下载器 {name} 读取失败，拒绝删除")
                    warnings.append(f"{name} 种子读取失败")
                    continue
                try:
                    dl_type = str(service.config.type or service.type or "")
                except Exception:
                    dl_type = ""
                tracker_fields_seen, trusted_tracker_count = 0, 0
                complete_hashes = True
                for torrent in torrents:
                    def g(*keys):
                        for key in keys:
                            try:
                                value = (torrent.get(key) if isinstance(torrent, dict)
                                         else getattr(torrent, key, None))
                                if value is not None:
                                    return value
                            except Exception:
                                pass
                        return None
                    infohash = str(g("hash", "hashString") or "").lower()
                    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash, re.I):
                        complete_hashes = False
                        if strict_downloaders or partial:
                            raise ValueError("下载器任务清单缺少 Hash")
                    else:
                        read_hashes.append({"downloader": name, "hash": infohash})
                    label = str(g("name") or "")
                    if not label:
                        continue
                    progress = self._get_progress_ratio(torrent, dl_type)
                    size_bytes = (g("total_size") or g("totalSize") or g("size"))
                    try:
                        size_gb = float(size_bytes) / 1073741824 if size_bytes else None
                    except (ValueError, TypeError):
                        size_gb = None
                    tracker = self._extract_tracker_text(torrent, dl_type)
                    trusted_tracker = is_trusted_hh_tracker(tracker)
                    tracker_fields_seen += int(bool(tracker))
                    trusted_tracker_count += int(bool(trusted_tracker))
                    site_tracker = trusted_tracker or any(
                        d in tracker.casefold() for d in
                        ("hhanclub", "hhancclub", "hhclub", "hanclub")
                    )
                    parsed_domain = re.search(r"https?://([A-Za-z0-9.:-]+)", tracker)
                    try:
                        added = g("added_on", "added_date", "date_added", "dateAdded")
                        if hasattr(added, "timestamp"):
                            added = added.timestamp()
                        added_stamp = float(added or 0)
                        added_at = (datetime.fromtimestamp(int(added)).strftime("%Y-%m-%d")
                                    if added and int(added) > 1000000000 else "")
                    except (TypeError, ValueError, OverflowError, OSError):
                        added_at, added_stamp = "", 0
                    downloader_rows.append({
                        "name": label, "downloader": name,
                        "hash": str(g("hash", "hashString") or ""),
                        "progress": progress, "size_gb": size_gb,
                        "completed": self._is_completed(torrent, dl_type),
                        "added_timestamp": added_stamp,
                        "state": str(g("state", "status") or ""),
                        "site_tracker": site_tracker,
                        "trusted_tracker": trusted_tracker,
                        "upspeed": g("upspeed", "rateUpload", "upload_speed", "uploadRate"),
                        "dlspeed": g("dlspeed", "rateDownload", "download_speed", "downloadRate"),
                        "eta": g("eta"), "ratio": g("ratio", "uploadRatio"),
                        "path": str(g("save_path", "downloadDir", "download_dir",
                                      "content_path", "path", "dir") or ""),
                        "cur_seeders": g("num_seeds", "seeds", "seeders", "seederCount"),
                        "cur_leechers": g("num_leechs", "leechs", "leechers", "leecherCount"),
                        "tracker": parsed_domain.group(1) if parsed_domain else "",
                        "added": added_at,
                    })
                if complete_hashes:
                    read_clients.add(name)
                logger.info(f"憨憨保种管理器：下载器 {name} 种子 {len(torrents)} 条，"
                            f"Tracker 字段可读 {tracker_fields_seen} 条 / "
                            f"本站主机可识别 {trusted_tracker_count} 条（仅作诊断，不影响人工删除）")
            except Exception as e:
                logger.warning(f"憨憨保种管理器：下载器 {name} 数据解析失败：{HHClubButler._safe_error(e)}")
                if strict_downloaders or partial:
                    raise RuntimeError(f"下载器 {name} 数据不完整，拒绝删除") from e
                warnings.append(f"{name} 数据解析失败")
            finally:
                downloaded[name] = {"rows": downloader_rows[row_start:], "warnings": warnings[warning_start:]}
        self._reconcile_delete_guard(read_hashes, read_clients)
        rows, stats = associate_rescue_seeds(completed, downloader_rows)
        rows = self._append_downloader_incomplete(rows, downloader_rows)
        if snapshot is not None:
            snapshot.update(completed=completed, downloaders=downloaded, warning="；".join(warnings))
        extra = sum(1 for row in rows if row.get("source") == "downloader")
        if snapshot is None:
            self._list_warning = "；".join(warnings)
        if extra:
            logger.info(f"憨憨保种管理器：另有 {extra} 组未进入站点完成页的下载器未完成任务")
        logger.info(f"憨憨保种管理器：站点 {stats['eligible']} 条 / "
                    f"已关联 {stats['linked']} 条 / 精确 {stats['exact']} 条 / "
                    f"译名 {stats['translated']} 条 / 近似 {stats['similar']} 条 / 未匹配 {stats['unmatched']} 条 / "
                    f"辅种组 {stats['cross_seed']} 条 / 额外辅种任务 {stats['auxiliary_tasks']} 个 / "
                    f"真正歧义 {stats['ambiguous']} 条 / 可人工移除任务 {stats['removable_tasks']} 个 / "
                    f"允许删除文件 {stats['deletable']} 条；总用时 {time.monotonic()-started:.1f}s")
        logger.info(f"憨憨保种管理器：歧义归因（仅计数）："
                    f"多下载任务={stats['ambiguity_multiple_tasks']}、"
                    f"站点同名={stats['ambiguity_duplicate_site_titles']}、"
                    f"近似多重命中={stats['ambiguity_shared_fuzzy']}；"
                    f"跳过下载器重复记录={stats['duplicate_downloader_rows_ignored']}、"
                    f"阻止模糊占用强匹配任务={stats['fuzzy_exact_claims_blocked']}、"
                    f"译名完整后缀匹配={stats['translation_suffix_claims']}")
        return rows

    @staticmethod
    def _append_downloader_incomplete(site_rows: list[dict],
                                      downloader_rows: list[dict]) -> list[dict]:
        """Offer unmatched unfinished downloads as a distinct, non-site inventory.

        Site eligibility is NEVER synthesized. Negative stable IDs distinguish
        this download-client-only group from positive HH completed-page IDs.
        Group only by full normalized task name and two-decimal total GiB;
        do not let a size-only match pull in unrelated files.
        """
        import hashlib
        already = {
            (str(c.get("downloader") or ""), str(c.get("hash") or "").lower())
            for row in site_rows for c in row.get("candidates", [])
        }
        groups = {}
        for task in downloader_rows:
            key = (str(task.get("downloader") or ""),
                   str(task.get("hash") or "").lower())
            if key in already or not key[0] or not key[1]:
                continue
            name = str(task.get("name") or "")
            size = task.get("size_gb")
            progress = task.get("progress")
            try:
                size = float(size)
                progress = float(progress)
            except (ValueError, TypeError):
                continue
            if size <= 0 or not 0 <= progress <= 1:
                continue
            signature = (normalize_name(release_name(name)), round(size, 2))
            if not signature[0]:
                continue
            group = groups.setdefault(signature, [])
            if key not in {(d.get("downloader"), str(d.get("hash") or "").lower())
                           for d in group}:
                group.append(task)

        supplemental = []
        for (normalized, size), candidates in groups.items():
            # Group all exact same-release hashes when at least one has not
            # finished. Other completed siblings are included in the manifest
            # so the user's "remove all cross-seeds" choice remains complete.
            if not any(float(task["progress"]) < 1.0 for task in candidates):
                continue
            # Stable negative JS-safe integer; page fetches can be repeated
            # without reassigning IDs during the same download.
            fingerprint = f"{normalized}\0{size:.2f}".encode("utf-8")
            synthetic = -int.from_bytes(
                hashlib.sha256(fingerprint).digest()[:6], "big") - 1
            source = {
                "title": release_name(candidates[0]["name"]),
                "size": size,
                "seed_id": synthetic,
                "seeders": -1,
                "completed_at": "",
                "qualified": "未完成下载",
                "source": "downloader",
            }
            matched, _ = associate_rescue_seeds([source], candidates)
            entry = matched[0]
            entry["source"] = "downloader"
            entry["qualified"] = "未完成下载"
            entry["match_reason"] = (
                "尚未进入站点完成页的下载器任务；用户主动确认后可清理未完成文件"
                if entry.get("can_delete_group") else
                "下载器未完成任务，因名称/体积/哈希无法确认，暂不允许删除"
            )
            supplemental.append(entry)
        supplemental.sort(key=lambda row: (str(row.get("downloader")),
                                           str(row.get("title"))))
        return site_rows + supplemental

    def _list_rescue_worker(self, generation: int, downloaders: tuple = ()):
        """Update the in-memory snapshot atomically, keeping errors visible."""
        started = time.monotonic()
        try:
            with self._list_lock:
                previous = getattr(self, "_list_snapshot", None)
                snapshot = dict(previous) if downloaders and previous is not None else {}
            covered, full_read = set(), False
            while True:
                seeds = self._collect_rescue_seeds(snapshot=snapshot, refresh_downloaders=downloaders)
                covered.update(downloaders)
                full_read = full_read or not downloaders
                with self._list_lock:
                    if generation != self._list_generation or self._stopped:
                        return
                    pending = getattr(self, "_list_requested_clients", set()) - covered
                    if getattr(self, "_list_requested_full", False) and not full_read:
                        downloaders = ()
                    elif pending and not full_read:
                        downloaders = tuple(sorted(pending))
                    else:
                        self._list_cache = seeds
                        self._list_snapshot = snapshot
                        self._list_warning = snapshot.get("warning", "")
                        self._list_updated_at = time.time()
                        self._list_finished_at = self._list_updated_at
                        self._list_state = "ready"
                        self._list_error = ""
                        return
        except Exception as e:
            logger.error(f"憨憨保种管理器后台读取失败，耗时 {time.monotonic() - started:.1f}s：{HHClubButler._safe_error(e)}")
            with self._list_lock:
                if generation != self._list_generation or self._stopped:
                    return
                self._list_state = "error"
                self._list_error = ("更新下载器失败，请检查下载器连接后重试" if downloaders else
                                    "读取保种数据失败，请检查站点 Cookie、下载器及插件日志")
                self._list_finished_at = time.time()

    def api_list_rescue_seeds(self, refresh: bool = False, downloaders: str = ""):
        """Immediate status response; expensive I/O is coalesced in one worker."""
        now = time.time()
        clients = ()
        if downloaders:
            try:
                names = json.loads(downloaders)
                if (not isinstance(names, list) or not names or len(names) > 50
                        or any(not isinstance(name, str) or name not in self._downloaders for name in names)):
                    raise ValueError("下载器范围无效")
                clients = tuple(sorted(set(names)))
            except (ValueError, TypeError):
                return {"success": False, "message": "下载器刷新范围无效"}
        with self._list_lock:
            if self._stopped or not self._enabled:
                return {"success": False, "message": "插件未启用"}
            if self._list_state == "loading":
                if refresh:
                    self._list_requested_clients.update(clients)
                    self._list_requested_full = self._list_requested_full or not clients
                return {
                    "success": True, "loading": True,
                    "elapsed_seconds": max(0, int(now - self._list_started_at)),
                    "message": "保种数据正在后台读取"}
            if clients and getattr(self, "_list_snapshot", None) is None:
                return {"success": False, "message": "站点快照尚未就绪，请手动刷新完整列表"}
            if (not refresh and self._list_state == "error"
                    and now - self._list_finished_at < 30):
                return {"success": False, "message": self._list_error}
            if (not refresh and self._list_state == "ready" and self._list_cache is not None
                    and now - self._list_updated_at < self._list_cache_ttl):
                return {"success": True, "loading": False,
                        "data": self._list_cache, "warning": self._list_warning,
                        "updated_at": datetime.fromtimestamp(
                            self._list_updated_at).strftime("%Y-%m-%d %H:%M:%S")}
            self._list_generation += 1
            generation = self._list_generation
            self._list_state = "loading"
            self._list_requested_clients = set(clients)
            self._list_requested_full = not clients
            self._list_started_at = now
            self._list_error = ""
            thread = threading.Thread(
                target=self._list_rescue_worker, args=(generation, clients),
                daemon=True, name="HHClubButler-RescueSnapshot")
            self._list_thread = thread
            try:
                thread.start()
            except Exception as e:
                logger.error(f"启动保种列表后台任务失败：{HHClubButler._safe_error(e)}")
                self._list_state = "error"
                self._list_error = "后台任务启动失败，请检查插件日志"
                self._list_finished_at = time.time()
                return {"success": False, "message": self._list_error}
        return {"success": True, "loading": True, "message": "保种数据正在后台读取"}

    def _get_downloader_detail_map(self, torrents: Optional[list] = None) -> dict:
        out = {}
        svcs = self._get_manage_services()
        if not svcs:
            return out
        sv_types = {}
        for name, sv in svcs.items():
            dl_type = ""
            try:
                dl_type = str(sv.type or sv.config.type or "").lower()
            except Exception:
                pass
            sv_types[name] = dl_type
        if torrents is None:
            torrents = self._fetch_all_downloader_torrents()
        if not torrents:
            return out

        def g(t, *names):
            for n in names:
                try:
                    v = t.get(n) if isinstance(t, dict) else getattr(t, n, None)
                    if v is not None:
                        return v
                except Exception:
                    pass
            return None

        for dl_name, t in torrents:
            try:
                name = g(t, "name") or ""
                if not name:
                    continue
                dl_type = sv_types.get(dl_name, "")
                progress = HHClubButler._get_progress_ratio(t, dl_type)
                if progress is not None and progress < 1.0:
                    continue
                upspeed = g(t, "upspeed", "rateUpload", "upload_speed", "uploadRate") or 0
                dlspeed = g(t, "dlspeed", "rateDownload", "download_speed", "downloadRate") or 0
                eta = g(t, "eta") or 0
                ratio = g(t, "ratio", "uploadRatio")
                path = g(t, "save_path", "downloadDir", "download_dir", "content_path", "path", "dir") or ""
                cur_s = g(t, "num_seeds", "seeds", "seeders", "seederCount", "num_seeders")
                cur_l = g(t, "num_leechs", "leechs", "leechers", "leecherCount", "num_leechers")
                added = g(t, "added_on", "date_added", "dateAdded")
                tracker = ""
                try:
                    tracker = HHClubButler._extract_tracker_text(t, dl_type)
                except Exception:
                    pass
                dom = ""
                m = re.search(r"https?://([^/]+)", tracker or "")
                if m:
                    dom = m.group(1)
                added_str = ""
                try:
                    if added:
                        added = int(added)
                        if added > 1e9:
                            added_str = time.strftime("%Y-%m-%d", time.localtime(added))
                except Exception:
                    pass
                out[HHClubButler._norm_title(name)] = {
                    "upspeed": float(upspeed or 0),
                    "dlspeed": float(dlspeed or 0),
                    "eta": int(eta or 0),
                    "ratio": float(ratio) if ratio is not None else None,
                    "path": str(path or ""),
                    "cur_seeders": int(cur_s) if cur_s is not None else None,
                    "cur_leechers": int(cur_l) if cur_l is not None else None,
                    "tracker": dom,
                    "hash": str(g(t, "hash", "hashString") or ""),
                    "added": added_str,
                    "progress": progress,
                    "downloader": dl_name,
                }
            except Exception:
                continue
        return out

    def api_rescue_panel(self):
        return HTMLResponse(
            content=self._build_rescue_panel_html(),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                     "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"})

    def _build_rescue_panel_html(self) -> str:
        html = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>保种管理器</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI","PingFang SC",Arial,sans-serif;background:var(--bg);color:var(--fg);font-size:12px;height:100vh;height:100dvh;display:flex;flex-direction:column;overflow:hidden}
body[data-theme="light"]{--bg:#ffffff;--fg:#1d1d1f;--topbar:#f5f5f7;--border:#e5e5ea;--chip:#e8e8ed;--chip-active:#0071e3;--chip-hover:#d1d1d6;--input-bg:#ffffff;--input-border:#d2d2d7;--btn:#0071e3;--btn-danger:#ff3b30;--btn-ghost:#e8e8ed;--toolbar:#f0f0f2;--picker-bg:#ffffff;--picker-border:#d2d2d7;--th:#f5f5f7;--th-hover:#e8e8ed;--td-border:#f0f0f2;--tr-hover:#f0f5ff;--tr-sel:#0071e3;--footer:#f5f5f7;--footer-border:#e5e5ea;--muted:#86868b;--muted2:#6e6e73}
body[data-theme="cream"]{--bg:#fdf6e3;--fg:#3e2f1c;--topbar:#f5e6c8;--border:#d4c5a0;--chip:#ead9b8;--chip-active:#b8860b;--chip-hover:#e0cf9f;--input-bg:#fff8e0;--input-border:#c4b080;--btn:#b8860b;--btn-danger:#c0392b;--btn-ghost:#ead9b8;--toolbar:#f0e0bc;--picker-bg:#fdf6e3;--picker-border:#c4b080;--th:#f0e0bc;--th-hover:#e8d5a0;--td-border:#e0d0a5;--tr-hover:#f5e6b8;--tr-sel:#8b6914;--footer:#e8d8a8;--footer-border:#d4c5a0;--muted:#8b7355;--muted2:#6b5535}
body[data-theme="sakura"]{--bg:#fff5f7;--fg:#4a2a35;--topbar:#ffe4ec;--border:#f8c8d8;--chip:#ffd6e5;--chip-active:#e91e63;--chip-hover:#ffc2d6;--input-bg:#ffffff;--input-border:#f8b8cc;--btn:#e91e63;--btn-danger:#c0392b;--btn-ghost:#ffd6e5;--toolbar:#ffe0ec;--picker-bg:#fff5f7;--picker-border:#f8b8cc;--th:#ffe0ec;--th-hover:#ffd0e0;--td-border:#f8d0dc;--tr-hover:#ffe4ef;--tr-sel:#ad1457;--footer:#ffe4ec;--footer-border:#f8c8d8;--muted:#a06878;--muted2:#804858}
body[data-theme="mint"]{--bg:#f0faf4;--fg:#1f3a2e;--topbar:#d8f0e2;--border:#b8dcc4;--chip:#c8ecd4;--chip-active:#10b981;--chip-hover:#b0e4c2;--input-bg:#ffffff;--input-border:#a8d4b8;--btn:#10b981;--btn-danger:#e53e3e;--btn-ghost:#c8ecd4;--toolbar:#e0f2e8;--picker-bg:#f0faf4;--picker-border:#a8d4b8;--th:#e0f2e8;--th-hover:#d0ead8;--td-border:#d8ecd0;--tr-hover:#e0f5e8;--tr-sel:#059669;--footer:#e0f2e8;--footer-border:#b8dcc4;--muted:#6a9a7e;--muted2:#4a7a5e}
body[data-theme="sky"]{--bg:#f0f7ff;--fg:#1a2a3e;--topbar:#dceafd;--border:#b8d4f0;--chip:#cce4fa;--chip-active:#0ea5e9;--chip-hover:#b8d8f5;--input-bg:#ffffff;--input-border:#a8c8ee;--btn:#0ea5e9;--btn-danger:#e53e3e;--btn-ghost:#cce4fa;--toolbar:#e0eefd;--picker-bg:#f0f7ff;--picker-border:#a8c8ee;--th:#e0eefd;--th-hover:#d0e6f8;--td-border:#d8e8f8;--tr-hover:#e0f0ff;--tr-sel:#0284c7;--footer:#e0eefd;--footer-border:#b8d4f0;--muted:#6a8aaa;--muted2:#4a6a8a}
body[data-theme="lavender"]{--bg:#f6f3ff;--fg:#2e1f4a;--topbar:#e8e0fb;--border:#ccbfe8;--chip:#ddd2f5;--chip-active:#8b5cf6;--chip-hover:#cdbef0;--input-bg:#ffffff;--input-border:#bcade0;--btn:#8b5cf6;--btn-danger:#e53e3e;--btn-ghost:#ddd2f5;--toolbar:#ece6fb;--picker-bg:#f6f3ff;--picker-border:#bcade0;--th:#ece6fb;--th-hover:#e0d6f5;--td-border:#e0d8f0;--tr-hover:#ece4ff;--tr-sel:#7c3aed;--footer:#ece6fb;--footer-border:#ccbfe8;--muted:#8a7aaa;--muted2:#6a5a8a}
body[data-theme="silver"]{--bg:#eef0f2;--fg:#2a2d32;--topbar:#dde1e6;--border:#c0c5cc;--chip:#d4d8dd;--chip-active:#6b7280;--chip-hover:#c8ccd2;--input-bg:#ffffff;--input-border:#b8bdc4;--btn:#6b7280;--btn-danger:#d97706;--btn-ghost:#d4d8dd;--toolbar:#e4e7eb;--picker-bg:#eef0f2;--picker-border:#b8bdc4;--th:#e4e7eb;--th-hover:#d8dce0;--td-border:#dde1e6;--tr-hover:#e2e6ea;--tr-sel:#4b5563;--footer:#dde1e6;--footer-border:#c0c5cc;--muted:#7a8088;--muted2:#5a6068}
body[data-theme="dark"]{--bg:#1e1e1e;--fg:#d4d4d4;--topbar:#252526;--border:#000;--chip:#3a3d41;--chip-active:#0e639c;--chip-hover:#494c50;--input-bg:#3c3c3c;--input-border:#555;--btn:#0e639c;--btn-danger:#c72e2e;--btn-ghost:#3a3d41;--toolbar:#2d2d30;--picker-bg:#252526;--picker-border:#555;--th:#2d2d30;--th-hover:#37373d;--td-border:#333;--tr-hover:#2a2d2e;--tr-sel:#094771;--footer:#000;--footer-border:#000;--muted:#888;--muted2:#aaa}
body[data-theme="graphite"]{--bg:#2c2c2e;--fg:#e5e5e7;--topbar:#1c1c1e;--border:#0a0a0a;--chip:#3a3a3c;--chip-active:#64d2ff;--chip-hover:#48484a;--input-bg:#1c1c1e;--input-border:#48484a;--btn:#64d2ff;--btn-danger:#ff453a;--btn-ghost:#3a3a3c;--toolbar:#1c1c1e;--picker-bg:#2c2c2e;--picker-border:#48484a;--th:#1c1c1e;--th-hover:#3a3a3c;--td-border:#38383a;--tr-hover:#3a3a3c;--tr-sel:#0a84ff;--footer:#000;--footer-border:#000;--muted:#8e8e93;--muted2:#aeaeb2}
body[data-theme="midnight"]{--bg:#191923;--fg:#e0e0ec;--topbar:#10101a;--border:#050508;--chip:#2a2a38;--chip-active:#5e5ce6;--chip-hover:#35354a;--input-bg:#10101a;--input-border:#3a3a4e;--btn:#5e5ce6;--btn-danger:#ff453a;--btn-ghost:#2a2a38;--toolbar:#14141e;--picker-bg:#191923;--picker-border:#3a3a4e;--th:#14141e;--th-hover:#20202e;--td-border:#252535;--tr-hover:#22222e;--tr-sel:#4846c9;--footer:#050508;--footer-border:#000;--muted:#6a6a8a;--muted2:#9a9ab8}
body[data-theme="navy"]{--bg:#0d1b2a;--fg:#c8d6e5;--topbar:#1b263b;--border:#0a1520;--chip:#2c3e5d;--chip-active:#4fc3f7;--chip-hover:#34496b;--input-bg:#1b263b;--input-border:#34496b;--btn:#4fc3f7;--btn-danger:#e74c3c;--btn-ghost:#2c3e5d;--toolbar:#162235;--picker-bg:#0d1b2a;--picker-border:#34496b;--th:#162235;--th-hover:#1f2f4a;--td-border:#1f2d42;--tr-hover:#1a2a42;--tr-sel:#2a6fa0;--footer:#0a1520;--footer-border:#000;--muted:#6a8aa8;--muted2:#8aa8c8}
body[data-theme="plum"]{--bg:#1a0f1f;--fg:#e0c8e8;--topbar:#2a1530;--border:#100a15;--chip:#3a2045;--chip-active:#ce93d8;--chip-hover:#452850;--input-bg:#2a1530;--input-border:#452850;--btn:#ce93d8;--btn-danger:#ef5350;--btn-ghost:#3a2045;--toolbar:#22122a;--picker-bg:#1a0f1f;--picker-border:#452850;--th:#22122a;--th-hover:#2e1838;--td-border:#2e1838;--tr-hover:#2a1830;--tr-sel:#7b1fa2;--footer:#100a15;--footer-border:#000;--muted:#8a6a9a;--muted2:#b090c0}
body[data-theme="charcoal"]{--bg:#23201e;--fg:#e0dcd6;--topbar:#1a1715;--border:#0a0806;--chip:#3a3532;--chip-active:#d4a574;--chip-hover:#45403c;--input-bg:#1a1715;--input-border:#4a4440;--btn:#d4a574;--btn-danger:#e74c3c;--btn-ghost:#3a3532;--toolbar:#1e1a18;--picker-bg:#23201e;--picker-border:#4a4440;--th:#1e1a18;--th-hover:#2a2522;--td-border:#33302c;--tr-hover:#2a2624;--tr-sel:#8a6a44;--footer:#0a0806;--footer-border:#000;--muted:#8a8078;--muted2:#aaa098}
body[data-theme="forest"]{--bg:#0f1f17;--fg:#c8e0d0;--topbar:#162a1f;--border:#0a1510;--chip:#1f3a2a;--chip-active:#66bb6a;--chip-hover:#2a4a35;--input-bg:#162a1f;--input-border:#2a4a35;--btn:#66bb6a;--btn-danger:#ef5350;--btn-ghost:#1f3a2a;--toolbar:#122519;--picker-bg:#0f1f17;--picker-border:#2a4a35;--th:#122519;--th-hover:#1a3525;--td-border:#1a3020;--tr-hover:#1a2e20;--tr-sel:#2e7d32;--footer:#0a1510;--footer-border:#000;--muted:#5a8a6a;--muted2:#8ab89a}
body[data-theme="hc"]{--bg:#000000;--fg:#ffffff;--topbar:#1a1a1a;--border:#404040;--chip:#2a2a2a;--chip-active:#00ffff;--chip-hover:#3a3a3a;--input-bg:#000;--input-border:#888;--btn:#00ffff;--btn-danger:#ff0000;--btn-ghost:#2a2a2a;--toolbar:#1a1a1a;--picker-bg:#000;--picker-border:#888;--th:#1a1a1a;--th-hover:#2a2a2a;--td-border:#333;--tr-hover:#1a1a1a;--tr-sel:#006666;--footer:#000;--footer-border:#404040;--muted:#aaaaaa;--muted2:#cccccc}
.topbar{background:var(--topbar);padding:8px 12px;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border);flex-wrap:wrap;position:relative}
.dot{display:inline-block;width:8px;height:8px;border-radius:0;margin-right:5px;vertical-align:middle}
.chip b{margin-left:3px}
.topbar h1{font-size:14px;color:var(--fg);margin-right:8px}
.chip{background:var(--chip);padding:3px 10px;border-radius:12px;cursor:pointer;font-size:11px;user-select:none;color:var(--fg)}
.chip.active{background:var(--chip-active);color:#fff}
.chip:hover{background:var(--chip-hover)}
.search{margin-left:auto;background:var(--input-bg);border:1px solid var(--input-border);color:var(--fg);padding:5px 10px;border-radius:3px;width:600px;max-width:40vw}
.btn{background:var(--btn);color:#fff;border:none;padding:5px 12px;border-radius:3px;cursor:pointer;font-size:12px}
.btn.danger{background:var(--btn-danger)}
.btn.ghost{background:var(--btn-ghost);color:var(--fg)}
.toolbar2{background:var(--toolbar);padding:6px 12px;display:flex;gap:6px;border-bottom:1px solid var(--border);align-items:center;position:relative;flex-wrap:wrap}
.colpicker{position:absolute;right:12px;top:50px;background:var(--picker-bg);border:1px solid var(--picker-border);border-radius:4px;padding:8px;z-index:100;min-width:160px;display:none;box-shadow:0 4px 16px rgba(0,0,0,0.5);max-height:70vh;overflow:auto}
.colpicker.show{display:block}
.colpicker h4{font-size:11px;color:var(--muted2);margin-bottom:6px;font-weight:normal}
.colpicker label{display:flex;align-items:center;gap:6px;padding:3px 0;cursor:pointer;font-size:12px;color:var(--fg)}
.colpicker label:hover{color:var(--fg)}
.table-wrap{flex:1;overflow:auto;position:relative}
.status{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;font-size:14px;color:var(--fg);text-align:center;max-width:420px;background:var(--bg);padding:28px 36px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,0.12)}
.status .bar{width:240px;height:4px;background:var(--chip);border-radius:2px;overflow:hidden;position:relative}
.status .bar i{position:absolute;top:0;left:0;height:100%;width:38%;background:var(--btn);border-radius:2px;animation:hhslide 1s linear infinite}
@keyframes hhslide{0%{left:-38%}100%{left:100%}}
.status .errmsg{color:var(--btn-danger);font-size:14px;max-width:70%;text-align:center}
.status .retrybtn{background:var(--btn);color:#fff;border:none;padding:7px 22px;border-radius:4px;cursor:pointer;font-size:14px;margin-top:6px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px;table-layout:fixed}
th,td{padding:6px 10px;border-bottom:1px solid var(--td-border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;position:relative}
th{background:var(--th);color:var(--muted2);text-align:left;font-weight:500;cursor:pointer;user-select:none;position:sticky;top:0;z-index:2}
th:hover{background:var(--th-hover)}
th.sorted{color:var(--muted2)}
th .sortind{margin-left:4px;font-size:10px}
th .resize{position:absolute;right:-3px;top:0;width:9px;height:100%;cursor:col-resize;background:transparent;z-index:3;touch-action:none}
th .resize:hover{background:var(--chip-active)}
tr:hover td{background:var(--tr-hover)}
tr.sel td{background:var(--tr-sel);color:#fff}
.tier0{color:#22c55e;font-weight:600}.tier1{color:#4da3ff;font-weight:600}.tier2{color:#ff6b6b;font-weight:600}
.qual-yes{color:#22c55e}
.match-hint{font-size:10px;color:var(--muted);opacity:.85;margin-left:4px}
.match-unmatched{color:var(--muted)}
.match-ambiguous{color:#e59a32}
.match-exact{color:#22c55e}
.match-similar{color:#5aa9ff}
.match-translated{color:#1cba96;font-weight:600}
.match-cross_seed{color:#bd8fff;font-weight:600}
.hh-copy-list{padding:4px 24px 20px;max-height:50vh;overflow-y:auto;display:grid;gap:8px}
.hh-copy-row{display:flex;align-items:flex-start;gap:10px;padding:12px;border:1px solid var(--input-border);border-radius:8px;cursor:pointer}
.hh-copy-row:has(input:checked){border-color:var(--chip-active);background:var(--chip)}
.hh-copy-row:has(input:disabled){opacity:.50;cursor:not-allowed}
.hh-copy-row input{margin-top:3px;accent-color:var(--chip-active)}
.hh-copy-content{min-width:0;display:flex;flex-direction:column;gap:5px;overflow-wrap:anywhere}
.hh-copy-primary{font-size:13px;font-weight:600}
.hh-copy-secondary{font-size:11px;color:var(--muted2);line-height:1.5}
@media(max-width:720px){.hh-copy-list{padding:4px 14px 16px}}

.right{text-align:right;font-variant-numeric:tabular-nums}
.hide{display:none !important}
.footer{background:var(--footer);padding:6px 14px;font-size:11px;color:var(--muted);border-top:1px solid var(--footer-border);display:flex;gap:18px;flex-wrap:wrap}
.themebtn{background:var(--btn-ghost);color:var(--fg);border:1px solid var(--input-border);padding:3px 10px;border-radius:3px;cursor:pointer;font-size:11px}
.chip .dot{display:inline-block;width:8px;height:8px;border-radius:0;margin-right:4px;vertical-align:middle}
.dlpicker{position:absolute;left:auto;right:0;top:calc(100% + 6px);background:var(--picker-bg);border:1px solid var(--picker-border);border-radius:4px;padding:8px;z-index:100;min-width:190px;display:none;box-shadow:0 4px 16px rgba(0,0,0,0.5);max-height:70vh;overflow:auto}
.dlpicker.show{display:block}
.dlpicker h4{font-size:11px;color:var(--muted2);margin-bottom:6px;font-weight:normal}
.dlpicker .qk{display:flex;gap:6px;margin-bottom:6px}
.dlpicker .qk span{font-size:11px;color:var(--btn);cursor:pointer;border:1px solid var(--input-border);padding:2px 8px;border-radius:3px;user-select:none}
.dlpicker .qk span:hover{background:var(--chip-hover)}
.dlpicker label{display:flex;align-items:center;gap:6px;padding:3px 0;cursor:pointer;font-size:12px;color:var(--fg)}
.dlpicker label:hover{color:var(--fg)}
@media (max-width:720px){
.search{width:100%;max-width:none;margin-left:0;order:99}
.topbar h1{font-size:13px}
.chip{font-size:10px;padding:3px 8px}
.btn{padding:5px 9px}
}

/* V3 confirmation overlay and notices: theme-aware, no native browser dialogs */
.hh-overlay[hidden],.hh-toast[hidden]{display:none !important}
.hh-overlay{position:fixed;inset:0;z-index:1500;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.63);backdrop-filter:blur(5px)}
.hh-dialog{width:min(480px,100%);background:var(--picker-bg);color:var(--fg);border:1px solid var(--input-border);border-radius:14px;box-shadow:0 26px 80px rgba(0,0,0,.45);overflow:hidden}
.hh-dialog-head{padding:22px 24px 8px;display:flex;align-items:center;gap:10px;font-size:17px;font-weight:700}
.hh-warning-icon{width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center;border-radius:10px;background:rgba(239,68,68,.15);color:#ef4444;font-size:22px;flex:none}
.hh-dialog-desc{padding:12px 24px 18px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:42vh;overflow:auto;line-height:1.7;font-size:13px;color:var(--fg)}
.hh-dialog-note{margin:0 24px 20px;padding:11px 12px;border-radius:8px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);color:var(--fg);line-height:1.5}
.hh-dialog-actions{display:flex;justify-content:flex-end;gap:10px;padding:15px 24px 20px;border-top:1px solid var(--border)}
.hh-dialog-actions .btn{padding:9px 16px;border-radius:8px;font-size:13px}
.hh-toast{position:fixed;z-index:1600;right:20px;bottom:20px;min-width:220px;max-width:min(480px,calc(100vw - 40px));background:var(--picker-bg);color:var(--fg);border:1px solid var(--input-border);border-left:4px solid var(--btn);padding:13px 17px;border-radius:9px;box-shadow:0 12px 38px rgba(0,0,0,.30);white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;font-size:13px}
.hh-toast.good{border-left-color:#22c55e}.hh-toast.bad{border-left-color:#ef4444}.hh-toast.warn{border-left-color:#f59e0b}
.btn:disabled{opacity:.55;cursor:not-allowed}
@media(max-width:720px){.hh-overlay{padding:12px}.hh-dialog-head{padding:18px 18px 8px}.hh-dialog-desc{padding:10px 18px 16px}.hh-dialog-note{margin:0 18px 16px}.hh-dialog-actions{padding:12px 18px 18px}}
</style></head><body>
<div class="topbar">
<h1>保种管理器</h1>
<span class="chip active" data-tier="all"><i class="dot" style="background:#9e9e9e"></i>全部 <b id="cnt_all">0</b></span>
<span class="chip" data-tier="incomplete" title="下载器中尚未完成、且没有进入站点完成页的任务"><i class="dot" style="background:#ffb020"></i>下载器未完成 <b id="cnt_incomplete">0</b></span>
<span class="chip" data-tier="0"><i class="dot" style="background:#22c55e"></i>0-1人 <b id="cnt_t0">0</b></span>
<span class="chip" data-tier="1"><i class="dot" style="background:#4da3ff"></i>2-3人 <b id="cnt_t1">0</b></span>
<span class="chip" data-tier="2"><i class="dot" style="background:#ff6b6b"></i>4-5人 <b id="cnt_t2">0</b></span>
<span style="position:relative;display:inline-flex"><button class="btn ghost" id="dlBtn" title="按下载器筛选，可多选">筛选下载器</button>
<div class="dlpicker" id="dlpicker"><h4>按下载器筛选（可多选）</h4>
<div class="qk"><span id="dlAll">全选</span><span id="dlNone">清空</span></div>
<div id="dlList"></div></div></span>
<input class="search" id="q" placeholder="搜索名称...">
<button class="btn ghost" type="button" id="btnRefresh" title="重新从站点和下载器获取最新列表">⟳ 刷新列表</button>
<button class="btn danger" type="button" id="btnDel" title="删除所选站点记录关联的全部辅种任务及文件（执行前需确认）">删除选中</button>
<button class="btn ghost" id="colsBtn">列选择</button>
<select class="themebtn" id="themeSel" title="选择皮肤" style="cursor:pointer;"><option value="light">纯白</option><option value="cream">米黄暖</option><option value="sakura">樱花粉</option><option value="mint">薄荷绿</option><option value="sky">天空蓝</option><option value="lavender">薰衣草紫</option><option value="silver">银灰金属</option><option value="dark">深灰</option><option value="graphite">石墨蓝</option><option value="midnight">午夜蓝</option><option value="navy">深蓝</option><option value="plum">暗紫</option><option value="charcoal">炭灰暖</option><option value="forest">暗夜绿</option><option value="hc">高对比</option></select>
<button class="btn ghost" id="btnExit" title="关闭管理器">退出</button>
<div class="colpicker" id="colpicker"><h4>勾选要显示的列</h4>
<label><input type="checkbox" data-col="c_sid" checked>种子ID</label>
<label><input type="checkbox" data-col="c_name" checked>种子名称</label>
<label><input type="checkbox" data-col="c_size" checked>种子大小</label>
<label><input type="checkbox" data-col="c_init" checked>初始人数</label>
<label><input type="checkbox" data-col="c_now" checked>现在人数</label>
<label><input type="checkbox" data-col="c_tier" checked>档位</label>
<label><input type="checkbox" data-col="c_done_at">完成时间</label>
<label><input type="checkbox" data-col="c_last_settle">上次结算时间</label>
<label><input type="checkbox" data-col="c_today_hours">今日做种时间</label>
<label><input type="checkbox" data-col="c_qualified">今日是否达标</label>
<label><input type="checkbox" data-col="c_dl" checked>下载器</label>
</div>
</div>
<div class="table-wrap"><div id="status" class="status"><span>正在加载保种数据，请稍候…</span><div class="bar"><i></i></div></div><table id="tbl"><thead><tr id="head"></tr></thead><tbody id="tbody"></tbody></table></div>
<div class="footer">
<span>已选 <b id="seln">0</b> 个 / 共 <b id="totaln">0</b> 个</span>
<span>已选体积 <b id="selgb">0</b> GB</span>
<span>总体积 <b id="totalgb">0</b> GB</span>
<span>站点保种资格 <b id="siteCount">0</b> 条 / 下载器未完成 <b id="downloadCount">0</b> 组</span>
<span>下载器已关联 <b id="linkedCount">0</b> 组</span>
<span title="按当前下载器筛选，使用下载器名称与 Hash 去重；同组辅种分别计数。">当前显示 <b id="visibleCount">0</b> 条 / 已确认关联任务 <b id="linkedTaskCount">0</b> 个</span>
<span>译名关联 <b id="translatedCount">0</b> 个</span>
<span>辅种组 <b id="crossSeedGroups">0</b> 个 / 额外任务 <b id="auxiliaryTaskCount">0</b> 个</span>
<span>未关联 <b id="unlinkedCount">0</b> 个</span>
<span>待核对 <b id="verifyCount">0</b> 个</span>
<span title="无站点 ID 的未完成项目来自下载器，不计入站点资格。删除后只更新相关下载器；站点资格通过“刷新列表”更新。">列表：站点资格 + 下载器未完成</span>
</div>
<div class="hh-overlay" id="hhConfirmOverlay" hidden>
  <div class="hh-dialog" role="dialog" aria-modal="true" aria-labelledby="hhConfirmTitle" aria-describedby="hhConfirmDesc">
    <div class="hh-dialog-head"><span class="hh-warning-icon" aria-hidden="true">!</span><span id="hhConfirmTitle">确认删除种子</span></div>
    <div class="hh-dialog-desc" id="hhConfirmDesc"></div>
    <div class="hh-dialog-note">此操作会同时移除下载器任务及相关文件，不能通过插件撤销。</div>
    <div class="hh-dialog-actions">
      <button class="btn ghost" type="button" id="hhCancelDelete">取消</button>
      <button class="btn danger" type="button" id="hhAcceptDelete">确认删除文件</button>
    </div>
  </div>
</div>
<div class="hh-toast" id="hhToast" role="status" aria-live="polite" hidden></div>
<script>
var COLS=[
{k:"c_sid",t:"种子ID",w:"70",r:1,sortk:"seed_id"},
{k:"c_name",t:"种子名称",w:"260",sortk:"title"},
{k:"c_size",t:"种子大小",w:"90",r:1,sortk:"size"},
{k:"c_init",t:"初始人数",w:"70",r:1,sortk:"seeders"},
{k:"c_now",t:"现在人数",w:"70",r:1,sortk:"now_seeders"},
{k:"c_tier",t:"档位",w:"80",sortk:"seeders"},
{k:"c_done_at",t:"完成时间",w:"140",sortk:"completed_at"},
{k:"c_last_settle",t:"上次结算时间",w:"140",sortk:"last_settle"},
{k:"c_today_hours",t:"今日做种时间",w:"90",sortk:"today_hours"},
{k:"c_qualified",t:"今日达标",w:"70",sortk:"qualified"},
{k:"c_dl",t:"下载器",w:"110",sortk:"downloader"}
];
var seeds=[],filtered=[],sel={},dlSel={};
var curTier="all",sortKey="size",sortDir=-1,query="";
function tierOf(n){n=+n||0;return n<0?-1:(n<=1?0:(n<=3?1:2))}
function selectedKey(seed){return String(seed.seed_id!=null?seed.seed_id:seed.title)}
function fmtSize(gb){if(!isFinite(gb))return "-";gb=+gb;if(gb>=1024)return(gb/1024).toFixed(2)+" TB";return gb.toFixed(2)+" GB"}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function buildHead(){
var h='<th style="width:28px;"><input type="checkbox" id="chkAll"></th>';
for(var i=0;i<COLS.length;i++){var c=COLS[i];var hide=c.visible===false?" hide":"";
var ind="";if(sortKey===c.sortk)ind=sortDir<0?" \u25BC":" \u25B2";
h+='<th class="'+(c.r?"right ":"")+(sortKey===c.sortk?" sorted":"")+hide+'" data-col="'+c.k+'" data-sortk="'+c.sortk+'" style="width:'+c.w+'px;">'+c.t+'<span class="sortind">'+ind+'</span><span class="resize"></span></th>';}
h+='<th style="width:60px;">操作</th>';
document.getElementById("head").innerHTML=h;bindHead();
}
function bindHead(){
var dragMoved=false;
document.querySelectorAll("th .resize").forEach(function(hd){hd.onmousedown=function(e){e.preventDefault();e.stopPropagation();
var th=hd.parentElement,sx=e.clientX,sw=th.offsetWidth;dragMoved=false;document.body.style.cursor='col-resize';
function mv(ev){var dx=ev.clientX-sx;if(Math.abs(dx)>1)dragMoved=true;var w=Math.max(40,sw+dx);th.style.width=w+"px";var col=th.dataset.col;if(col)document.querySelectorAll('td[data-col="'+col+'"]').forEach(function(td){td.style.width=w+"px"})}
function up(ev){document.removeEventListener("mousemove",mv);document.removeEventListener("mouseup",up);document.body.style.cursor='';if(dragMoved&&ev){ev.stopPropagation();ev.preventDefault()}}
document.addEventListener("mousemove",mv);document.addEventListener("mouseup",up)};
hd.ontouchstart=function(e){e.preventDefault();e.stopPropagation();
var th=hd.parentElement,sx=e.touches[0].clientX,sw=th.offsetWidth;dragMoved=false;document.body.style.cursor='col-resize';
function tmv(ev){var dx=ev.touches[0].clientX-sx;if(Math.abs(dx)>1)dragMoved=true;var w=Math.max(40,sw+dx);th.style.width=w+"px";var col=th.dataset.col;if(col)document.querySelectorAll('td[data-col="'+col+'"]').forEach(function(td){td.style.width=w+"px"})}
function tup(ev){document.removeEventListener("touchmove",tmv);document.removeEventListener("touchend",tup);document.body.style.cursor='';if(dragMoved&&ev){ev.stopPropagation();ev.preventDefault()}}
document.addEventListener("touchmove",tmv);document.addEventListener("touchend",tup)}});
document.querySelectorAll("th[data-sortk]").forEach(function(th){th.onclick=function(ev){if(dragMoved){dragMoved=false;return}var sk=this.dataset.sortk;if(sortKey===sk){sortDir=-sortDir}else{sortKey=sk;sortDir=-1}doSort();buildHead();render()}});
document.getElementById("chkAll").onchange=function(){var v=this.checked;filtered.forEach(function(s){sel[selectedKey(s)]=v});render()};
}
function doSort(){
seeds.sort(function(a,b){
var va=a[sortKey]||0,vb=b[sortKey]||0;
if(typeof va==="string")return va.localeCompare(vb)*sortDir;
return(va-vb)*sortDir;
});
}
function cellVal(c,s,t){
if(c.k==="c_sid")return s.source==="downloader"?'<span title="未关联站点种子 ID；此记录来自下载器当前任务，不代表种子已删除">—</span>':s.seed_id||"-";
if(c.k==="c_name")return '<span title="'+esc(s.title)+'">'+esc(s.title)+"</span>";
if(c.k==="c_size")return fmtSize(s.size);
if(c.k==="c_init")return s.source==="downloader"?"-":s.seeders;
if(c.k==="c_now")return s.now_seeders!=null?s.now_seeders:"-";
if(c.k==="c_tier")return s.source==="downloader"?
'<span style="color:#ffb020">下载中</span>':
'<span class="'+["tier0","tier1","tier2"][t]+'">'+["0-1人","2-3人","4-5人"][t]+"</span>";
if(c.k==="c_done_at")return esc(s.completed_at||"-");
if(c.k==="c_last_settle")return esc(s.last_settle||"-");
if(c.k==="c_today_hours")return esc(s.today_hours||"-");
if(c.k==="c_qualified"){var q=s.qualified||"";var ok=(q.indexOf("\u5df2\u8fbe")>=0||q==="\u662f"||q==="Y"||q==="\u2713"||q==="\u2714"||q.indexOf("\u2714")>=0||q.indexOf("OK")>=0);return '<span class="'+(ok?"qual-yes":"")+'">'+esc(q||"-")+"</span>";}
if(c.k==="c_dl"){
var names=s.downloaders&&s.downloaders.length?s.downloaders.join(" / "):(s.downloader||"");
if(!names)return '<span class="match-unmatched" title="'+esc(s.match_reason||"下载器未匹配")+'">未匹配</span>';
var kind=s.match_status||"";
var copies=s.cross_seed_count||0;
return '<span title="'+esc(s.match_reason||"")+'">'+esc(names)+'</span>'+
 (copies>1?'<span class="match-hint">辅种 '+copies+' 个</span>':"");
}
return "";
}
function render(){
var dlKeys=Object.keys(dlSel);
var f=seeds.filter(function(s){
if(curTier==="incomplete"&&s.source!=="downloader")return false;
if(curTier!=="all"&&curTier!=="incomplete"&&(s.source==="downloader"||String(tierOf(s.seeders))!==curTier))return false;
if(query&&(s.title||"").toLowerCase().indexOf(query)<0)return false;
if(dlKeys.length&&!(s.downloaders||[s.downloader||""]).some(function(dl){return !!dlSel[dl]}))return false;
return true;});
filtered=f;
var html="";
for(var i=0;i<f.length;i++){var s=f[i];var t=tierOf(s.seeders);var seled=!!sel[selectedKey(s)];
html+='<tr class="'+(seled?"sel":"")+'">';
html+='<td><input type="checkbox" data-idx="'+i+'" '+(seled?"checked":"")+"></td>";
for(var j=0;j<COLS.length;j++){var c=COLS[j];if(c.visible===false)continue;
html+='<td class="'+(c.r?"right ":"")+'" data-col="'+c.k+'">'+cellVal(c,s,t)+"</td>";}
var action=s.can_delete_group
 ?'<a style="color:#ff8080;cursor:pointer;" data-del="'+i+'" title="默认删除全部辅种任务及其数据文件，执行前再次确认">删除'+
 (s.cross_seed_count>1?"全部 "+s.cross_seed_count+" 个":"")+'</a>'
 :'<span style="opacity:.4" title="'+esc(s.match_reason||"无法完整关联全部任务")+'">仅查看</span>';
html+='<td>'+action+'</td></tr>';}
if(!f.length)html='<tr><td colspan="20" style="text-align:center;padding:40px;color:#888">无匹配种子</td></tr>';
document.getElementById("tbody").innerHTML=html;
document.querySelectorAll("#tbody input[type=checkbox]").forEach(function(cb){cb.onchange=function(){var i=+this.dataset.idx;var key=selectedKey(filtered[i]);sel[key]=this.checked;renderFooter()}});
document.querySelectorAll("#tbody [data-del]").forEach(function(a){a.onclick=function(){delOne(filtered[+this.dataset.del])}});
renderFooter();
}
function renderFooter(){
var tasks={};
filtered.forEach(function(s){if(s.match_status==="ambiguous")return;(s.candidates||[]).forEach(function(c){
if(c.hash&&c.downloader&&(!Object.keys(dlSel).length||dlSel[c.downloader])&&
 (c.match_type==="exact"||c.match_type==="translated"))tasks[JSON.stringify([c.downloader,c.hash.toLowerCase()])]=1;
})});
document.getElementById("visibleCount").textContent=filtered.length;
document.getElementById("linkedTaskCount").textContent=Object.keys(tasks).length;
var sn=0,sgb=0;seeds.forEach(function(s){if(sel[selectedKey(s)]){sn++;sgb+=+s.size||0}});
document.getElementById("seln").textContent=sn;document.getElementById("selgb").textContent=sgb.toFixed(1);
document.getElementById("totaln").textContent=seeds.length;document.getElementById("totalgb").textContent=seeds.reduce(function(a,b){return a+(+b.size||0)},0).toFixed(1);
var incompleteGroups=seeds.filter(function(s){return s.source==="downloader"});
document.getElementById("siteCount").textContent=seeds.length-incompleteGroups.length;
document.getElementById("downloadCount").textContent=incompleteGroups.length;
document.getElementById("cnt_incomplete").textContent=incompleteGroups.length;
var linked=seeds.filter(function(s){return !!s.matched}).length;
var needsReview=seeds.filter(function(s){return s.match_status==="ambiguous"||s.match_status==="similar"||s.match_status==="unverified"||s.match_status==="downloading"}).length;
var translated=seeds.filter(function(s){return s.match_status==="translated"}).length;
document.getElementById("linkedCount").textContent=linked;
document.getElementById("translatedCount").textContent=translated;
document.getElementById("crossSeedGroups").textContent=seeds.filter(function(s){return s.match_status==="cross_seed"}).length;
document.getElementById("auxiliaryTaskCount").textContent=seeds.reduce(function(sum,s){return sum+(s.auxiliary_count||0)},0);
document.getElementById("unlinkedCount").textContent=seeds.length-linked;
document.getElementById("verifyCount").textContent=needsReview;
var c0=0,c1=0,c2=0;seeds.forEach(function(s){var t=tierOf(s.seeders);if(t===0)c0++;else if(t===1)c1++;else if(t===2)c2++});
document.getElementById("cnt_all").textContent=seeds.length;
document.getElementById("cnt_t0").textContent=c0;document.getElementById("cnt_t1").textContent=c1;document.getElementById("cnt_t2").textContent=c2;
}
function updateDlBtn(){var n=Object.keys(dlSel).length;document.getElementById("dlBtn").textContent=n?"筛选下载器("+n+")":"筛选下载器";}
function buildDlList(all){
var names={};
seeds.forEach(function(s){(s.downloaders||[s.downloader||""]).forEach(function(d){if(d)names[d]=1})});
var list=Object.keys(names).sort();
if(all){dlSel={};list.forEach(function(n){dlSel[n]=true})}
var h='';
for(var i=0;i<list.length;i++){var n=list[i];h+='<label><input type="checkbox" data-dl="'+esc(n)+'"'+(dlSel[n]?' checked':'')+'>'+esc(n)+'</label>';}
document.getElementById("dlList").innerHTML=h||'<div style="font-size:11px;color:#888;padding:4px 0">暂无下载器数据</div>';
document.querySelectorAll("#dlList input[type=checkbox]").forEach(function(cb){cb.onchange=function(){var n=cb.dataset.dl;if(cb.checked)dlSel[n]=true;else delete dlSel[n];updateDlBtn();render()}});
updateDlBtn();
}
var activeLoadId=0;
async function load(force,downloaders){
var token=++activeLoadId;
var st=document.getElementById("status"),started=Date.now();
st.style.display="flex";
st.innerHTML='<span>'+(downloaders&&downloaders.length?'正在更新下载器 '+esc(downloaders.join(' / ')):'正在获取保种数据')+'… <b id="el">0</b> 秒</span><div class="bar"><i></i></div>';
function elapsed(){return Math.floor((Date.now()-started)/1000)}
var ticker=setInterval(function(){
if(token!==activeLoadId)return;
var el=document.getElementById("el");if(el)el.textContent=elapsed();
},250);
function showErr(msg){
st.innerHTML='<span class="errmsg">'+esc(msg)+'</span><button class="retrybtn" id="retryLoad">重试</button>';
document.getElementById("retryLoad").onclick=function(){return load(true,downloaders)};
}
try{
while(token===activeLoadId){
var ctl=(typeof AbortController!=="undefined")?new AbortController():null;
var timeout=ctl?setTimeout(function(){ctl.abort()},15000):null;
try{
var url="/api/v1/plugin/HHClubButler/list_rescue_seeds"+(force?"?refresh=1":"");
if(downloaders&&downloaders.length)url+=(force?"&":"?")+"downloaders="+encodeURIComponent(JSON.stringify(downloaders));
force=false;
var r=await fetch(url,ctl?{signal:ctl.signal,credentials:"same-origin",cache:"no-store"}:{credentials:"same-origin",cache:"no-store"});
if(!r.ok)throw Error("HTTP "+r.status);
var j=await r.json();
if(token!==activeLoadId)return;
if(!j.success){showErr(j.message||"数据加载失败");return;}
if(j.loading){
if(elapsed()>480){showErr("保种数据获取时间过长，请检查 MoviePilot 日志后重试；后台任务可能仍在运行");return;}
await new Promise(function(resolve){setTimeout(resolve,Math.max(2000,(j.retry_after_seconds||3)*1000));});
continue;
}
seeds=j.data||[];doSort();buildDlList();render();
st.style.display="none";
if(j.warning)showToast("站点可保种列表已加载，但下载器关联可能不全："+j.warning,"warn",12000);
return;
}catch(e){
if(token!==activeLoadId)return;
showErr((e&&e.name==="AbortError")?"接口响应超时，请检查 MoviePilot 服务":"请求失败："+e);
return;
}finally{if(timeout)clearTimeout(timeout);}
}
}finally{clearInterval(ticker);}
}
var deletionBusy=false,toastTimer=null,dialogResolve=null;
var pendingKey="hhclubbutler_delete_pending_v1";
function showToast(message,kind,duration){
var box=document.getElementById("hhToast");
box.textContent=String(message||"");
box.className="hh-toast "+(kind||"info");
box.hidden=false;
if(toastTimer)clearTimeout(toastTimer);
if(duration!==0)toastTimer=setTimeout(function(){box.hidden=true;},duration||7500);
}
function savePending(item){
try{sessionStorage.setItem(pendingKey,JSON.stringify(item))}catch(e){}
}
function readPending(){
try{return JSON.parse(sessionStorage.getItem(pendingKey)||"null")}catch(e){return null}
}
function clearPending(){
try{sessionStorage.removeItem(pendingKey)}catch(e){}
}
function toggleDeletionBusy(busy){
deletionBusy=!!busy;
document.getElementById("btnDel").disabled=deletionBusy;
document.getElementById("hhAcceptDelete").disabled=deletionBusy;
}
function openDeleteDialog(items){
return new Promise(function(resolve){
if(dialogResolve){resolve(false);return;}
var overlay=document.getElementById("hhConfirmOverlay");
var total=items.reduce(function(n,s){return n+(s.targets||[]).length},0);
var clients={};
items.forEach(function(s){(s.targets||[]).forEach(function(t){
clients[t.downloader]=(clients[t.downloader]||0)+1;
})});
var names=Object.keys(clients).sort().map(function(k){return k+": "+clients[k]+" 个任务"}).join("；");
document.getElementById("hhConfirmTitle").textContent="确认删除全部辅种及文件";
document.getElementById("hhConfirmDesc").textContent=
"选中记录："+items.length+" 组\n关联下载器任务："+total+" 个\n"+
"下载器："+names+"\n"+
(items.length===1?"发布名："+items[0].title+"\n":"")+
"模式：全部移除任务，并删除各任务关联的数据文件。";
overlay.querySelector(".hh-dialog-note").textContent=
"高风险操作，不可撤销！所有关联的辅种任务和数据文件都会删除，可能影响其它站点的做种或硬链接以外的共享路径。"+
"执行前后台还会重新核对全部 Hash，若清单变化则取消，不会自动扩大删除范围。";
document.getElementById("hhAcceptDelete").textContent=
"确认删除 "+total+" 个任务及其文件";
dialogResolve=resolve;overlay.hidden=false;
document.getElementById("hhCancelDelete").focus();
});
}
function closeDeleteDialog(accepted){
if(!dialogResolve)return;
var resolve=dialogResolve;dialogResolve=null;
document.getElementById("hhConfirmOverlay").hidden=true;
resolve(!!accepted);
}
document.getElementById("hhCancelDelete").onclick=function(){closeDeleteDialog(false)};
document.getElementById("hhAcceptDelete").onclick=function(){closeDeleteDialog(true)};
document.getElementById("hhConfirmOverlay").onclick=function(e){
if(e.target===this)closeDeleteDialog(false);
};
document.addEventListener("keydown",function(e){
if(e.key==="Escape"&&dialogResolve){e.preventDefault();closeDeleteDialog(false)}
});
function createRequestId(){
if(window.crypto&&window.crypto.randomUUID)return window.crypto.randomUUID();
return Date.now().toString(36)+"-"+Math.random().toString(36).slice(2)+Math.random().toString(36).slice(2);
}
async function fetchJson(url,opts){
var ctl=typeof AbortController!=="undefined"?new AbortController():null;
var timer=ctl?setTimeout(function(){ctl.abort()},12000):null;
try{
var options=Object.assign({credentials:"same-origin",cache:"no-store"},opts||{});
if(ctl)options.signal=ctl.signal;
var response=await fetch(url,options);
if(!response.ok)throw new Error("HTTP "+response.status);
return await response.json();
}finally{if(timer)clearTimeout(timer);}
}
async function pollDeleteStatus(id){
var deadline=Date.now()+10*60*1000,errors=0,missing=0;
while(Date.now()<deadline){
try{
var payload=await fetchJson("/api/v1/plugin/HHClubButler/delete_rescue_status?request_id="+encodeURIComponent(id));
if(!payload.success){
if(++missing<3){await new Promise(function(r){setTimeout(r,2000)});continue;}
return {status:"unknown",message:payload.message||"未找到删除任务"};
}
var job=payload.data||{},state=job.status||"unknown";
if(state==="verified"||state==="failed"||state==="uncertain"||state==="resolved")return job;
if(state!=="running"&&state!=="queued")return {status:"unknown",message:"未知任务状态"};
errors=0;missing=0;
showToast("辅种删除执行中（"+Math.floor(job.elapsed_seconds||0)+" 秒）"+
"\n已核对移除："+(job.removed_count||0)+"/"+(job.total_count||0)+
"\n"+(job.title||"")+"\n请勿重复提交","info",0);
await new Promise(function(r){setTimeout(r,2500)});
}catch(e){
if(++errors>=3)return {status:"unknown",message:"状态查询中断："+e};
await new Promise(function(r){setTimeout(r,2500)});
}
}
return {status:"unknown",message:"等待任务结果超时；任务可能仍在后台运行"};
}
function groupFromSeed(seed){
var candidates=seed.candidates||[];
if(!seed.can_delete_group||!candidates.length)return null;
var targets=candidates.map(function(c){return {downloader:c.downloader,hash:c.hash}});
if(targets.some(function(t){return !t.downloader||!t.hash}))return null;
return {title:seed.title,seed_id:seed.seed_id,targets:targets,delete_file:true};
}
function forgetVerifiedItem(item){
delete sel[selectedKey(item)];
var row=seeds.find(function(s){return selectedKey(s)===selectedKey(item)});
if(row){
if(row.source==="downloader"){
seeds=seeds.filter(function(s){return s!==row});
}else{
row.candidates=[];row.cross_seed_count=0;row.auxiliary_count=0;
row.can_manage=false;row.can_delete=false;row.can_delete_group=false;
row.hash="";row.matched=false;row.match_status="unmatched";
row.match_reason="已确认移除关联任务；站点资格记录仍保留";
row.downloader="";row.downloaders=[];
}
}
doSort();buildDlList();render();
}
function refreshDownloaders(items){
var clients=[];
items.forEach(function(item){(item.targets||[]).forEach(function(t){
if(t.downloader&&clients.indexOf(t.downloader)<0)clients.push(t.downloader);
})});
return clients.length?load(true,clients):Promise.resolve();
}
async function followDeletion(record,reload){
var result=await pollDeleteStatus(record.id);
if(result.status==="resolved"){
clearPending();showToast(result.message||"旧指令已核对，请刷新剩余任务，磁盘状态需另行确认","warn",12000);
if(reload)await refreshDownloaders([record.item]);return "resolved";
}
if(result.status==="verified"){
forgetVerifiedItem(record.item);clearPending();
showToast("下载器已确认移除全部 "+(result.removed_count||0)+
" 个关联任务，并已收到删除文件指令。\n"+
"注意：实际磁盘文件是否彻底删除须到下载器/存储端确认。","good",10000);
if(reload)await refreshDownloaders([record.item]);
return "verified";
}
if(result.status==="failed"){
clearPending();
showToast("删除前核验失败："+(result.message||"请检查插件日志")+
"\n未自动重新提交。","bad",12000);
return "failed";
}
savePending(record);
showToast("部分完成或状态未知："+(result.message||"需人工核对")+
"\n已确认任务数："+(result.removed_count||0)+
"/"+(result.total_count||record.item.targets.length)+
"\n请核对下载器和磁盘文件！不会自动重发删除命令。","warn",0);
if(reload)await refreshDownloaders([record.item]);
return "uncertain";
}
async function delOne(seed){
if(deletionBusy)return;
var group=groupFromSeed(seed);
if(!group){
showToast("该记录不能确认全部任务的完整名称、大小或 Hash，拒绝整组删除。","warn",9000);
return;
}
if(!await openDeleteDialog([group]))return;
await doDel([group]);
}
async function delSel(){
if(deletionBusy)return;
var chosen=seeds.filter(function(seed){return !!sel[selectedKey(seed)]});
if(!chosen.length){showToast("请先勾选需要删除的站点或下载器任务。","warn");return;}
var groups=chosen.map(groupFromSeed);
if(groups.some(function(group){return !group})){
showToast("所选记录中存在无法核对全部辅种的任务；请取消这些记录再试。","warn",11000);
return;
}
if(!await openDeleteDialog(groups))return;
await doDel(groups);
}
async function doDel(groups){
if(deletionBusy)return;
if(readPending()){
showToast("上一条删除请求状态尚未核对，请等待或重新打开页面恢复任务状态。","warn",10000);
return;
}
toggleDeletionBusy(true);
var finished=0,stopped=false,attempted=[];
try{
for(var i=0;i<groups.length;i++){
var item=groups[i],record={id:createRequestId(),item:item,started:Date.now()};
savePending(record);
showToast("正在提交第 "+(i+1)+"/"+groups.length+" 组，"+
(item.targets||[]).length+" 个辅种任务及其文件。\n"+
"请求提交结果不明时只查询状态，不重复删除。","info",0);
var submitted=null;
try{
submitted=await fetchJson("/api/v1/plugin/HHClubButler/delete_rescue_group",{
method:"POST",headers:{"Content-Type":"application/json","X-HHClub-Request":"1"},
body:JSON.stringify({
request_id:record.id,seed_id:item.seed_id,title:item.title,
targets:item.targets,confirm:true,delete_file:true
})});
}catch(err){
showToast("HTTP 请求结果未知，正在按原任务编号查询；不会再次提交删除命令。","warn",0);
}
if(submitted&&!submitted.success){
clearPending();
showToast("服务端拒绝删除："+(submitted.message||"未知原因"),"bad",10000);
stopped=true;break;
}
attempted.push(item);
var state=await followDeletion(record,false);
if(state==="verified")finished++;
else{stopped=true;break;}
}
if(finished){
showToast("已确认处理 "+finished+" 组辅种。"+
(stopped?"其他组已停止，需人工核对。":"正在更新相关下载器。"),"good",9000);
}
if(attempted.length)await refreshDownloaders(attempted);
}finally{toggleDeletionBusy(false);}
}
async function resumePendingDelete(){
var record=readPending();
if(!record||!record.id||!record.item)return;
toggleDeletionBusy(true);
showToast("检测到未完成的辅种删除任务，仅恢复状态查询，不会重新发送删除。","info",0);
try{await followDeletion(record,true)}
finally{toggleDeletionBusy(false)}
}
document.getElementById("btnDel").onclick=delSel;
document.getElementById("btnRefresh").onclick=function(){
if(deletionBusy){showToast("请先等待删除任务结果，避免列表与任务状态冲突。","warn");return}
showToast("正在重新获取站点与下载器种子列表…","info",3500);
load(true);
};
document.getElementById("q").oninput=function(){query=this.value.trim().toLowerCase();render()};
document.querySelectorAll(".topbar .chip").forEach(function(c){c.onclick=function(){document.querySelectorAll(".topbar .chip").forEach(function(x){x.classList.remove("active")});this.classList.add("active");curTier=this.dataset.tier;render()}});
var dp=document.getElementById("dlpicker");
document.getElementById("dlBtn").onclick=function(e){e.stopPropagation();buildDlList();dp.classList.toggle("show")};
dp.addEventListener("click",function(e){e.stopPropagation()});
document.addEventListener("click",function(e){if(!dp.contains(e.target))dp.classList.remove("show")});
document.getElementById("dlAll").onclick=function(e){e.stopPropagation();buildDlList(true);render()};
document.getElementById("dlNone").onclick=function(e){e.stopPropagation();dlSel={};buildDlList();render()};
var cp=document.getElementById("colpicker");
var LS_KEY="hhclubbutler_colcfg_v1";
function loadColCfg(){
try{
var raw=localStorage.getItem(LS_KEY);
if(!raw)return;
var cfg=JSON.parse(raw);
if(cfg&&typeof cfg==="object"){
for(var i=0;i<COLS.length;i++){if(cfg[COLS[i].k]!==undefined)COLS[i].visible=cfg[COLS[i].k]}
}
}catch(e){}
}
function saveColCfg(){
try{var cfg={};for(var i=0;i<COLS.length;i++)cfg[COLS[i].k]=COLS[i].visible!==false;localStorage.setItem(LS_KEY,JSON.stringify(cfg))}catch(e){}
}
function syncColChecks(){
cp.querySelectorAll("input[type=checkbox]").forEach(function(cb){
for(var i=0;i<COLS.length;i++){if(COLS[i].k===cb.dataset.col){cb.checked=COLS[i].visible!==false;break}}
});
}
document.getElementById("colsBtn").onclick=function(e){e.stopPropagation();syncColChecks();cp.classList.toggle("show")};
document.addEventListener("click",function(e){if(!cp.contains(e.target))cp.classList.remove("show")});
cp.querySelectorAll("input[type=checkbox]").forEach(function(cb){cb.onchange=function(){var col=cb.dataset.col;var def=null;for(var i=0;i<COLS.length;i++)if(COLS[i].k===col)def=COLS[i];if(def){def.visible=cb.checked;saveColCfg();buildHead();render()}}});
loadColCfg();
var THEME_KEY="hhclubbutler_theme_v1";
function applyTheme(t){document.body.setAttribute("data-theme",t);try{localStorage.setItem(THEME_KEY,t)}catch(e){}}
try{var lt=localStorage.getItem(THEME_KEY);if(lt)applyTheme(lt);else applyTheme("dark");}catch(e){applyTheme("dark");}
var themeSelect=document.getElementById("themeSel");
themeSelect.value=document.body.getAttribute("data-theme")||"dark";
themeSelect.onchange=function(){applyTheme(this.value)};
document.getElementById("btnExit").onclick=function(){try{window.close()}catch(e){}setTimeout(function(){if(!window.closed)showToast("浏览器未能自动关闭窗口，请手动关闭本标签页。","info")},150)};
buildHead();load(false);resumePendingDelete();
</script></body></html>"""
        return html

    @staticmethod
    def _delete_job_view(job: dict) -> dict:
        """Send only a small, safe status payload to an authenticated admin."""
        return {
            "request_id": job["request_id"], "status": job["status"],
            "message": job.get("message", ""), "title": job["title"],
            "elapsed_seconds": max(0, int(time.time() - job["created_at"])),
            "total_count": job.get("total_count", 1),
            "removed_count": job.get("removed_count", 0),
        }

    def _invalidate_rescue_cache(self):
        """Do not show a stale snapshot after a dispatched deletion."""
        with self._list_lock:
            self._list_generation += 1
            self._list_state = "idle"
            self._list_cache = None
            self._list_updated_at = 0.0
            self._list_error = ""
            self._list_warning = ""

    def api_delete_rescue_seed(self, title: str = "", downloader: str = "",
                               torrent_hash: str = "", confirm: bool = False,
                               request_id: str = "", delete_file: bool = True):
        """Quick idempotent admission. Network requests happen in one worker."""
        if not confirm or not all((title, downloader, torrent_hash)):
            return {"success": False, "message": "缺少删除确认或种子标识"}
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", torrent_hash, re.I):
            return {"success": False, "message": "种子 Hash 格式无效"}
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id or ""):
            return {"success": False, "message": "删除请求标识不合法"}
        if not self._enabled or self._stopped:
            return {"success": False, "message": "插件未启用，拒绝删除"}
        if downloader not in self._downloaders:
            return {"success": False, "message": "下载器不属于本插件管理范围"}
        with self._delete_lock:
            existing = self._delete_jobs.get(request_id)
            if existing:
                if (existing["title"], existing["downloader"], existing["torrent_hash"],
                    existing["delete_file"]) != (
                    title, downloader, torrent_hash.lower(), bool(delete_file)):
                    return {"success": False, "message": "同一请求标识不能用于不同种子"}
                return {"success": True, "message": existing["message"],
                        "data": self._delete_job_view(existing)}
            active = self._delete_jobs.get(self._delete_active_id)
            if active and active["status"] in {"queued", "running"}:
                return {"success": False, "message": "其他删除任务仍在执行，请查看状态后再提交"}
            # Bound the in-memory idempotency ledger while retaining active
            # requests; a browser must never silently re-submit after 524.
            if len(self._delete_jobs) >= 100:
                removable = sorted(
                    (item for item in self._delete_jobs.values()
                     if item["status"] not in {"queued", "running"}),
                    key=lambda item: item["created_at"])[:50]
                for item in removable:
                    self._delete_jobs.pop(item["request_id"], None)
            job = {
                "request_id": request_id, "title": title,
                "downloader": downloader, "torrent_hash": torrent_hash.lower(),
                "delete_file": bool(delete_file),
                "status": "queued", "message": "已接收移除任务请求，正在后台核验",
                "created_at": time.time(),
            }
            self._delete_jobs[request_id] = job
            self._delete_active_id = request_id
            generation = self._delete_generation
            worker = threading.Thread(
                target=self._delete_rescue_worker,
                args=(request_id, generation),
                daemon=True, name="HHClubButler-Delete")
            try:
                worker.start()
            except Exception as error:
                logger.error(f"后台删除任务启动失败：{HHClubButler._safe_error(error)}")
                self._delete_jobs.pop(request_id, None)
                self._delete_active_id = None
                return {"success": False, "message": "无法启动后台删除任务，请检查插件日志"}
            return {"success": True, "message": job["message"],
                    "data": self._delete_job_view(job)}

    def _delete_rescue_worker(self, request_id: str, generation: int):
        with self._delete_lock:
            job = self._delete_jobs.get(request_id)
            if not job:
                return
            job["status"] = "running"
            target = (job["title"], job["downloader"], job["torrent_hash"])
        if not self._run_lock.acquire(blocking=False):
            result = {"success": False, "state": "failed",
                      "message": "其他自动优选任务正在运行，未执行删除"}
        else:
            try:
                result = self._delete_rescue_exact(
                    *target, confirm=True, generation=generation,
                    delete_file=job["delete_file"], request_id=request_id)
            except Exception as error:
                logger.error(f"删除后台任务出现未知异常：{HHClubButler._safe_error(error)}")
                # Do not claim a safe retry when an exception may happen
                # after a downloader has already accepted deletion.
                result = {"success": False, "state": "uncertain",
                          "message": "执行结果不确定，勿重复提交，请刷新核对"}
            finally:
                self._run_lock.release()
        status = result.get("state") or ("verified" if result.get("success") else "failed")
        if status in {"verified", "uncertain"}:
            self._invalidate_rescue_cache()
            self._last_overview = None
            self._last_overview_ts = 0.0
        with self._delete_lock:
            job = self._delete_jobs.get(request_id)
            if job:
                job["status"] = status
                job["removed_count"] = 1 if status == "verified" else 0
                job["message"] = str(result.get("message") or "")
                job["finished_at"] = time.time()
            if self._delete_active_id == request_id:
                self._delete_active_id = None

    def api_delete_rescue_status(self, request_id: str = ""):
        """Read-only status: MUST NOT re-issue any downloader request."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id or ""):
            return {"success": False, "message": "删除任务标识不合法"}
        with self._delete_lock:
            job = self._delete_jobs.get(request_id)
            if job is None or job.get("status") == "uncertain":
                try:
                    self._load_delete_guard()
                    if request_id in self._delete_resolved:
                        return {"success": True, "message": "旧指令状态已核对，请刷新核对剩余任务",
                                "data": {"request_id": request_id, "status": "resolved", "title": "",
                                         "message": "已发送指令的 Hash 已消失；未自动执行剩余目标，磁盘状态需另行核对"}}
                    if job is None and request_id in self._delete_guard.values():
                        return {"success": True, "data": {"request_id": request_id, "status": "uncertain",
                                "title": "", "message": "重启前的删除尚待核对，保护已保留，不会重发"}}
                except Exception:
                    return {"success": False, "message": "无法读取持久化删除保护，拒绝恢复写操作"}
            if job is None:
                return {"success": False, "message": "未找到删除任务；状态未知，请刷新列表核对，勿重复提交"}
            return {"success": True, "message": job.get("message", ""),
                    "data": self._delete_job_view(job)}

    def api_delete_rescue_group(self, request: RescueGroupDeleteRequest):
        """Accept an explicitly confirmed all-hashes manifest; return immediately.

        Repeating the same request_id never resubmits deletion, even if the
        HTTP client has timed out or the downloader reported an unknown state.
        """
        title = str(request.title or "").strip()
        request_id = str(request.request_id or "").strip()
        try:
            seed_id = int(request.seed_id)
        except (TypeError, ValueError):
            return {"success": False, "message": "无效站点种子 ID"}
        if (not request.confirm or not request.delete_file or not title or seed_id == 0
                or not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", request_id)):
            return {"success": False, "message": "删除前必须确认站点、任务和文件"}
        if not self._enabled or self._stopped:
            return {"success": False, "message": "插件未启用，拒绝删除"}
        targets = []
        for entry in request.targets:
            client = str(entry.downloader or "").strip()
            infohash = str(entry.hash or "").strip().lower()
            if (client not in self._downloaders
                    or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash)):
                return {"success": False, "message": "包含无效下载器或 Hash"}
            targets.append((client, infohash))
        if not 1 <= len(targets) <= 200 or len(set(targets)) != len(targets):
            return {"success": False, "message": "任务清单为空、重复或超过单组安全上限"}
        canonical = tuple(sorted(targets))
        with self._delete_lock:
            previous = self._delete_jobs.get(request_id)
            if previous:
                if (previous.get("kind") != "group"
                        or previous.get("title") != title
                        or previous.get("seed_id") != seed_id
                        or previous.get("targets") != canonical):
                    return {"success": False, "message": "请求编号已绑定其他删除清单"}
                return {"success": True, "message": previous.get("message", ""),
                        "data": self._delete_job_view(previous)}
            active = self._delete_jobs.get(self._delete_active_id)
            if active and active.get("status") in ("queued", "running"):
                return {"success": False, "message": "其他删除任务正在执行，请等待状态完成"}
            if len(self._delete_jobs) >= 100:
                old = sorted(
                    (x for x in self._delete_jobs.values()
                     if x.get("status") not in ("queued", "running")),
                    key=lambda x: x["created_at"])
                for item in old[:50]:
                    self._delete_jobs.pop(item["request_id"], None)
            job = {
                "kind": "group", "request_id": request_id, "title": title,
                "seed_id": seed_id, "targets": canonical,
                "status": "queued", "message": f"已受理 {len(canonical)} 个辅种及文件的删除核验",
                "created_at": time.time(), "total_count": len(canonical),
                "removed_count": 0, "delete_file": True,
            }
            self._delete_jobs[request_id] = job
            self._delete_active_id = request_id
            generation = self._delete_generation
            try:
                threading.Thread(
                    target=self._delete_rescue_group_worker,
                    args=(request_id, generation),
                    daemon=True, name="HHClubButler-GroupRemove",
                ).start()
            except Exception as e:
                logger.error(f"辅种后台任务启动失败：{HHClubButler._safe_error(e)}")
                self._delete_jobs.pop(request_id, None)
                self._delete_active_id = None
                return {"success": False, "message": "无法启动后台删除，请检查插件日志"}
            return {"success": True, "message": job["message"],
                    "data": self._delete_job_view(job)}

    def _delete_rescue_group_worker(self, request_id: str, generation: int):
        with self._delete_lock:
            job = self._delete_jobs.get(request_id)
            if not job:
                return
            job["status"] = "running"
            seed_id, title, manifest = job["seed_id"], job["title"], job["targets"]
        if not self._run_lock.acquire(blocking=False):
            outcome = {"state": "failed", "message": "其他优选任务正在运行，未执行删除"}
        else:
            try:
                outcome = self._delete_rescue_group(
                    seed_id=seed_id, title=title,
                    targets=manifest, generation=generation, request_id=request_id)
            except Exception as e:
                logger.error(f"辅种删除后台执行异常：{HHClubButler._safe_error(e)}")
                outcome = {"state": "uncertain",
                           "message": "删除状态不确定，不会自动重试，请查看下载器"}
            finally:
                self._run_lock.release()
        if (generation == self._delete_generation
                and (outcome.get("removed_count", 0) or outcome.get("state") in ("uncertain", "verified"))):
            self._invalidate_rescue_cache()
            self._last_overview = None
            self._last_overview_ts = 0.0
        with self._delete_lock:
            item = self._delete_jobs.get(request_id)
            if item:
                item["status"] = outcome.get("state", "uncertain")
                item["message"] = outcome.get("message", "操作完成，请核对")
                item["removed_count"] = outcome.get("removed_count", 0)
                item["finished_at"] = time.time()
            if self._delete_active_id == request_id:
                self._delete_active_id = None

    @staticmethod
    def _torrent_field(t, *keys):
        for key in keys:
            try:
                value = t.get(key) if isinstance(t, dict) else getattr(t, key, None)
                if value is not None:
                    return value
            except Exception:
                continue
        return None

    def _data_paths(self, service, torrent, *, files=True):
        import posixpath
        import ntpath
        get = lambda *keys: self._torrent_field(torrent, *keys)
        base = str(get("save_path", "download_dir", "downloadDir") or "")
        pathmod = ntpath if "\\" in base or re.match(r"^[A-Za-z]:", base) else posixpath
        def canonical(value):
            return pathmod.normcase(pathmod.normpath(value)).replace("\\", "/")
        content = str(get("content_path") or "")
        if not files and content and pathmod.isabs(content):
            return {canonical(content)}
        if not base or not pathmod.isabs(base):
            raise ValueError("无法确认下载数据的绝对路径，拒绝删除文件")
        getter = getattr(service.instance, "get_files", None)
        infohash = str(get("hash", "hashString") or "")
        entries = getter(infohash) if callable(getter) else None
        if not entries:
            raise ValueError("无法读取下载器文件清单，拒绝删除文件")
        paths = set()
        for entry in entries:
            name = self._torrent_field(entry, "name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("下载器文件清单缺少完整名称")
            paths.add(canonical(pathmod.join(base, name)))
        return paths

    @staticmethod
    def _paths_overlap(first, second):
        return any(a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
                   for a in first for b in second)

    def _validate_delete_files(self, services, snapshots, targets):
        wanted = set(targets)
        selected = set()
        for client, remote in snapshots.items():
            for torrent in remote:
                infohash = str(self._torrent_field(torrent, "hash", "hashString") or "").lower()
                if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash, re.I):
                    raise ValueError("下载器任务缺少 Hash，无法检查共享数据")
                if (client, infohash) in wanted:
                    selected.update(self._data_paths(services[client], torrent))
        if not selected:
            raise ValueError("没有可核实的目标文件清单")
        for client, remote in snapshots.items():
            for torrent in remote:
                infohash = str(self._torrent_field(torrent, "hash", "hashString") or "").lower()
                if (client, infohash) in wanted:
                    continue
                content = self._torrent_field(torrent, "content_path")
                base = str(self._torrent_field(torrent, "save_path", "download_dir", "downloadDir") or "")
                # qB content_path is authoritative; TR needs files when its directory overlaps.
                import ntpath
                import posixpath
                pathmod = ntpath if "\\" in base or re.match(r"^[A-Za-z]:", base) else posixpath
                if not content:
                    if not base or not pathmod.isabs(base):
                        raise ValueError("非目标任务缺少绝对路径，无法排除共享数据")
                    normalized_base = pathmod.normcase(pathmod.normpath(base)).replace("\\", "/")
                    if not self._paths_overlap(selected, {normalized_base}):
                        continue
                paths = self._data_paths(services[client], torrent, files=False)
                if self._paths_overlap(selected, paths):
                    raise ValueError(f"下载器 {client} 存在非目标任务共享数据，拒绝删除文件")

    def _load_delete_guard(self):
        if self._delete_guard_loaded:
            return
        path = self.get_data_path() / "pending_deletions.json"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            pending = value.get("pending") if isinstance(value, dict) else None
            resolved = value.get("resolved") if isinstance(value, dict) else None
            if (not isinstance(pending, dict) or not isinstance(resolved, list)
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in pending.items())
                    or any(not isinstance(v, str) for v in resolved)):
                raise ValueError("删除保护记录损坏，拒绝新的删除")
            self._delete_guard = pending
            self._delete_resolved = resolved[-100:]
        self._delete_guard_loaded = True

    def _save_delete_guard(self):
        path = self.get_data_path() / "pending_deletions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"pending": self._delete_guard, "resolved": self._delete_resolved}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _guard_deletion(self, targets, request_id):
        with self._delete_lock:
            self._load_delete_guard()
            keys = [client + "\0" + infohash.lower() for client, infohash in targets]
            if any(key in self._delete_guard for key in keys):
                raise ValueError("同一 Hash 的上次删除结果仍不确定，仅允许刷新核对，禁止重发")
            before = dict(self._delete_guard)
            old_resolved = list(self._delete_resolved)
            self._delete_resolved = [value for value in self._delete_resolved if value != request_id]
            self._delete_guard.update({key: request_id for key in keys})
            try:
                self._save_delete_guard()
            except Exception:
                self._delete_guard = before
                self._delete_resolved = old_resolved
                raise

    def _cancel_delete_reservation(self, targets, request_id):
        with self._delete_lock:
            for client, infohash in targets:
                key = client + "\0" + infohash.lower()
                if self._delete_guard.get(key) == request_id:
                    self._delete_guard.pop(key)
            self._save_delete_guard()

    def _reconcile_delete_guard(self, rows, read_clients):
        with self._delete_lock:
            self._load_delete_guard()
            visible = {str(r.get("downloader")) + "\0" + str(r.get("hash") or "").lower() for r in rows}
            expired = [key for key in self._delete_guard if key.split("\0", 1)[0] in read_clients and key not in visible]
            if expired:
                before = dict(self._delete_guard)
                old_resolved = list(self._delete_resolved)
                requests = {self._delete_guard[key] for key in expired}
                for key in expired:
                    self._delete_guard.pop(key, None)
                for request_id in requests - set(self._delete_guard.values()):
                    if request_id not in self._delete_resolved:
                        self._delete_resolved.append(request_id)
                self._delete_resolved = self._delete_resolved[-100:]
                try:
                    self._save_delete_guard()
                except Exception:
                    self._delete_guard = before
                    self._delete_resolved = old_resolved
                    raise

    def _delete_rescue_group(self, seed_id: int, title: str, targets: tuple,
                             generation: int, request_id: str = "", auto_mode: str = "") -> dict:
        if not self._operation_allowed(generation) or not 1 <= len(targets) <= 200:
            return {"state": "failed", "removed_count": 0, "message": "插件配置已变化或任务清单无效，未执行删除"}
        if (len(set(targets)) != len(targets) or any(client not in self._downloaders
                or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value, re.I) for client, value in targets)):
            return {"state": "failed", "removed_count": 0, "message": "下载器或 Hash 清单无效，未执行删除"}
        removed_count, dispatched = 0, False
        def outcome(state, message):
            return {"state": state, "removed_count": removed_count, "message": message}
        try:
            rows = self._collect_rescue_seeds(strict_downloaders=True)
            eligible = [row for row in rows if str(row.get("seed_id")) == str(seed_id)
                        and normalize_name(row.get("title")) == normalize_name(title)]
            if len(eligible) != 1:
                return outcome("failed", "站点记录发生变化，删除已取消")
            row = eligible[0]
            if (seed_id < 0) != (row.get("source") == "downloader") or not row.get("can_delete_group"):
                return outcome("failed", "记录来源或名称/预计大小/Hash 无法完整核实，拒绝删除")
            manifest = tuple(sorted((str(c.get("downloader") or ""), str(c.get("hash") or "").lower())
                                    for c in row.get("candidates", [])))
            if manifest != tuple(targets):
                return outcome("failed", "辅种 Hash 清单已变化，请刷新重新确认")
            services = self._get_manage_services()
            grouped = {}
            for client, infohash in targets:
                grouped.setdefault(client, []).append(infohash)
            if any(client not in services for client in grouped):
                return outcome("failed", "管理下载器不可用，未执行删除")
            snapshots = {}
            for client, service in services.items():
                remote, error = service.instance.get_torrents()
                if error or remote is None:
                    return outcome("failed", f"下载器 {client} 无法读取最新清单")
                snapshots[client] = list(remote)
                wanted, found = set(grouped.get(client, [])), set()
                for torrent in remote:
                    get = lambda *keys: self._torrent_field(torrent, *keys)
                    infohash = str(get("hash", "hashString") or "").lower()
                    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash, re.I):
                        return outcome("failed", "下载器清单缺少 Hash，拒绝删除")
                    if infohash not in wanted:
                        continue
                    remote_name = str(get("name") or "")
                    if (translated_release_key(remote_name) or normalize_name(remote_name)) != (translated_release_key(title) or normalize_name(title)):
                        return outcome("failed", f"{client} 完整发布名变化，拒绝删除")
                    try:
                        size = float(get("total_size", "totalSize", "size") or 0) / 1073741824
                    except (TypeError, ValueError):
                        size = 0
                    if not translated_size_matches(row, {"size_gb": size}):
                        return outcome("failed", f"{client} 预计总体积变化，拒绝删除")
                    if auto_mode:
                        dl_type = str(getattr(service, "type", ""))
                        completed = self._is_completed(torrent, dl_type)
                        if not is_trusted_hh_tracker(self._extract_tracker_text(torrent, dl_type)):
                            return outcome("failed", "自动删除无法确认站点 Tracker，已取消")
                        if auto_mode == "wash" and not completed:
                            return outcome("failed", "自动换种目标尚未完成，已取消")
                        if auto_mode == "stale":
                            added = get("added_on", "added_date", "date_added", "dateAdded")
                            added = added.timestamp() if hasattr(added, "timestamp") else float(added or 0)
                            if (completed or self._get_progress_ratio(torrent, dl_type) is None
                                    or not added > 0 or self._auto_clean_days <= 0
                                    or time.time() - added < self._auto_clean_days * 86400):
                                return outcome("failed", "自动清理条件已变化，已取消")
                    found.add(infohash)
                if found != wanted:
                    return outcome("failed", f"{client} 的目标 Hash 已变化，拒绝删除")
            self._validate_delete_files(services, snapshots, targets)
            for client, hashes in sorted(grouped.items()):
                if not self._operation_allowed(generation):
                    return outcome("uncertain" if dispatched else "failed", "配置变化已停止后续删除")
                self._guard_deletion([(client, value) for value in hashes], request_id)
                # Persist the target guard before the first one-shot destructive RPC.
                if not self._operation_allowed(generation):
                    self._cancel_delete_reservation([(client, value) for value in hashes], request_id)
                    return outcome("uncertain" if dispatched else "failed", "配置变化，未发送当前下载器的删除指令")
                dispatched = True
                accepted = services[client].instance.delete_torrents(delete_file=True, ids=list(hashes))
                if accepted is False:
                    return outcome("uncertain", f"{client} 未确认指令结果，不会自动重发")
                missing = set()
                client_before = removed_count
                for attempt in range(3):
                    actual, error = services[client].instance.get_torrents()
                    if error or actual is None:
                        return outcome("uncertain", f"{client} 无法回读，文件及任务状态待核对")
                    remaining = set()
                    for torrent in actual:
                        value = self._torrent_field(torrent, "hash", "hashString")
                        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(value or ""), re.I):
                            return outcome("uncertain", f"{client} 回读缺少 Hash，无法确认移除")
                        remaining.add(str(value).lower())
                    missing = set(hashes) - remaining
                    removed_count = client_before + len(missing)
                    if len(missing) == len(hashes):
                        break
                    if attempt < 2:
                        time.sleep(0.5)
                fresh = [{"downloader": client, "hash": value} for value in remaining]
                self._reconcile_delete_guard(fresh, {client})
                if len(missing) != len(hashes):
                    return outcome("uncertain", f"{client} 部分 Hash 仍存在，已确认移除 {removed_count} 个；不会重发")
                if request_id:
                    with self._delete_lock:
                        job = self._delete_jobs.get(request_id)
                        if job:
                            job["removed_count"] = removed_count
                            job["message"] = f"已确认移除 {removed_count}/{len(targets)} 个任务"
            return outcome("verified", f"已确认移除全部 {removed_count} 个任务；删文件指令已发送，磁盘状态需另行核对")
        except Exception as error:
            logger.error(f"辅种删除核验/回读异常：{self._safe_error(error)}")
            return outcome("uncertain" if dispatched else "failed",
                           "命令已发送，结果不确定；禁止重发，请刷新核对" if dispatched else f"删除前核验失败：{self._safe_error(error)}")

    def _delete_rescue_exact(self, title: str = "", downloader: str = "",
                            torrent_hash: str = "", confirm: bool = False,
                            generation: int | None = None,
                            delete_file: bool = True, request_id: str = ""):

        """Remove ONE selected downloader hash after fresh identity checking.

        Multiple same-name infohashes are legitimate cross-seeding.
        The user chooses an exact hash. Shared payloads are never removed
        when multiple tasks are associated with the same site release.
        """
        if not self._enabled or self._stopped:
            return {"success": False, "state": "failed", "message": "插件未启用或正在重载，拒绝删除"}
        if generation is not None and generation != self._delete_generation:
            return {"success": False, "state": "failed", "message": "插件配置已更新，已取消旧删除操作"}
        if not (confirm and title and downloader and torrent_hash):
            return {"success": False, "state": "failed", "message": "必须提供完整标识和删除确认"}
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", torrent_hash, re.I):
            return {"success": False, "state": "failed", "message": "种子 Hash 格式无效"}
        canon = normalize_name(title)
        if not canon or downloader not in self._downloaders:
            return {"success": False, "state": "failed", "message": "下载器或种子名称无效"}
        dispatched = False
        try:
            # The previous response may have been cached for 180 seconds.
            # Require fresh site records and ALL managed downloader snapshots
            # before making a destructive decision.
            # For task-only removal a disconnected *other* client must not
            # block the user; no shared files will be touched. File deletion
            # still requires every selected client to be available.
            current = self._collect_rescue_seeds(strict_downloaders=bool(delete_file))
            candidates = [row for row in current if normalize_name(row.get("title")) == canon]
            if len(candidates) != 1:
                return {"success": False, "state": "failed",
                        "message": "站点记录缺失或重复，无法唯一确认删除对象"}
            row = candidates[0]
            matching_candidates = [
                c for c in row.get("candidates", [])
                if c.get("downloader") == downloader
                and str(c.get("hash") or "").casefold() == torrent_hash.casefold()
            ]
            if len(matching_candidates) != 1 or not matching_candidates[0].get("can_remove"):
                return {"success": False, "state": "failed",
                        "message": "下载器哈希未在可人工管理的关联任务中找到，拒绝操作"}
            chosen = matching_candidates[0]
            if delete_file and not chosen.get("can_delete_files"):
                return {"success": False, "state": "failed",
                        "message": "存在辅种或 Tracker 未确认，禁止同时删除共享视频文件；请仅移除任务"}
            match_type = chosen.get("match_type")
            if match_type not in {"exact", "translated"}:
                return {"success": False, "state": "failed",
                        "message": "只有英文发布名完全对应的任务才可以移除"}
            service = self._get_manage_services().get(downloader)
            if not service:
                return {"success": False, "state": "failed", "message": "指定下载器不可用"}
            torrents, error = service.instance.get_torrents()
            if error or torrents is None:
                return {"success": False, "state": "failed", "message": "下载器任务读取失败，拒绝删除"}
            if delete_file:
                services = self._get_manage_services()
                snapshots = {}
                for client, current_service in services.items():
                    remote, failed = current_service.instance.get_torrents()
                    if failed or remote is None:
                        return {"success": False, "state": "failed", "message": "共享数据核验无法读取全部下载器"}
                    snapshots[client] = list(remote)
                self._validate_delete_files(services, snapshots, [(downloader, torrent_hash.lower())])
            matched_hashes = set()
            for torrent in torrents:
                def g(*keys):
                    for key in keys:
                        val = (torrent.get(key) if isinstance(torrent, dict)
                               else getattr(torrent, key, None))
                        if val is not None:
                            return val
                    return None
                remote_hash = str(g("hash", "hashString") or "").lower()
                if remote_hash != torrent_hash.lower():
                    continue
                remote_name = str(g("name") or "")
                tracker_text = self._extract_tracker_text(torrent)
                if match_type == "translated":
                    if translated_release_key(remote_name) != canon:
                        return {"success": False, "state": "failed",
                                "message": "下载器英文发布名已经变化，拒绝操作"}
                    if delete_file and not is_trusted_hh_tracker(tracker_text):
                        return {"success": False, "state": "failed",
                                "message": "未确认 tracker.hhanclub.net，不允许删除文件"}
                    size_bytes = (g("total_size") or g("totalSize") or g("size"))
                    try:
                        size_gb = float(size_bytes) / 1073741824 if size_bytes else 0
                    except (ValueError, TypeError):
                        size_gb = 0
                    if not translated_size_matches(row, {"size_gb": size_gb}):
                        return {"success": False, "state": "failed",
                                "message": "下载器体积与站点不一致，拒绝删除"}
                else:
                    if self._norm_title(remote_name) != self._norm_title(title):
                        return {"success": False, "state": "failed",
                                "message": "下载器名称发生变化，拒绝操作"}
                    if delete_file and not is_trusted_hh_tracker(tracker_text):
                        return {"success": False, "state": "failed",
                                "message": "未确认 tracker.hhanclub.net，不允许删除文件"}
                try:
                    size_gb = float(g("total_size", "totalSize", "size") or 0) / 1073741824
                except (TypeError, ValueError):
                    size_gb = 0
                if not translated_size_matches(row, {"size_gb": size_gb}):
                    return {"success": False, "state": "failed", "message": "预计总体积无法核实，拒绝删除"}
                matched_hashes.add(remote_hash)
            if len(matched_hashes) != 1:
                return {"success": False, "state": "failed",
                        "message": "下载器未找到唯一核验的种子哈希"}
            matched = [torrent_hash]
            # Do not delete if this plugin was disabled/reloaded while
            # waiting for the site or downloader.
            if self._stopped or (generation is not None and generation != self._delete_generation):
                return {"success": False, "state": "failed", "message": "插件配置已变化，删除已取消"}
            guard_id = request_id or f"single-{time.time_ns()}"
            self._guard_deletion([(downloader, torrent_hash.lower())], guard_id)
            if self._stopped or (generation is not None and generation != self._delete_generation):
                self._cancel_delete_reservation([(downloader, torrent_hash.lower())], guard_id)
                return {"success": False, "state": "failed", "message": "配置变化，未发送删除指令"}
            dispatched = True
            accepted = service.instance.delete_torrents(
                delete_file=bool(delete_file), ids=matched)
            if accepted is False:
                return {"success": False, "state": "uncertain",
                        "message": "下载器未确认删除指令是否执行，请刷新列表核对，不要重复点击"}
            # The downloader APIs return bool for command acceptance, not
            # proof of removal. Verify by checking the exact hash afterward.
            for attempt in range(3):
                try:
                    after, after_error = service.instance.get_torrents()
                except Exception:
                    after, after_error = None, "readback_failed"
                if after_error or after is None:
                    return {"success": False, "state": "uncertain",
                            "message": "删除指令已发送，但无法回读下载器状态；请刷新核对"}
                hashes = []
                for item in after:
                    value = ((item.get("hash") or item.get("hashString")) if isinstance(item, dict)
                             else getattr(item, "hash", None) or getattr(item, "hashString", None))
                    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", str(value or ""), re.I):
                        return {"success": False, "state": "uncertain",
                                "message": "下载器回读结果缺少种子哈希，无法确认删除"}
                    hashes.append(str(value).lower())
                if torrent_hash.lower() not in hashes:
                    self._reconcile_delete_guard(
                        [{"downloader": downloader, "hash": value} for value in hashes], {downloader})
                    logger.info(f"憨憨保种区管家已确认移除：下载器={downloader}，"
                                f"hash={torrent_hash[:8]}…，保留文件={not delete_file}")
                    message = ("已移除所选任务并保留数据文件" if not delete_file
                               else "已移除任务，删除文件指令已发送；磁盘清除需另行核对")
                    return {"success": True, "state": "verified", "message": f"{message}：{title}"}
                if attempt < 2:
                    time.sleep(0.5)
            return {"success": False, "state": "uncertain",
                    "message": "删除请求已发送，但下载器仍返回该种子；请刷新核对"}

        except Exception as e:
            logger.error(f"手动删除种子异常：{self._safe_error(e)}")
            return {"success": False, "state": "uncertain" if dispatched else "failed",
                    "message": "删除指令执行状态不确定，请刷新核对，勿重复删除"
                    if dispatched else "删除前核验失败，未执行删除，请检查插件日志"}

    def run(self):
        # Per-instance atomic admission; one-shot, cron and API cannot run concurrently.
        if not self._run_lock.acquire(blocking=False):
            logger.info("憨憨保种区管家已有任务在运行，跳过重复触发")
            return
        self._running = True
        self._run_generation = self._delete_generation
        try:
            if not self._operation_allowed():
                return
            if self._download_options_error:
                self._last_result = self._download_options_error
                logger.warning(self._last_result)
                return
            cookie = self._get_site_cookie()
            if not cookie:
                self._last_result = "未获取到站点Cookie"
                logger.warning(self._last_result)
                return
            try:
                self._do_run()
            except Exception as e:
                logger.error(f"憨憨保种区管家运行异常：{HHClubButler._safe_error(e)}")
                self._last_result = f"运行异常：{HHClubButler._safe_error(e)}"
                if self._notify:
                    try:
                        self.post_message(mtype=NotificationType.Plugin,
                                          title="【憨憨保种区管家】运行异常", text=self._safe_error(e))
                    except Exception:
                        pass
        finally:
            self._running = False
            self._run_lock.release()

    def _do_run(self):
        logs = []
        logger.info(f"憨憨保种区管家运行开始（代码版本 v{self.plugin_version}）")
        logs.append("=== 憨憨保种区管家保种优选开始 ===")

        seeds = self._fetch_rescue_all(logs)
        if not seeds:
            self._last_result = "保种区未获取到种子（检查Cookie是否有效）"
            logger.warning(self._last_result)
            self._save_log(logs)
            return
        if not self._operation_allowed():
            self._last_result = "配置已变化，停止旧自动任务"
            return
        seeds_full = list(seeds)
        all_site_titles = {normalize_name(release_name(s.get("title"))) for s in seeds}

        if self._exclude_zero:
            before = len(seeds)
            seeds = [s for s in seeds if s.get("seeders", 0) > 0]
            logs.append(f"已排除0做种种子 {before - len(seeds)} 个，剩 {len(seeds)} 个")

        current = self._get_current_seeding(logs)
        if current.get("error") or current.get("degraded"):
            reason = current.get("error") or current.get("degraded")
            msg = f"无法获取完整当前保种情况（{reason}），为防止误推送已停止运行"
            self._last_result = msg
            logger.warning(msg)
            self._save_log(logs)
            return
        current_gb = current.get("total_gb", 0.0)
        logs.append(f"当前保种：{current.get('count', 0)} 个，体积 {current_gb:.1f} GB")

        logger.info(f"自动清理配置：{self._auto_clean_days:g} 天（{'启用' if self._auto_clean_days > 0 else '未启用'}）")
        cleaned = 0
        if self._auto_clean_days > 0:
            cleaned = self._clean_stale_downloads(logs, seeds, all_site_titles)

        dl_all = self._get_downloader_seeds(logs, only_completed=False, any_tracker=True)
        in_flight_gb = 0.0
        if dl_all is None:
            dl_norm_all = set()
            logs.append("下载器种子列表获取失败，本次停止以防重复")
            self._last_result = logs[-1]
            self._save_log(logs)
            return
        else:
            dl_done = self._get_downloader_seeds(logs, only_completed=True, any_tracker=True)
            if dl_done is None:
                self._last_result = "下载器完成状态读取失败，停止本轮"
                self._save_log(logs)
                return
            dl_norm_all = {normalize_name(release_name(n)) for n in dl_all}
            dl_done_norm = {normalize_name(release_name(n)) for n in dl_done}
            in_flight_norms = dl_norm_all - dl_done_norm
            if in_flight_norms:
                gb_map = {}
                for s in seeds_full:
                    gb_map[normalize_name(release_name(s.get("title")))] = s.get("size", 0.0)
                in_flight_gb = sum(gb_map.get(nm, 0.0) for nm in in_flight_norms)
            logs.append(f"在途（下载中未完成）{len(in_flight_norms)} 个，体积 {in_flight_gb:.1f} GB")
            before = len(seeds)
            seeds = [s for s in seeds if normalize_name(release_name(s.get("title"))) not in dl_norm_all]
            removed = before - len(seeds)
            if removed:
                logs.append(f"已剔除 {removed} 个已在下载器中的候选（含下载中），剩 {len(seeds)} 个")

        if self._operation_allowed() and not current.get("degraded"):
            try:
                overview = self._build_overview_from_current(current)
                if self._operation_allowed():
                    self._last_overview = overview
                    self._last_overview_ts = time.time()
            except Exception as e:
                logger.error(f"构建概况缓存失败：{HHClubButler._safe_error(e)}")

        if not self._operation_allowed():
            self._last_result = "配置已变化，停止旧自动任务"
            return
        target = self._target_volume
        committed_gb = current_gb + in_flight_gb
        if target and target > 0:
            if committed_gb >= target - 1e-6 and self._mode != "wash":
                msg = f"当前保种+在途已达标（{committed_gb:.1f} GB ≥ 目标 {target:.0f} GB），本次不推不删"
                logs.append(msg)
                self._last_result = f"已达目标（{committed_gb:.1f}/{target:.0f} GB）"
                logger.info(f"憨憨保种区管家：{msg}")
                self._save_log(logs)
                return
            eff_target = max(0.0, target - committed_gb)
            logs.append(f"目标体积（总保种上限）{target:g}，当前 {current_gb:.1f}，在途 {in_flight_gb:.1f}，"
                        f"剩余可增 {eff_target:.1f} GB")
        else:
            eff_target = 0.0

        if self._seeder_cond:
            rng = HHClubButler._parse_seeder_range(self._seeder_cond)
            if rng is None:
                logs.append(f"做种人数条件无法解析：{self._seeder_cond!r}，按不限处理")
            else:
                before = len(seeds)
                seeds = [s for s in seeds if rng[0] <= s.get("seeders", 0) <= rng[1]]
                logs.append(f"做种人数条件 {rng[0]}~{rng[1]}：候选 {before} → {len(seeds)} 个")

        if self._mode == "wash" and current.get("seeds"):
            result = self._optimize_wash(seeds, current.get("seeds"), eff_target, logs)
        else:
            result = self._optimize_incremental(seeds, eff_target, current_gb, logs)
            result["del_seeds"] = []

        picked = result.get("picked", [])
        if result.get("del_seeds"):
            deletion = self._delete_seeds(result["del_seeds"], logs)
            result["del_seeds"] = deletion["verified"]
            if not deletion["success"]:
                self._last_result = f"换种停止：已核实移除 {deletion['removed_count']} 个任务，未推送依赖释放容量的新种子"
                self._save_log(logs)
                if self._operation_allowed():
                    self._last_overview = None
                    self._last_overview_ts = 0
                return
            for s in result["del_seeds"]:
                logger.info(f"优选删除种子: {s.get('title','')} | {s.get('size',0.0):.1f} GB | "
                            f"初始做种 {s.get('seeders','?')} 人")

        filtered = 0
        if picked and dl_all is not None:
            before = len(picked)
            picked = [s for s in picked if normalize_name(release_name(s["title"])) not in dl_norm_all]
            filtered = before - len(picked)
            if filtered:
                logs.append(f"已过滤 {filtered} 个已在下载器的种子，实际推送 {len(picked)} 个")

        ok_count = fail_count = 0
        fail_list = []
        if picked:
            ok_count, fail_count, fail_list = self._push_seeds(picked, logs)
            failed_names = {failure["title"] for failure in fail_list}
            picked = [s for s in picked if s["title"] not in failed_names]
            for s in picked:
                logger.info(f"优选新增种子: {s.get('title','')} | {s.get('size',0.0):.1f} GB | "
                            f"初始做种 {s.get('seeders','?')} 人")
        else:
            logs.append("无需新增下载")

        if fail_list:
            logs.append(f"❌ 推送失败 {len(fail_list)} 个：")
            for f in fail_list:
                logger.error(f"推送失败种子: {f['title']} | {f['reason']}")
                logs.append(f"   {f['title']}（{f['reason']}）")

        total_gb = sum(s.get("size", 0.0) for s in picked)
        mode_name = "换种" if self._mode == "wash" else "增量"
        summary = (f"{mode_name}已接收下载 {ok_count} 个 | 新增体积 {total_gb:.1f} GB | 失败/未发送 {fail_count} 个")
        if result.get("del_seeds"):
            summary += f" | 删除 {len(result['del_seeds'])} 个"
        logs.append("=== " + summary + " ===")
        self._last_result = summary
        self._save_log(logs)
        logger.info(f"憨憨保种区管家优选完成：{summary}")

        if self._notify:
            try:
                notify = self._build_notify(mode_name, current, target, eff_target, picked, total_gb,
                                            filtered, ok_count, fail_count, fail_list, result, cleaned)
                self.post_message(mtype=NotificationType.Plugin,
                                  title=f"【憨憨保种区管家】{mode_name}优选完成",
                                  text="\n".join(notify))
            except Exception as e:
                logger.error(f"憨憨保种区管家发送通知失败：{HHClubButler._safe_error(e)}")

        del_done = result.get("del_seeds") or []
        if del_done and self._operation_allowed() and not current.get("degraded"):
            del_titles = {s.get("title") for s in del_done}
            remain = [s for s in current.get("seeds", []) if s.get("title") not in del_titles]
            current["seeds"] = remain
            current["count"] = len(remain)
            current["total_gb"] = sum(s.get("size", 0.0) for s in remain)
            try:
                overview = self._build_overview_from_current(current)
                if self._operation_allowed():
                    self._last_overview = overview
                    self._last_overview_ts = time.time()
            except Exception as e:
                logger.error(f"删除后更新概况失败：{HHClubButler._safe_error(e)}")

    def _build_notify(self, mode_name, current, target, eff_target, picked, total_gb,
                      filtered, ok_count, fail_count, fail_list, result, cleaned=0) -> list:
        lines = ["──────────────"]
        # 计算换种/增量后的最终状态
        del_seeds = result.get("del_seeds", []) or []
        del_titles = {s["title"] for s in del_seeds}
        final_seeds = []
        seen = set()
        for s in (current.get("seeds", []) or []):
            if s["title"] not in del_titles and s["title"] not in seen:
                final_seeds.append(s)
                seen.add(s["title"])
        for s in picked:
            if s["title"] not in seen:
                final_seeds.append(s)
                seen.add(s["title"])
        final_count = len(final_seeds)
        final_gb = sum(s.get("size", 0.0) for s in final_seeds)
        lines.append(f"保留保种及已接收下载：{final_count} 个 / {final_gb:.1f} GB（新下载待完成）")
        if target and target > 0:
            remain = max(0.0, target - final_gb)
            lines.append(f"目标体积：{target:.0f} GB（剩余可增 {remain:.1f} GB）")
        else:
            lines.append("目标体积：不限")
        ov = self._last_overview or {}
        dist = {"0-1人": {"count": 0, "gb": 0.0},
                "2-3人": {"count": 0, "gb": 0.0},
                "4-5人": {"count": 0, "gb": 0.0}}
        for s in final_seeds:
            t = tier_of(s.get("seeders", 0))
            if t > 2:
                t = 2
            dist[TIER_NAMES[t]]["count"] += 1
            dist[TIER_NAMES[t]]["gb"] += s.get("size", 0.0)
        if final_seeds:
            lines.append("初始做种人数分布")
            for key in ("0-1人", "2-3人", "4-5人"):
                d = dist.get(key) or {}
                lines.append(f"  {key}  {d.get('count', 0)}个  {d.get('gb', 0.0):.1f} GB")
        last_bean = ov.get("last_bean")
        last_pt = ov.get("last_pt")
        last_date = ov.get("last_date", "") or ""
        if isinstance(last_bean, (int, float)) and isinstance(last_pt, (int, float)):
            seg = f"上次结算：憨豆 {last_bean:.0f}  积分 {last_pt:.0f}"
            if last_date:
                seg += f"（{last_date}）"
            lines.append(seg)
        lines.append("──────────────")
        if picked:
            lines.append(f"新增 {len(picked)} 个种子：+{total_gb:.1f} GB")
            for s in picked[:5]:
                t = (s.get("title") or "").strip()
                t = t if len(t) <= 36 else t[:36] + "…"
                lines.append(f"  · {t}")
            if len(picked) > 5:
                lines.append(f"  …等共 {len(picked)} 个")
            lines.append(f"推送成功：{ok_count}/{ok_count + fail_count}")
        else:
            lines.append("无需新增下载")
            if filtered > 0:
                lines.append(f"已过滤 {filtered} 个已在下载器的种子")
        if fail_count:
            lines.append(f"推送失败/未发送：{fail_count} 个（已接收 {ok_count}）")
        if result.get("del_seeds"):
            lines.append(f"删除低档位种子：{len(result['del_seeds'])} 个")
            for s in result["del_seeds"][:5]:
                t = (s.get("title") or "").strip()
                t = t if len(t) <= 32 else t[:32] + "…"
                lines.append(f"  - {t}（做种{s.get('seeders','?')}人/{s.get('size',0.0):.0f}GB）")
        if cleaned > 0:
            lines.append(f"清理超时未完成：{cleaned} 个")
        return lines

    def _get_mp_site(self):
        try:
            site_oper = SiteOper()
            for site in site_oper.list_active():
                url = site.url or ""
                domain = site.domain or ""
                if "hhanclub" in url.lower() or "hhclub" in url.lower() \
                        or "hhanclub" in domain.lower() or "hhclub" in domain.lower():
                    return site
        except Exception as e:
            logger.error(f"读取MP站点配置失败：{HHClubButler._safe_error(e)}")
        return None

    def _get_site_cookie(self) -> str:
        if not self._cookie:
            site = self._get_mp_site()
            if site and site.cookie:
                self._cookie = site.cookie
                logger.info("已从MP站点管理自动获取憨憨站Cookie")
                return self._cookie
        return self._cookie or ""

    def _get_site_url(self) -> str:
        url = self._site_url
        if not url or url == "https://hhanclub.net":
            site = self._get_mp_site()
            if site and site.url:
                url = site.url.rstrip("/")
        return url

    def _update_cfg(self, **kwargs):
        cfg = self.get_config() or {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg.update(kwargs)
        self.update_config(cfg)

    def _get_site_uid(self) -> Optional[str]:
        if self._uid:
            return self._uid
        try:
            session = self._session()
            r = session.get(self._get_site_url(), timeout=15)
            m = re.search(r"userdetails\.php\?id=(\d+)", r.text)
            if m:
                uid = m.group(1)
                if self._uid != uid:
                    self._uid = uid
                    try:
                        self._update_cfg(uid=uid)
                    except Exception:
                        pass
                logger.info(f"已从站点主页自动获取UID：{uid}")
                return uid
        except Exception as e:
            logger.error(f"自动获取站点UID失败：{HHClubButler._safe_error(e)}")
        logger.warning("未自动获取到站点UID，请检查站点Cookie/UA是否有效")
        return None

    def _session(self) -> requests.Session:
        proxy = settings.PROXY if self._use_proxy else None
        if self._use_proxy and not proxy:
            raise RuntimeError("已开启使用 MP 代理，但 MP 未配置可用代理")
        s = requests.Session()
        s.trust_env = False
        if proxy:
            s.proxies.update(proxy)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        site = self._get_mp_site()
        if site and site.ua:
            headers["User-Agent"] = site.ua
        cookie = self._get_site_cookie()
        if cookie:
            headers["Cookie"] = cookie
        s.headers.update(headers)
        return s

    @staticmethod
    def _get_with_retry(session, url, timeout=30, retries=2, backoff=(3, 5)):
        last_exc = None
        for i in range(retries + 1):
            try:
                r = session.get(url, timeout=timeout)
                r.raise_for_status()
                return r
            except Exception as e:
                last_exc = e
                if i < retries:
                    wait = backoff[i] if i < len(backoff) else 5
                    time.sleep(wait)
        raise last_exc

    def _last_settlement_from_stats(self) -> Tuple[Optional[float], Optional[float], str]:
        """从结算统计表本地聚合数据取最新一条实结记录（records 按日期排序，取日期最大者）"""
        try:
            data = self._load_monthly_stats()
            recs = data.get("records") or []
            if not recs:
                return None, None, ""
            best = max(recs, key=lambda r: str(r.get("date") or ""))
            return (float(best.get("bean") or 0), float(best.get("pt") or 0),
                    str(best.get("date") or ""))
        except Exception:
            return None, None, ""

    def _fetch_last_settlement(self) -> Tuple[Optional[float], Optional[float], str]:
        """翻页拉取保种结算日志至末页，取全局最新一条（日志按时间正序分页，最新在最后一页）"""
        uid = self._get_site_uid()
        if not uid:
            return None, None, ""
        try:
            session = self._session()
            site_url = self._get_site_url()
            best = None
            best_date = ""
            page = 0
            while page <= 600:
                try:
                    if page == 0:
                        url = f"{site_url}/rescuesettleinfo.php?id={uid}"
                    else:
                        url = f"{site_url}/rescuesettleinfo.php?id={uid}&page={page}"
                    r = self._get_with_retry(session, url, timeout=20, retries=2, backoff=(3, 5))
                except Exception as e:
                    logger.warning(f"上次结算第{page + 1}页获取失败：{HHClubButler._safe_error(e)}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                table = None
                for tb in soup.find_all("table"):
                    if "获得的憨豆" in tb.get_text() and "结算时间" in tb.get_text():
                        table = tb
                        break
                if not table:
                    break
                new_rows = 0
                page_best = None
                page_best_date = ""
                for tr in table.select("tr"):
                    tds = tr.find_all(["td", "th"])
                    if len(tds) < 8:
                        continue
                    cells = [c.get_text(strip=True) for c in tds]
                    try:
                        bean = float(re.sub(r'[^\d.]', '', cells[4]) or 0)
                        pt = float(re.sub(r'[^\d.]', '', cells[5]) or 0)
                        dstr = cells[7]
                        dmatch = re.search(r'\d{4}-\d{2}-\d{2}', dstr)
                        if not dmatch:
                            continue
                        d = dmatch.group(0)
                        new_rows += 1
                        if d >= page_best_date:
                            page_best_date = d
                            page_best = (bean, pt)
                    except (ValueError, IndexError):
                        continue
                if new_rows == 0:
                    break
                if page_best and page_best_date >= best_date:
                    best_date = page_best_date
                    best = page_best
                page += 1
            if best:
                return best[0], best[1], best_date
        except Exception as e:
            logger.warning(f"抓取上次结算失败：{HHClubButler._safe_error(e)}")
        return None, None, ""

    # ---------- 结算统计表（保种结算日志翻页拉取 + 本地历史累计） ----------

    def _monthly_stats_path(self):
        try:
            path = self.get_data_path()
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            return path / "monthly_stats.json"
        except Exception as e:
            logger.error(f"获取插件数据目录失败：{HHClubButler._safe_error(e)}")
            return None

    def _load_monthly_stats(self) -> dict:
        self._load_error = ""
        p = self._monthly_stats_path()
        if not p or not p.exists():
            return {"last_fetch_date": "", "updated_at": "", "records": []}
        try:
            size = p.stat().st_size
            if size == 0:
                self._load_error = f"文件为空（0 字节）"
                logger.warning(f"读取结算统计表本地数据失败：文件为空（0 字节）：{p}")
                return {"last_fetch_date": "", "updated_at": "", "records": []}
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"读取结算统计表本地数据失败：{HHClubButler._safe_error(e)}")
            return {"last_fetch_date": "", "updated_at": "", "records": []}

    def _save_monthly_stats(self, data: dict):
        """原子写入结算统计表本地数据：先写临时文件再替换，杜绝 0 字节空文件"""
        self._save_error = ""
        p = self._monthly_stats_path()
        if not p:
            self._save_error = "数据目录不可用"
            return
        try:
            s = json.dumps(data, ensure_ascii=False, indent=1)
        except Exception as e:
            self._save_error = f"序列化失败：{HHClubButler._safe_error(e)}"
            logger.error(f"保存结算统计表本地数据失败（序列化）：{HHClubButler._safe_error(e)}")
            return
        tmp = p.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(s)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp, p)
        except Exception as e:
            self._save_error = f"写入失败：{HHClubButler._safe_error(e)}"
            logger.error(f"保存结算统计表本地数据失败（写入）：{HHClubButler._safe_error(e)}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def _fetch_settlement_history(self) -> List[Tuple[str, float, float]]:
        """翻页拉取保种结算日志：第1页无page参数，之后 page=1,2,...（0基），直至无更多数据"""
        uid = self._get_site_uid()
        if not uid:
            return []
        session = self._session()
        site_url = self._get_site_url()
        out: Dict[str, Tuple[float, float]] = {}
        page = 0
        while page <= 600:
            try:
                if page == 0:
                    url = f"{site_url}/rescuesettleinfo.php?id={uid}"
                else:
                    url = f"{site_url}/rescuesettleinfo.php?id={uid}&page={page}"
                html = self._get_with_retry(session, url, timeout=20, retries=2, backoff=(3, 5)).text
            except Exception as e:
                logger.warning(f"结算日志第{page + 1}页获取失败：{self._safe_error(e)}")
                return []
            soup = BeautifulSoup(html, "html.parser")
            table = None
            for tb in soup.find_all("table"):
                if "获得的憨豆" in tb.get_text() and "结算时间" in tb.get_text():
                    table = tb
                    break
            if not table:
                break
            new_rows = 0
            for tr in table.select("tr"):
                tds = tr.find_all(["td", "th"])
                if len(tds) < 8:
                    continue
                cells = [c.get_text(strip=True) for c in tds]
                try:
                    bean = float(re.sub(r'[^\d.]', '', cells[4]) or 0)
                    pt = float(re.sub(r'[^\d.]', '', cells[5]) or 0)
                    dstr = cells[7]
                    dmatch = re.search(r'\d{4}-\d{2}-\d{2}', dstr)
                    if not dmatch:
                        continue
                    day = dmatch.group(0)
                    new_rows += int(day not in out)
                    out[day] = (bean, pt)
                except (ValueError, IndexError):
                    continue
            if new_rows == 0:
                break
            page += 1
        if out:
            logger.info(f"结算日志翻页拉取完成：共 {len(out)} 条（最新 {max(out.keys())}）")
        return [(d, v[0], v[1]) for d, v in out.items()]

    def _ensure_monthly_stats_impl(self, force: bool = False) -> dict:
        """返回本地历史；当日已成功获取（本地已含当日记录或当日拉取成功）则直接使用。
        拉取失败或未拉取到当日数据时，按 retry_at 时间戳（5 分钟间隔）自动重试，当日累计最多 3 次。
        结算日志按时间正序分页，最新一条在最后一页；本地按日期全量聚合，取最新=max(date)，与页序无关。"""
        data = self._load_monthly_stats()
        records = data.get("records") or []
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        has_today = any(str(r.get("date")) == today for r in records)
        if not force and (data.get("last_fetch_date") == today or has_today):
            self._fetch_state = "ok_cached"
            return data
        attempt_date = str(data.get("last_attempt_date") or "")
        attempts = int(data.get("attempt_count") or 0) if attempt_date == today else 0
        retry_at = float(data.get("retry_at") or 0)
        if not force and attempt_date == today and attempts >= 3:
            self._fetch_state = "failed_limited"
            return data
        if not force and attempt_date == today and attempts > 0 and now.timestamp() < retry_at:
            self._fetch_state = "pending_retry"
            return data
        generation = self._delete_generation
        fetched = self._fetch_settlement_history()
        if self._stopped or generation != self._delete_generation:
            return data
        if fetched:
            merged: Dict[str, dict] = {}
            for r in records:
                merged[str(r.get("date"))] = {
                    "date": str(r.get("date")),
                    "bean": float(r.get("bean") or 0),
                    "pt": float(r.get("pt") or 0),
                }
            for d, b, p in fetched:
                merged[d] = {"date": d, "bean": float(b or 0), "pt": float(p or 0)}
            data["records"] = sorted(merged.values(), key=lambda x: x["date"])
            data["last_attempt_date"] = today
            if today in merged:
                data["last_fetch_date"] = today
                data["attempt_count"] = 0
                data["retry_at"] = 0
                data["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                self._save_monthly_stats(data)
                self._fetch_state = "ok"
            else:
                # 拉取成功但站点当日记录尚未生成（如当日尚未实结），按 5 分钟间隔重试
                data["attempt_count"] = attempts + 1
                data["retry_at"] = now.timestamp() + 300
                self._save_monthly_stats(data)
                self._fetch_state = "no_today_data"
                logger.warning(f"结算日志未包含今日数据（今日已尝试 {attempts + 1} 次），5 分钟后自动重试")
        else:
            data["last_attempt_date"] = today
            data["attempt_count"] = attempts + 1
            data["retry_at"] = now.timestamp() + 300
            self._save_monthly_stats(data)
            self._fetch_state = "failed"
            if not records:
                logger.warning("结算日志拉取失败（或站点无记录），5 分钟后自动重试")
            else:
                logger.warning(f"结算日志拉取失败，保留本地历史数据（今日已尝试 {attempts + 1} 次），5 分钟后自动重试")
        return data

    def _monthly_agg(self, data: dict) -> dict:
        """聚合近12个月（含当月）月度憨豆/积分"""
        records = data.get("records") or []
        tz = pytz.timezone(settings.TZ)
        now = datetime.now(tz)
        ym_now = now.year * 12 + (now.month - 1)
        labels, bean, pt, days, notes = [], [], [], [], []
        for i in range(11, -1, -1):
            t = ym_now - i
            ty, tm = divmod(t, 12)
            tm += 1
            labels.append(f"{ty}-{tm:02d}")
            bean.append(None)
            pt.append(None)
            days.append(0)
            notes.append("")
        monthly: Dict[str, List[float]] = {}
        for r in records:
            d = str(r.get("date") or "")
            if len(d) < 7:
                continue
            key = d[:7]
            if key not in monthly:
                monthly[key] = [0.0, 0.0, 0]
            monthly[key][0] += float(r.get("bean") or 0)
            monthly[key][1] += float(r.get("pt") or 0)
            monthly[key][2] += 1
        now_key = now.strftime("%Y-%m")
        for i, lab in enumerate(labels):
            if lab in monthly:
                bean[i] = round(monthly[lab][0], 1)
                pt[i] = round(monthly[lab][1], 1)
                days[i] = int(monthly[lab][2])
                if lab == now_key:
                    notes[i] = "进行中"
                else:
                    try:
                        y, m = int(lab[:4]), int(lab[5:7])
                        nxt = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
                        total = (nxt - datetime(y, m, 1)).days
                    except Exception:
                        total = 31
                    notes[i] = f"仅{days[i]}天" if days[i] < total else "完整"
        total_bean = sum(float(r.get("bean") or 0) for r in records)
        total_pt = sum(float(r.get("pt") or 0) for r in records)
        return {"labels": labels, "bean": bean, "pt": pt, "days": days, "notes": notes,
                "total_bean": round(total_bean, 1), "total_pt": round(total_pt, 1),
                "updated_at": data.get("updated_at", ""),
                "last_fetch_date": data.get("last_fetch_date", "")}

    def api_monthly_stats(self):
        return HTMLResponse(
            content=self._build_monthly_stats_html(),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                     "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"})

    def _ensure_monthly_stats(self, force: bool = False) -> dict:
        generation = self._delete_generation
        with self._stats_lock:
            if self._stopped or generation != self._delete_generation:
                raise RuntimeError("结算刷新配置已变化")
            self._save_error = ""
            result = self._ensure_monthly_stats_impl(force=force)
            if getattr(self, "_save_error", ""):
                raise RuntimeError("结算数据保存失败，未确认本次刷新成功")
            return result

    def _monthly_stats_worker(self, generation, force):
        try:
            result = self._monthly_stats_result(refresh=int(force))
        except Exception as error:
            logger.error(f"结算后台任务失败：{self._safe_error(error)}")
            result = {"error": "结算后台读取失败，请检查脱敏日志"}
        with self._stats_job_lock:
            if self._stopped or generation != self._delete_generation:
                return
            self._stats_job = {"state": "ready", "result": result, "finished_at": time.time()}

    def api_monthly_stats_data(self, refresh: int = 0):
        with self._stats_job_lock:
            if self._stopped or not self._enabled:
                return {"error": "插件未启用"}
            job = self._stats_job
            if job.get("state") == "loading":
                return {"loading": True, "elapsed_seconds": max(0, int(time.time() - job["started_at"]))}
            if not refresh and job.get("state") == "ready" and time.time() - job["finished_at"] < 180:
                return job["result"]
            self._stats_job = {"state": "loading", "started_at": time.time()}
            try:
                threading.Thread(target=self._monthly_stats_worker, args=(self._delete_generation, bool(refresh)),
                                 daemon=True, name="HHClubButler-Settlement").start()
            except Exception:
                self._stats_job = {"state": "idle"}
                return {"error": "无法启动结算后台任务"}
            return {"loading": True}

    def _monthly_stats_result(self, refresh: int = 0):
        try:
            data = self._ensure_monthly_stats(force=bool(refresh))
            agg = self._monthly_agg(data)
            records = data.get("records") or []
            recent = sorted(records, key=lambda x: str(x.get("date", "")))[-40:]
            p = self._monthly_stats_path()
            try:
                file_size = p.stat().st_size if p and p.exists() else 0
            except Exception:
                file_size = -1
            return {
                "labels": agg["labels"], "bean": agg["bean"], "pt": agg["pt"],
                "days": agg["days"], "notes": agg["notes"],
                "total_bean": agg["total_bean"], "total_pt": agg["total_pt"],
                "updated_at": agg["updated_at"], "last_fetch_date": agg["last_fetch_date"],
                "records_total": len(records),
                "records": [{"date": str(r.get("date", "")),
                             "bean": float(r.get("bean") or 0),
                             "pt": float(r.get("pt") or 0)} for r in recent],
                "fetch_state": getattr(self, "_fetch_state", ""),
                "attempt_count": int(data.get("attempt_count") or 0),
                "diag": {
                    "data_path": str(p or ""),
                    "file_size": file_size,
                    "save_error": getattr(self, "_save_error", ""),
                    "load_error": getattr(self, "_load_error", ""),
                    "last_fetch_date": str(data.get("last_fetch_date") or ""),
                    "last_attempt_date": str(data.get("last_attempt_date") or ""),
                },
            }
        except Exception as e:
            logger.error(f"获取结算统计表数据失败：{HHClubButler._safe_error(e)}")
            return {"error": "结算读取失败，请检查脱敏日志"}

    def _build_monthly_stats_html(self) -> str:
        html = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>统计结算表</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI","PingFang SC",Arial,sans-serif;color:#F0ECFF;
background:radial-gradient(800px 420px at 6% -8%,rgba(255,64,160,.13),transparent 55%),
radial-gradient(900px 460px at 94% -6%,rgba(64,200,255,.15),transparent 55%),#0B0714;
min-height:100vh;height:100vh;height:100dvh;display:flex;flex-direction:column;overflow:hidden;font-size:12px}
.wrap{width:100%;margin:0 auto;flex:1;overflow:auto;padding:20px 28px 16px;display:flex;flex-direction:column}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.head .t{font-size:22px;font-weight:700}
.head .t b{color:#FF8A3C}
.head .src{font-size:12px;color:#9A8FC0;margin-top:5px}
.exit{border:1px solid rgba(255,64,160,.35);background:rgba(255,64,160,.06);color:#D9A0CF;font-size:13px;padding:7px 16px;border-radius:10px;cursor:pointer;font-family:inherit}
.exit:hover{background:rgba(255,64,160,.16)}
.topcard{background:rgba(16,10,28,.75);border:1px solid rgba(64,200,255,.25);border-radius:18px;padding:16px 18px 12px;
box-shadow:0 0 30px rgba(64,200,255,.07);margin-bottom:18px}
.ct{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}
.ct .nm{font-size:16px;font-weight:700}.ct .sb{font-size:11px;color:#9A8FC0}
.chart{width:100%;height:300px}
.low{display:grid;grid-template-columns:1fr 1.15fr;gap:18px}
.card{background:rgba(16,10,28,.72);border:1px solid rgba(255,64,160,.28);border-radius:18px;padding:16px 18px;
box-shadow:0 0 24px rgba(255,64,160,.07)}
.duals{position:relative;width:100%;height:330px;display:flex;gap:14px}
.duals .dbox{position:relative;flex:1 1 0;min-width:0}
.duals .g{width:100%;height:330px}
.duals .dlab{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);text-align:center;pointer-events:none}
.duals .dlab .r{font-size:14px;color:#9A8FC0;margin-bottom:8px}
.duals .dlab .v{font-size:26px;font-weight:700;line-height:1.15}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-weight:600;color:#9A8FC0;font-size:11px;padding:7px 10px;border-bottom:1px solid rgba(255,64,160,.16);position:sticky;top:0;background:#150D24}
td{padding:8px 10px;border-bottom:1px solid rgba(120,90,220,.10);color:#DCD3F5;font-variant-numeric:tabular-nums}
td.d{color:#9A8FC0}
td.bean{color:#FF8A3C;font-weight:600}
td.pt{color:#38D9FF;font-weight:600}
.scroll30{height:330px;overflow-y:auto;border-radius:12px;border:1px solid rgba(120,90,220,.20)}
.scroll30::-webkit-scrollbar{width:8px}.scroll30::-webkit-scrollbar-thumb{background:#4A3A78;border-radius:4px}
.status{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;font-size:14px;color:#F0ECFF;text-align:center;max-width:460px;padding:28px 36px;border-radius:14px;border:1px solid rgba(255,64,160,.25);background:rgba(16,10,28,.85);box-shadow:0 0 30px rgba(255,64,160,.12)}
.status .bar{width:260px;height:4px;background:rgba(120,90,220,.18);border-radius:2px;overflow:hidden;position:relative}
.status .bar i{position:absolute;top:0;left:0;height:100%;width:38%;background:linear-gradient(90deg,#FF8A3C,#38D9FF);border-radius:2px;animation:hhslide 1s linear infinite;box-shadow:0 0 8px rgba(255,138,60,.6)}
@keyframes hhslide{0%{left:-38%}100%{left:100%}}
.status .err{color:#FF6B6B;font-size:13px;max-width:80%;text-align:center;line-height:1.6}
.status .retrybtn{background:linear-gradient(90deg,#FF8A3C,#38D9FF);color:#0B0714;border:none;padding:8px 26px;border-radius:8px;cursor:pointer;font-size:13px;margin-top:4px;font-weight:600}
.warnbar{display:none;margin-bottom:14px;padding:10px 16px;border-radius:12px;background:rgba(255,107,107,.10);border:1px solid rgba(255,107,107,.45);color:#FFB3A0;font-size:12.5px;line-height:1.6;align-items:center}
.warnbar b{font-weight:700;color:#FF8A6B}
.warnbar .wbtn{margin-left:14px;background:rgba(255,107,107,.18);border:1px solid rgba(255,107,107,.55);color:#FFD0C0;padding:5px 16px;border-radius:8px;cursor:pointer;font-size:12px;font-family:inherit;flex-shrink:0}
.warnbar .wbtn:hover{background:rgba(255,107,107,.32)}
.bodywrap{position:relative;flex:1;display:flex;flex-direction:column}
.footer{margin-top:16px;font-size:11.5px;color:#9A8FC0;line-height:1.7;text-align:center}
@media (max-width:720px){
.wrap{padding:14px 12px 12px}
.head .t{font-size:18px}
.head .src{font-size:11px}
.low{grid-template-columns:1fr}
.scroll30{overflow-x:auto}
.chart{height:272px}
.duals{height:280px}
.duals .g{height:280px}
.status{max-width:88vw;padding:22px 16px}
.status .bar{width:200px}
}
</style></head><body>
<div class="wrap">
<div class="head">
<div><div class="t">统计<b>结算表</b></div>
<div class="src">憨憨站保种结算日志 · 每日 0 点憨豆/积分实结</div></div>
<button class="exit" title="关闭页面" onclick="window.close()">退出</button>
</div>
<div class="bodywrap">
<div id="warn" class="warnbar"></div>
<div id="status" class="status"><span>正在获取每月结算数据，请稍候…</span><div class="bar"><i></i></div></div>
<div id="main" style="display:none">
<div class="topcard"><div class="ct"><span class="nm">近30日收益</span><span class="sb">橙柱 = 憨豆 · 青柱 = 积分 · 按结算日志每日实结</span></div>
<div class="chart" id="mb"></div></div>
<div class="low">
<div class="card"><div class="ct"><span class="nm">保种历史累计统计</span><span class="sb">左环 = 憨豆 · 右环 = 积分</span></div>
<div class="duals"><div class="dbox"><div class="g" id="dg1"></div><div class="dlab"><div class="r">憨豆累计</div><div class="v" id="cvb" style="color:#FF8A3C">—</div></div></div>
<div class="dbox"><div class="g" id="dg2"></div><div class="dlab"><div class="r">积分累计</div><div class="v" id="cvp" style="color:#38D9FF">—</div></div></div></div></div>
<div class="card"><div class="ct"><span class="nm">近12个月收益</span><span class="sb">带 * 的月份为部分数据（未满整月）· 最新月份在最上方</span></div>
<div class="scroll30" id="tbl"></div></div>
</div>
</div>
</div>
<div class="footer" id="foot">灰显月份暂无历史记录 · 统计结算表数据来自憨憨站保种结算日志</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<script>
var data=null,chb=null,chd1=null,chd2=null;
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}
function fmtBig(n){if(n===null||n===undefined)return "—";return Number(n).toLocaleString()}
function showErr(msg){var st=document.getElementById('status');st.innerHTML='<span class="err">'+esc(msg)+'</span><button class="retrybtn" onclick="location.reload()">重试</button>';}
function showWarn(msg){var w=document.getElementById('warn');w.style.display='flex';w.innerHTML='<b>⚠ '+esc(msg)+'</b><button class="wbtn" onclick="loadData(true)">立即重试</button>';}
function clearWarn(){var w=document.getElementById('warn');w.style.display='none';w.innerHTML='';}
var statsLoading=false;
async function loadData(refresh){
if(statsLoading)return;
statsLoading=true;
var t0=Date.now(),tmr=null;
document.getElementById('status').innerHTML='<span>正在获取每月结算数据，请稍候… <b id="el">0</b> 秒</span><div class="bar"><i></i></div>';
function tick(){var el=document.getElementById("el");if(el)el.textContent=Math.floor((Date.now()-t0)/1000);}
tick();tmr=setInterval(tick,250);
var url='/api/v1/plugin/HHClubButler/monthly_stats_data'+(refresh?'?refresh=1':'');
try {
var j;
while(true){
var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort()},15000);
try{
var r=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:ctl.signal});
if(!r.ok)throw Error('HTTP '+r.status);
j=await r.json();
}finally{clearTimeout(timer)}
if(!j.loading)break;
if(Date.now()-t0>480000)throw Error('后台结算读取超时，请检查日志后重试');
url='/api/v1/plugin/HHClubButler/monthly_stats_data';
await new Promise(function(resolve){setTimeout(resolve,3000)});
}
if(j&&j.error){if(tmr)clearInterval(tmr);showErr(j.error);return;}
data=j;
var st=document.getElementById('status');if(tmr)clearInterval(tmr);st.style.display='none';
document.getElementById('main').style.display='block';
clearWarn();
if(data.fetch_state==='failed'||data.fetch_state==='failed_limited'){
var n=data.attempt_count||0;
showWarn('今日结算数据获取失败（已尝试 '+n+' 次），当前展示为历史数据，非当日数据！');
}else if(data.fetch_state==='no_today_data'){
showWarn('站点当日结算记录尚未生成，正在自动重试（每5分钟一次，已尝试 '+(data.attempt_count||0)+' 次）…');
}else if(data.fetch_state==='pending_retry'){
showWarn('今日结算数据拉取未成功，等待自动重试中（每5分钟一次）…');
}
var ft=document.getElementById('foot');
ft.textContent='数据更新于 '+(data.updated_at||'—')+' · 灰显月份暂无历史记录 · 统计结算表数据来自憨憨站保种结算日志';
if(typeof echarts==='undefined'){renderTable();return;}
renderChart();renderTable();
}catch(e){showErr('获取数据失败：'+e.message);}
finally{if(tmr)clearInterval(tmr);statsLoading=false;}
}
loadData(false);
function renderChart(){
chb=echarts.init(document.getElementById('mb'));
var rec=(data.records||[]).slice(-30);
var x=[],b=[],p=[];
for(var i=0;i<rec.length;i++){var r=rec[i];x.push(String(r.date||'').slice(5));b.push(r.bean);p.push(r.pt);}
var isM=window.innerWidth<560;
chb.setOption({backgroundColor:'transparent',
tooltip:{trigger:'axis',triggerOn:'click',renderMode:'richText',confine:true,textStyle:{fontSize:11,color:'#F0ECFF',lineHeight:15},backgroundColor:'rgba(21,13,36,.95)',borderColor:'rgba(64,200,255,.3)',padding:[6,8]},
grid:{left:8,right:14,top:30,bottom:24,containLabel:true},
legend:{top:0,itemWidth:14,itemHeight:8,textStyle:{fontSize:11,color:'#A79BC9'}},
xAxis:{type:'category',data:x,axisLabel:{fontSize:isM?7:9,color:'#9A8FC0',interval:0,formatter:function(v,i){var d=String((rec[i]&&rec[i].date)||'');return d?d.slice(5).replace('-','/'):''}}},
yAxis:{type:'value',axisLabel:{fontSize:10,color:'#9A8FC0',formatter:function(v){return v>=10000?(v/10000).toFixed(1).replace('.0','')+'万':v}},splitLine:{lineStyle:{color:'rgba(64,200,255,.12)'}}},
series:[
{name:'憨豆',type:'bar',data:b,itemStyle:{color:'#FF8A3C',borderRadius:[4,4,0,0]},
label:{show:true,position:'top',fontSize:9,color:'#FF8A3C',distance:2,formatter:function(p){return (p.value===null||p.value===undefined)?'':fmtBig(p.value)}},labelLayout:{hideOverlap:true}},
{name:'积分',type:'bar',data:p,itemStyle:{color:'#38D9FF',borderRadius:[4,4,0,0]},
label:{show:true,position:'top',fontSize:9,color:'#38D9FF',distance:2,formatter:function(p){return (p.value===null||p.value===undefined)?'':fmtBig(p.value)}},labelLayout:{hideOverlap:true}}]});
chd1=echarts.init(document.getElementById('dg1'));
chd2=echarts.init(document.getElementById('dg2'));
var tb=(data.total_bean===undefined||data.total_bean===null)?0:Number(data.total_bean);
var tp=(data.total_pt===undefined||data.total_pt===null)?0:Number(data.total_pt);
document.getElementById('cvb').textContent=fmtBig(tb);
document.getElementById('cvp').textContent=fmtBig(tp);
chd1.setOption({backgroundColor:'transparent',series:[
{type:'gauge',startAngle:210,endAngle:-30,min:0,max:Math.max(tb,1),radius:'78%',center:['50%','52%'],
progress:{show:true,width:22,itemStyle:{color:'#FF8A3C',shadowColor:'#FF8A3C',shadowBlur:16}},
axisLine:{lineStyle:{width:22,color:[[1,'rgba(255,138,60,.10)']]}},
axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},pointer:{show:false},detail:{show:false},data:[{value:tb}]}]});
chd2.setOption({backgroundColor:'transparent',series:[
{type:'gauge',startAngle:210,endAngle:-30,min:0,max:Math.max(tp,1),radius:'78%',center:['50%','52%'],
progress:{show:true,width:22,itemStyle:{color:'#38D9FF',shadowColor:'#38D9FF',shadowBlur:16}},
axisLine:{lineStyle:{width:22,color:[[1,'rgba(56,217,255,.10)']]}},
axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},pointer:{show:false},detail:{show:false},data:[{value:tp}]}]});
window.addEventListener('resize',function(){if(chb)chb.resize();if(chd1)chd1.resize();if(chd2)chd2.resize();});
}
function renderTable(){
var labs=data.labels,bean=data.bean,pt=data.pt,notes=data.notes||[];
var cumB=[],cumP=[],cb=0,cp=0;
for(var i=0;i<labs.length;i++){cb+=bean[i]||0;cp+=(pt[i]||0);cumB.push(cb);cumP.push(cp);}
var rows='';
for(var j=labs.length-1;j>=0;j--){var v=bean[j];
if(v===null||v===undefined){rows+='<tr><td class="d">'+esc(labs[j])+'</td><td class="d">-</td><td class="d">-</td><td class="d">-</td><td class="d">-</td></tr>';continue;}
var star=(notes[j]&&notes[j].indexOf('仅')===0)?' *':'';
rows+='<tr><td class="d">'+esc(labs[j])+star+'</td><td class="bean">'+fmtBig(v)+'</td><td class="pt">'+fmtBig(pt[j])+'</td><td>'+fmtBig(cumB[j])+'</td><td>'+fmtBig(cumP[j])+'</td></tr>';}
document.getElementById('tbl').innerHTML='<table><thead><tr><th>月份</th><th>憨豆</th><th>积分</th><th>累计憨豆</th><th>累计积分</th></tr></thead><tbody>'+rows+'</tbody></table>';
}
</script></body></html>"""
        return html

    def _fetch_rescue_all(self, logs: list) -> List[dict]:
        seeds = []
        session = self._session()
        max_page = 1
        site_url = self._get_site_url()

        def _try_get(u):
            r = self._get_with_retry(session, u, timeout=30, retries=2, backoff=(3, 5))
            return r.text

        try:
            html = _try_get(f"{site_url}/rescue.php?page=0")
            page_seeds, max_page = self._parse_rescue_page(html)
            seeds.extend(page_seeds)
            logs.append(f"保种区第1页获取 {len(page_seeds)} 条数据")
        except Exception as e:
            alt = site_url.replace("hhanclub.net", "hhancclub.net") if "hhanclub.net" in site_url \
                else site_url.replace("hhancclub.net", "hhanclub.net")
            if alt != site_url:
                try:
                    html = _try_get(f"{alt}/rescue.php?page=0")
                    site_url = alt
                    page_seeds, max_page = self._parse_rescue_page(html)
                    seeds.extend(page_seeds)
                    logs.append(f"保种区第1页已通过备用域名访问：{alt}")
                except Exception as e2:
                    logs.append(f"保种区第1页获取失败（含备用域名）：{HHClubButler._safe_error(e2)}")
                    return []
            else:
                logs.append(f"保种区第1页获取失败：{HHClubButler._safe_error(e)}")
                return []
        for page in range(1, max_page + 1):
            try:
                r = self._get_with_retry(session, f"{site_url}/rescue.php?page={page}",
                                         timeout=30, retries=2, backoff=(3, 5))
                page_seeds, _ = self._parse_rescue_page(r.text)
                seeds.extend(page_seeds)
                logs.append(f"保种区第{page + 1}页获取 {len(page_seeds)} 条数据")
            except Exception as e:
                logs.append(f"保种区第{page + 1}页获取失败（已重试）：{HHClubButler._safe_error(e)}")
                logs.append("候选池数据不完整，本次优选中止以防误操作")
                return []
            time.sleep(0.5)
        unique = {}
        for seed in seeds:
            key = seed.get("seed_id") or (normalize_name(release_name(seed.get("title"))), seed.get("href"))
            unique.setdefault(key, seed)
        return list(unique.values())

    def _parse_rescue_page(self, html: str) -> Tuple[List[dict], int]:
        seeds = []
        max_page = 0
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select('a[href*="page="]'):
            m = re.search(r'[?&]page=(\d+)', a.get("href", ""))
            if m:
                max_page = max(max_page, int(m.group(1)))
        if max_page > 500:
            raise ValueError("保种候选分页超过安全上限")
        for row in soup.select("div.torrent-table-sub-info"):
            s = self._parse_seed_row(row)
            if s:
                seeds.append(s)
        return seeds, max_page

    def _parse_seed_row(self, row) -> Optional[dict]:
        a_title = row.select_one("a.torrent-info-text-name")
        title = a_title.get_text(strip=True) if a_title else ""
        if not title:
            for a in row.find_all("a"):
                t = a.get_text(strip=True)
                if len(t) > 10:
                    title = t
                    break
        a_dl = row.select_one('a[href*="download.php"]')
        href = a_dl.get("href", "") if a_dl else ""
        size = None
        nums = []
        stats_el = row.select_one(".w-\\[20\\%\\]")
        leaves = []
        if stats_el:
            for el in stats_el.find_all(True):
                if el.find(True) is None and el.get_text(strip=True):
                    leaves.append(el.get_text(strip=True))
        for leaf in leaves:
            if size is None and re.search(r'(TB|GB|MB|KB)', leaf, re.I):
                size = size_to_gb(leaf)
                continue
            if re.match(r'^\d+(\.\d+)?$', leaf):
                nums.append(float(leaf))
        if size is None:
            for el in row.find_all(True):
                txt = el.get_text(strip=True)
                if el.find(True) is None and re.search(r'^\s*[\d.]+\s*(TB|GB|MB|KB)\s*$', txt, re.I):
                    size = size_to_gb(txt)
                    break
        if size is None:
            return None
        seeders = int(nums[0]) if nums else 0
        now_seeders = int(nums[1]) if len(nums) > 1 else 0
        if tier_of(seeders) >= 99:
            return None
        seed_id = None
        m_id = re.search(r'details\.php\?id=(\d+)', str(a_title.get("href") if a_title else ""))
        if m_id:
            seed_id = int(m_id.group(1))
        return {
            "title": title,
            "href": href,
            "size": size,
            "seeders": seeders,
            "now_seeders": now_seeders,
            "seed_id": seed_id,
        }

    def _get_current_seeding(self, logs: list, torrents: Optional[list] = None) -> dict:
        result = {"count": 0, "total_gb": 0.0, "seeds": []}
        try:
            rows = self._collect_rescue_seeds(strict_downloaders=True)
        except Exception as error:
            result["error"] = "站点或下载器无法完整读取"
            logs.append(f"当前保种读取失败：{self._safe_error(error)}")
            return result
        current = []
        for row in rows:
            copies = row.get("candidates", [])
            if row.get("source") == "downloader" or row.get("match_status") not in {"exact", "translated", "cross_seed"}:
                continue
            if not any(copy.get("completed") for copy in copies):
                continue
            item = dict(row)
            item["auto_delete_ready"] = bool(item.get("can_delete_group") and copies
                and all(copy.get("completed") and copy.get("trusted_tracker") for copy in copies))
            current.append(item)
        result.update(count=len(current), total_gb=sum(s.get("size", 0) for s in current), seeds=current)
        logs.append(f"站点资格与下载器强匹配的已完成保种 {len(current)} 个")
        return result

    def _build_overview_from_current(self, cur: dict) -> dict:
        seeds = cur.get("seeds", [])
        dist = {"0-1人": {"count": 0, "gb": 0.0},
                "2-3人": {"count": 0, "gb": 0.0},
                "4-5人": {"count": 0, "gb": 0.0}}
        for s in seeds:
            t = tier_of(s.get("seeders", 0))
            if t > 2:
                t = 2
            dist[TIER_NAMES[t]]["count"] += 1
            dist[TIER_NAMES[t]]["gb"] += s.get("size", 0.0)
        total_gb = cur.get("total_gb", 0.0)
        # 优先从结算统计表本地聚合数据取最新一条（全量翻页聚合，最新=max(日期)，与页序无关），
        # 与[统计结算表]页面同源一致；本地为空时才回退到翻页兜底抓取
        last_bean, last_pt, last_date = self._last_settlement_from_stats()
        if last_bean is None:
            last_bean, last_pt, last_date = self._fetch_last_settlement()
        if last_bean is None and self._last_overview:
            last_bean = self._last_overview.get("last_bean")
            last_pt = self._last_overview.get("last_pt")
            last_date = self._last_overview.get("last_date", "")
        return {
            "count": cur.get("count", 0),
            "total_gb": total_gb,
            "total_tb": total_gb / 1024.0,
            "last_bean": last_bean,
            "last_pt": last_pt,
            "last_date": last_date,
            "dist": dist,
            "ok": not cur.get("error") and not cur.get("degraded"),
        }

    def _fetch_completed(self, logs: list) -> List[dict]:
        uid = self._get_site_uid()
        if not uid:
            logs.append("未获取到站点UID")
            return []
        items = []
        session = self._session()
        url = f"{self._get_site_url()}/userdetails.php?action=7&id={uid}"
        max_page = 0
        try:
            r = self._get_with_retry(session, url, timeout=30, retries=2, backoff=(3, 5))
            items, max_page = self._parse_completed_page(r.text)
        except Exception as e:
            alt = url.replace("hhanclub.net", "hhancclub.net") if "hhanclub.net" in url \
                else url.replace("hhancclub.net", "hhanclub.net")
            if alt != url:
                try:
                    r = self._get_with_retry(session, alt, timeout=30, retries=2, backoff=(3, 5))
                    url = alt
                    items, max_page = self._parse_completed_page(r.text)
                    logs.append(f"完成页已通过备用域名访问：{alt}")
                except Exception as e2:
                    logs.append(f"完成页第1页获取失败（含备用域名，已重试）：{HHClubButler._safe_error(e2)}")
                    return []
            else:
                logs.append(f"完成页第1页获取失败（已重试）：{HHClubButler._safe_error(e)}")
                return []
        logger.info(f"憨憨保种管理器：站点完成页 UID={uid}，预计 {max_page + 1} 页")
        page = 1
        while page <= max_page:
            try:
                r = self._get_with_retry(session, f"{url}&page={page}",
                                         timeout=30, retries=2, backoff=(3, 5))
                page_items, discovered = self._parse_completed_page(r.text)
                max_page = max(max_page, discovered)
                items.extend(page_items)
            except Exception as e:
                logs.append(f"完成页第{page + 1}页获取失败（已重试）：{HHClubButler._safe_error(e)}")
                logs.append("完成页数据不完整，本次刷新作废保留上次数据")
                return []
            time.sleep(0.5)
            page += 1

        # Dynamic pagination can overlap records when the user changes their
        # rescue status during a crawl. Preserve site identity and dedupe.
        deduped, seen = [], set()
        for seed in items:
            sid = seed.get("seed_id")
            key = ("id", str(sid)) if sid is not None else (
                "title", HHClubButler._norm_title(seed.get("title") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(seed)
        logs.append(f"保种完成页共 {max_page + 1} 页，原始记录 {len(items)} 条，"
                    f"去重后可保种记录 {len(deduped)} 条")
        return deduped

    @staticmethod
    def _norm_title(s) -> str:
        if not s:
            return ""
        s = str(s).lower()
        return re.sub(r'[^0-9a-z\u4e00-\u9fff]', '', s)

    def _parse_completed_page(self, html: str) -> Tuple[List[dict], int]:
        items = []
        max_page = 0
        soup = BeautifulSoup(html, "html.parser")
        m = re.search(r"(?:var|let|const)\s+maxpage\s*=\s*(\d+)", html, re.I)
        if m:
            max_page = int(m.group(1))
        # Some site themes omit the old global maxpage variable and render
        # only clickable pagination links.
        for a in soup.select('a[href*="page="]'):
            href = a.get("href") or ""
            if ("userdetails.php" in href or href.startswith("?")
                    or href.startswith("&")) and ("action=7" in href or "action=" not in href):
                page = re.search(r"[?&]page=(\d+)", href)
                if page:
                    max_page = max(max_page, int(page.group(1)))
        if max_page > 500:
            raise RuntimeError("站点完成页分页超过安全上限，拒绝返回可能不完整的列表")
        table = None
        for tb in soup.find_all("table"):
            header = tb.find("tr")
            if header and "种子ID" in header.get_text():
                table = tb
                break
        if not table:
            body = soup.get_text(" ", strip=True)
            if any(token in body for token in ("暂无保种", "没有保种", "无记录")):
                return items, max_page
            raise ValueError("未找到站点保种完成页表格，请确认 Cookie/页面未跳转")
        header_tr = table.find("tr")
        headers = [th.get_text(strip=True) for th in header_tr.find_all(["th", "td"])] if header_tr else []
        idx_size = 2
        idx_n = 3
        for i, h in enumerate(headers):
            if "大小" in h:
                idx_size = i
            if "初始保种" in h:
                idx_n = i
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) <= max(idx_size, idx_n):
                continue
            # The torrent title always comes from the second column; the
            # old idx_n-1 choice could land on the size column.
            a = tds[1].find("a")
            title = a.get_text(strip=True) if a else tds[1].get_text(strip=True)
            size = size_to_gb(tds[idx_size].get_text(strip=True))
            n_str = tds[idx_n].get_text(strip=True)
            try:
                n = int(n_str)
            except ValueError:
                n = 1
            if not size or tier_of(n) >= 99:
                continue
            seed_id = None
            try:
                sid_txt = tds[0].get_text(strip=True)
                seed_id = int(sid_txt) if sid_txt.isdigit() else None
            except Exception:
                pass
            # column indices: 0=ID,1=name,2=size,3=init,4=now,5=完成时间,6=上次结算,7=今日做种,8=今日达标
            now_seeders = 0
            try:
                now_seeders = int(tds[4].get_text(strip=True))
            except Exception:
                pass
            completed_at = tds[5].get_text(strip=True) if len(tds) > 5 else ""
            last_settle = tds[6].get_text(strip=True) if len(tds) > 6 else ""
            today_hours = tds[7].get_text(strip=True) if len(tds) > 7 else ""
            qualified = tds[8].get_text(strip=True) if len(tds) > 8 else ""
            items.append({
                "title": title, "size": size, "seeders": n, "seed_id": seed_id,
                "now_seeders": now_seeders,
                "completed_at": completed_at,
                "last_settle": last_settle,
                "today_hours": today_hours,
                "qualified": qualified,
            })
        return items, max_page

    def _get_manage_services(self) -> dict:
        if not self._downloaders:
            return {}
        out = {}
        try:
            all_sv = DownloaderHelper().get_services()
        except Exception:
            all_sv = None
        for name in self._downloaders:
            sv = None
            if all_sv:
                sv = all_sv.get(name)
            if sv is None:
                try:
                    got = DownloaderHelper().get_services(name_filters=[name])
                    sv = got.get(name) if got else None
                except Exception:
                    sv = None
            if not sv or not getattr(sv, "instance", None):
                continue
            try:
                if sv.instance.is_inactive():
                    continue
            except Exception:
                pass
            out[name] = sv
        return out

    def _fetch_all_downloader_torrents(self) -> list:
        out = []
        for name, sv in self._get_manage_services().items():
            try:
                ts, error = sv.instance.get_torrents()
                if error or not ts:
                    continue
                for t in ts:
                    out.append((name, t))
            except Exception:
                continue
        return out

    def _get_downloader_obj(self):
        name = self._push_downloader or (self._downloaders[0] if self._downloaders else "")
        if not name:
            return None
        try:
            services = DownloaderHelper().get_services(name_filters=[name])
            if not services:
                return None
            service = services.get(name)
            if not service or not service.instance:
                return None
            if service.instance.is_inactive():
                return None
            return service
        except Exception:
            return None

    @staticmethod
    def _extract_tracker_text(t, dl_type: str = "") -> str:
        """Best-effort extraction of Tracker announce URLs from MP V3 clients.

        TR's Torrent object may expose snake_case properties, camelCase
        fields or a raw mapping. Missing attributes must not discard other
        available tracker fields. Tracker availability is NOT an authorization
        prerequisite for manual bulk operations.
        """
        from collections.abc import Mapping

        def get_value(obj, key):
            if isinstance(obj, Mapping):
                return obj.get(key)
            try:
                value = getattr(obj, key, None)
                if value is not None and not callable(value):
                    return value
            except Exception:
                pass
            try:
                getter = getattr(obj, "get", None)
                if callable(getter):
                    return getter(key)
            except Exception:
                pass
            return None

        names = (
            "tracker", "trackers", "trackerList", "tracker_list",
            "trackerStats", "tracker_stats", "announce", "announceURL",
            "announce_url", "announceUrl", "url", "magnet_uri",
        )
        collected = []
        seen = set()

        def walk(value, depth=0):
            if value is None or depth > 3 or len(collected) >= 50:
                return
            if isinstance(value, (list, tuple, set)):
                for entry in value:
                    walk(entry, depth + 1)
                return
            if isinstance(value, str):
                # Ignore labels such as '** [DHT] **' and empty placeholders.
                if "://" in value and value not in seen:
                    collected.append(value)
                    seen.add(value)
                return
            if isinstance(value, Mapping):
                for name in names:
                    if name in value:
                        walk(value.get(name), depth + 1)
                return
            for name in names:
                inner = get_value(value, name)
                if inner is not None and inner is not value:
                    walk(inner, depth + 1)

        try:
            for key in names:
                walk(get_value(t, key))
            for holder in ("fields", "_fields", "data", "_data"):
                walk(get_value(t, holder))
        except Exception:
            return " ".join(collected)
        return " ".join(collected)

    @staticmethod
    def _get_progress_ratio(t, dl_type: str = "") -> Optional[float]:
        import math
        def get(*keys):
            for key in keys:
                try:
                    value = t.get(key) if isinstance(t, dict) else getattr(t, key, None)
                    if value is not None:
                        return value
                except Exception:
                    continue
            return None
        try:
            if "transmission" in str(dl_type).lower() or "tr_" in str(dl_type).lower():
                progress = get("percent_done", "percentDone")
                if progress is None:
                    value = get("progress")
                    progress = float(value) / 100 if value is not None else None
            else:
                progress = get("progress", "percent_done", "percentDone")
            value = float(progress)
            return value if math.isfinite(value) and 0 <= value <= 1 else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _is_completed(t, dl_type: str = "") -> bool:
        ratio = HHClubButler._get_progress_ratio(t, dl_type)
        def get(key):
            return t.get(key) if isinstance(t, dict) else getattr(t, key, None)
        try:
            state = str(get("state") or get("status") or "").lower()
            left = get("amount_left")
            if left is None:
                left = get("left_until_done")
            if left is None:
                left = get("leftUntilDone")
            if left is not None and float(left) > 0:
                return False
            if state in {"downloading", "download_pending", "checking", "checkingdl", "checkingup",
                         "stalleddl", "metadl", "missingfiles", "error", "moving", "allocating"}:
                return False
            return ratio == 1 if ratio is not None else state in {
                "seeding", "seed_pending", "stalledup", "uploading", "pausedup", "queuedup", "forcedup"}
        except (TypeError, ValueError, AttributeError):
            return False

    def _operation_allowed(self, generation=None) -> bool:
        expected = getattr(self, "_run_generation", self._delete_generation) if generation is None else generation
        return bool(self._enabled and not self._stopped and expected == self._delete_generation)

    @staticmethod
    def _safe_error(error) -> str:
        # Exceptions can contain full announce/download URLs, including credentials.
        text = re.sub(r"(?:https?|udp)://[^\s<>]+", "[URL已隐藏]", str(error), flags=re.I)
        text = re.sub(r"(?im)(header value\s*:)[^\r\n]*", r"\1[已隐藏]", text)
        return re.sub(r'''(?im)\b(cookie|passkey|token|password|authorization)["']?\s*[:=]\s*[^\r\n]*''',
                      r"\1=[已隐藏]", text)[:500]

    def _download_response(self, session, url: str):
        from urllib.parse import urljoin, urlsplit
        site = urlsplit(self._get_site_url())
        allowed = {site.hostname}
        if site.hostname in {"hhanclub.net", "hhancclub.net"}:
            allowed.update({"hhanclub.net", "hhancclub.net"})
        for _ in range(6):
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username
                    or parsed.password or parsed.port not in (None, 443)):
                raise ValueError("种子下载链接不属于受信站点 HTTPS 地址")
            response = session.get(url, timeout=60, allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                raise ValueError("种子下载跳转缺少目标")
            url = urljoin(url, location)
        raise ValueError("种子下载跳转次数过多")

    def _get_downloader_seeds(self, logs: list, only_completed: bool = True,
                             any_tracker: bool = False, torrents: Optional[list] = None) -> Optional[set]:
        services = self._get_manage_services()
        if not services or set(self._downloaders) - set(services):
            logs.append("管理下载器不完整，停止自动任务")
            return None
        names = set()
        try:
            for client, service in services.items():
                dl_type = str(getattr(service, "type", "") or getattr(service.config, "type", ""))
                if torrents is None:
                    remote, error = service.instance.get_torrents()
                    if error or remote is None:
                        return None
                else:
                    remote = [t for label, t in torrents if label == client]
                for torrent in remote:
                    if only_completed and not self._is_completed(torrent, dl_type):
                        continue
                    if not any_tracker and not is_trusted_hh_tracker(self._extract_tracker_text(torrent, dl_type)):
                        continue
                    name = self._torrent_field(torrent, "name")
                    if not name:
                        return None
                    names.add(str(name))
            return names
        except Exception as error:
            logs.append(f"下载器读取失败：{self._safe_error(error)}")
            return None

    def _push_seeds(self, seeds: list, logs: list):
        if self._download_options_error:
            return 0, len(seeds), [{"title": s.get("title", ""), "reason": self._download_options_error} for s in seeds]
        service = self._get_downloader_obj()
        if not service:
            logs.append("未配置有效的下载器，无法推送")
            return 0, len(seeds), [{"title": s.get("title", ""), "reason": "推送下载器不可用"} for s in seeds]
        dl_type = str(getattr(getattr(service, "config", None), "type", "") or getattr(service, "type", "")).lower()
        if (self._upload_limit or self._download_limit) and not any(name in dl_type for name in ("qbittorrent", "transmission")):
            return 0, len(seeds), [{"title": s.get("title", ""), "reason": "该下载器不支持本插件的单任务限速，未添加任务"} for s in seeds]
        session = self._session()
        limited_tr = "transmission" in dl_type and bool(self._upload_limit or self._download_limit)
        push_cookie = self._get_site_cookie() or None
        ok_count = 0
        fail_list = []
        for index, s in enumerate(seeds):
            if not self._operation_allowed():
                fail_list.extend({"title": pending.get("title", ""), "reason": "配置变化，未推送"} for pending in seeds[index:])
                break
            href = s.get("href", "")
            title = s.get("title", "")
            if not href:
                fail_list.append({"title": title, "reason": "缺少下载链接"})
                continue
            url = href if href.startswith("http") else f"{self._get_site_url()}/{href.lstrip('/')}"
            try:
                r = self._download_response(session, url)
                if not self._operation_allowed():
                    fail_list.extend({"title": pending.get("title", ""), "reason": "配置变化，未添加下载"} for pending in seeds[index:])
                    break
                if r.status_code == 200 and r.content:
                    kwargs = {}
                    failure_reason = ""
                    if self._tag:
                        if "qbittorrent" in dl_type:
                            kwargs["tag"] = self._tag
                        elif "transmission" in dl_type:
                            kwargs["labels"] = [self._tag]
                        else:
                            kwargs["tag"] = self._tag
                    # 修复跨盘/自定义保存路径不生效：qBittorrent 开启自动种子管理时会忽略
                    # 传入的 save_path，导致填了其他盘的路径仍落在默认盘。
                    # 对 qBittorrent 显式关闭自动管理（ignore_category_check=False），
                    # 使下载目录严格按"保存路径"配置生效；Transmission 无此问题，透传即可。
                    if "qbittorrent" in dl_type:
                        if self._upload_limit:
                            kwargs["upload_limit"] = self._upload_limit * 1024
                        if self._download_limit:
                            kwargs["download_limit"] = self._download_limit * 1024
                        result = service.instance.add_torrent(
                            content=r.content, download_dir=self._save_path or None,
                            cookie=push_cookie, ignore_category_check=False, **kwargs)
                        if isinstance(result, tuple):
                            success = bool(result[0]) if result else False
                        else:
                            success = bool(result)
                    else:
                        existing = set()
                        if limited_tr:
                            # shortcut: MP hides TR duplicate flags; exclude external concurrent adds when the host exposes provenance.
                            remote, error = service.instance.get_torrents()
                            if error or remote is None:
                                raise RuntimeError("无法读取 Transmission 任务，未添加或修改任务")
                            for task in remote:
                                infohash = str(self._torrent_field(task, "hashString", "hash_string", "hash") or "").lower()
                                if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash, re.I):
                                    raise RuntimeError("Transmission 清单缺少可靠 Hash，未添加或修改任务")
                                existing.add(infohash)
                            kwargs["is_paused"] = True
                        if not self._operation_allowed():
                            raise RuntimeError("配置已变化，未添加任务")
                        result = service.instance.add_torrent(
                            content=r.content, download_dir=self._save_path or None,
                            cookie=push_cookie, **kwargs)
                        success = result is not None if not isinstance(result, bool) else result
                        if success and limited_tr:
                            infohash = str(self._torrent_field(result, "hashString", "hash_string", "hash") or "").lower()
                            try:
                                if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", infohash, re.I):
                                    raise RuntimeError("添加结果缺少可靠 Hash，未继续设置或启动")
                                if infohash in existing:
                                    raise RuntimeError("Hash 已存在，未修改原任务的限速或启动状态")
                                if not self._operation_allowed():
                                    raise RuntimeError("配置已变化，未继续设置或启动")
                                if service.instance.change_torrent(hash_string=infohash,
                                        upload_limit=self._upload_limit, download_limit=self._download_limit) is not True:
                                    raise RuntimeError("限速设置未确认，未发送启动指令")
                                if not self._operation_allowed():
                                    raise RuntimeError("配置已变化，未发送启动指令")
                                if service.instance.start_torrents(ids=[infohash]) is not True:
                                    raise RuntimeError("启动结果未确认")
                            except Exception as error:
                                success = False
                                failure_reason = "添加请求已受理，后续状态需人工核对；不会自动重发：" + self._safe_error(error)
                    if success:
                        ok_count += 1
                        logs.append(f"✅ 已添加：{title}")
                    else:
                        fail_list.append({"title": title, "reason": failure_reason or "下载器拒绝添加"})
                else:
                    fail_list.append({"title": title, "reason": f"种子文件下载失败(HTTP {r.status_code})"})
            except Exception as e:
                fail_list.append({"title": title, "reason": f"推送异常：{self._safe_error(e)}"})
            time.sleep(1)
        return ok_count, len(seeds) - ok_count, fail_list


    def _delete_seeds(self, seeds: list, logs: list, auto_mode: str = "wash"):
        verified, removed = [], 0
        generation = getattr(self, "_run_generation", self._delete_generation)
        for seed in seeds:
            targets = tuple(sorted((str(c.get("downloader") or ""), str(c.get("hash") or "").lower())
                                   for c in seed.get("candidates", [])))
            if not targets or any(not client or not value for client, value in targets):
                logs.append("缺少下载器及 Hash 身份，拒绝跨下载器猜测删除")
                return {"verified": verified, "removed_count": removed, "success": False}
            if not self._operation_allowed(generation):
                return {"verified": verified, "removed_count": removed, "success": False}
            result = self._delete_rescue_group(seed_id=seed["seed_id"], title=seed["title"],
                targets=targets, generation=generation, request_id=f"auto-{time.time_ns()}", auto_mode=auto_mode)
            removed += result.get("removed_count", 0)
            logs.append(result.get("message", "删除状态待核对"))
            if result.get("state") != "verified":
                return {"verified": verified, "removed_count": removed, "success": False}
            verified.append(seed)
        return {"verified": verified, "removed_count": removed, "success": True}

    @staticmethod
    def _norm_match(name: str, targets: set) -> bool:
        n = HHClubButler._norm_title(name)
        if not n:
            return False
        if n in targets:
            return True
        if len(n) >= 15:
            for t in targets:
                if len(t) >= 15 and (n in t or t in n):
                    return True
        return False

    def _clean_stale_downloads(self, logs: list, seeds: list, extra_titles: set = None):
        if not self._operation_allowed():
            return 0
        try:
            rows = self._collect_rescue_seeds(strict_downloaders=True)
        except Exception as error:
            logs.append(f"自动清理无法完整核验：{self._safe_error(error)}")
            return 0
        threshold, stale = self._auto_clean_days * 86400, []
        for row in rows:
            copies = row.get("candidates", [])
            if (not row.get("can_delete_group") or not copies
                    or not all(copy.get("trusted_tracker") and copy.get("progress") is not None
                               and not copy.get("completed") and copy.get("added_timestamp", 0) > 0
                               and time.time() - copy["added_timestamp"] >= threshold for copy in copies)):
                continue
            stale.append(row)
        result = self._delete_seeds(stale, logs, auto_mode="stale")
        if not result["success"]:
            raise RuntimeError(f"自动清理部分完成或结果不确定，已核实移除 {result['removed_count']} 个；停止后续优选，禁止重发")
        logs.append(f"已核实移除超时未完成任务 {result['removed_count']} 个；磁盘状态需另行核对")
        return result["removed_count"]

    @staticmethod
    def _parse_seeder_range(raw) -> Optional[tuple]:
        if raw is None:
            return None
        s = str(raw).strip()
        if "-" in s:
            parts = s.split("-", 1)
            try:
                lo = int(parts[0].strip())
                hi = int(parts[1].strip())
                return (min(lo, hi), max(lo, hi))
            except (ValueError, IndexError):
                return None
        try:
            n = int(s)
            return (n, n)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _tier_sort_key(s: dict):
        return (tier_of(s.get("seeders", 1)), -s.get("size", 0.0))

    def _optimize_incremental(self, seeds: list, eff_target: float,
                              current_gb: float, logs: list) -> dict:
        cap = float("inf") if self._target_volume <= 0 else eff_target
        if cap <= 0:
            logs.append("当前保种体积已达目标，无需新增")
            return {"picked": [], "total_gb": 0.0, "del_seeds": []}
        candidates = sorted(seeds, key=HHClubButler._tier_sort_key)
        picked = []
        used = 0.0
        for s in candidates:
            if used + s["size"] <= cap + 1e-6:
                picked.append(s)
                used += s["size"]
        logs.append(f"增量优选：剩余可增 {cap:.1f} GB，按档位高→低补 {len(picked)} 个，新增 {used:.1f} GB")
        for s in picked[:8]:
            logs.append(f"  + {s.get('title','')} | {s.get('size',0.0):.1f} GB | "
                        f"初始做种 {s.get('seeders','?')} 人")
        if len(picked) > 8:
            logs.append(f"  …等共 {len(picked)} 个")
        return {"picked": picked, "total_gb": used, "del_seeds": []}

    def _optimize_wash(self, candidates: list, current: list,
                       eff_target: float, logs: list) -> dict:
        cap = self._target_volume
        if not cap or cap <= 0:
            logs.append("目标体积为0（不限），换种模式不删除任何种子")
            return {"picked": [], "del_seeds": [], "total_gb": 0.0, "keep_count": len(current)}
        cap = min(cap, sum(s.get("size", 0) for s in current) + max(0, eff_target))
        cur_titles = {s["title"] for s in current}
        # 从当前在保种子开始，默认全部保留
        final = list(current)
        total_gb = sum(s.get("size", 0.0) for s in final)
        # 新候选按档位优先级排序（高档位先处理，同档位大体积先）
        new_cands = [s for s in candidates if s["title"] not in cur_titles]
        new_cands.sort(key=lambda s: (tier_of(s.get("seeders", 1)), -s.get("size", 0.0)))
        del_map = {}
        for cand in new_cands:
            csize = cand.get("size", 0.0)
            if csize > cap:
                continue
            # 能直接放下就加
            if total_gb + csize <= cap + 1e-6:
                final.append(cand)
                total_gb += csize
                continue
            # 放不下：只踢比候选档位更低的种子（低档优先、小体积优先）
            cand_tier = tier_of(cand.get("seeders", 1))
            victims = [s for s in final
                       if s.get("auto_delete_ready") and tier_of(s.get("seeders", 1)) > cand_tier
                       and s["title"] not in del_map]
            victims.sort(key=lambda s: (-tier_of(s.get("seeders", 1)), s.get("size", 0.0)))
            evicted_this_round = []
            added = False
            for victim in victims:
                final.remove(victim)
                evicted_this_round.append(victim)
                total_gb -= victim["size"]
                if total_gb + csize <= cap + 1e-6:
                    final.append(cand)
                    total_gb += csize
                    for v in evicted_this_round:
                        del_map[v["title"]] = v
                    added = True
                    break
            if not added:
                # 回滚本次尝试踢掉的种子
                for v in evicted_this_round:
                    final.append(v)
                    total_gb += v.get("size", 0.0)
        del_seeds = list(del_map.values())
        add_seeds = [s for s in final if s["title"] not in cur_titles]
        keep_count = len(final) - len(add_seeds)
        logs.append(f"换种优选（体积上限 {cap:g} GB）：构建 {len(final)} 个"
                    f"（保留当前 {keep_count} + 新增 {len(add_seeds)}），"
                    f"删除低档位 {len(del_seeds)} 个，最终体积 {total_gb:.1f} GB")
        for s in add_seeds[:8]:
            logs.append(f"  + 新增: {s.get('title','')} | {s.get('size',0.0):.1f} GB | "
                        f"初始做种 {s.get('seeders','?')} 人")
        if len(add_seeds) > 8:
            logs.append(f"  …等共 {len(add_seeds)} 个新增")
        for s in del_seeds[:8]:
            logs.append(f"  - 删除: {s.get('title','')} | {s.get('size',0.0):.1f} GB | "
                        f"初始做种 {s.get('seeders','?')} 人")
        if len(del_seeds) > 8:
            logs.append(f"  …等共 {len(del_seeds)} 个删除")
        return {"picked": add_seeds, "del_seeds": del_seeds,
                "total_gb": total_gb, "keep_count": keep_count}

    def _save_log(self, logs: list):
        try:
            path = self.get_data_path()
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            with open(path / "run_log.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(logs))
        except Exception as e:
            logger.error(f"保存日志失败：{HHClubButler._safe_error(e)}")

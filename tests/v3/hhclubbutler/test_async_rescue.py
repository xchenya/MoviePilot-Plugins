"""Regression tests for 524-safe polling, cache coalescing and stale-worker isolation.

Tests execute selected Python methods without importing MoviePilot or contacting trackers.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import runpy
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SUPPORT = __import__("runpy").run_path(str(Path(__file__).with_name("support.py")))

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3" / "hhclubbutler" / "__init__.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _method(name: str):
    tree = ast.parse(_source())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef)
               and x.name == "HHClubButler")
    node = next(x for x in cls.body if isinstance(x, ast.FunctionDef)
                and x.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(node)],
                                                 type_ignores=[]))
    helpers = runpy.run_path(str(ROOT / "plugins.v3/hhclubbutler/matching.py"))
    associate = helpers["associate_rescue_seeds"]
    namespace = {"HHClubButler": SUPPORT["Subject"], "time": time, "threading": threading, "datetime": datetime, "json": json,
                 "re": re, "associate_rescue_seeds": associate,
                 "is_trusted_hh_tracker": helpers["is_trusted_hh_tracker"],
                 "logger": SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())}
    exec(compile(module, f"<isolated:{name}>", "exec"), namespace)
    return namespace[name]


def _fixture():
    fake = SimpleNamespace(
        _enabled=True, _stopped=False,
        _list_lock=threading.Lock(),
        _list_state="idle", _list_cache=None,
        _list_updated_at=0.0, _list_started_at=0.0,
        _list_finished_at=0.0, _list_error="", _list_generation=0,
        _list_thread=None, _list_cache_ttl=180.0, _list_warning="",
    )
    fake._list_rescue_worker = lambda generation, downloaders=(): _method("_list_rescue_worker")(fake, generation, downloaders)
    return SUPPORT["enrich"](fake)


def test_first_read_returns_loading_without_blocking_and_coalesces_requests():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    fetched = threading.Event()
    finish = threading.Event()
    counter = []

    def collect(**kwargs):
        counter.append("started")
        fetched.set()
        assert finish.wait(5), "fixture worker should have been released"
        return [{"title": "Example.Movie", "size": 4.2, "seeders": 1}]

    fake._collect_rescue_seeds = collect
    first = api(fake)
    assert first["success"] is True and first["loading"] is True
    assert fetched.wait(2)
    for _ in range(5):
        poll = api(fake)
        assert poll["success"] and poll["loading"] and poll.get("data") is None
    assert len(counter) == 1, "polling must never multiply expensive jobs"
    finish.set()
    fake._list_thread.join(timeout=5)
    assert not fake._list_thread.is_alive()
    ready = api(fake)
    assert ready["success"] and ready["loading"] is False
    assert ready["data"][0]["title"] == "Example.Movie"
    assert ready["updated_at"]
    assert len(counter) == 1, "fresh cache must bypass backend fetching"


def test_fetch_error_is_explicit_and_retry_is_controlled():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    calls = []
    def broken(**kwargs):
        calls.append(1)
        raise RuntimeError("pretend remote is unavailable")

    fake._collect_rescue_seeds = broken
    assert api(fake)["loading"] is True
    fake._list_thread.join(timeout=5)
    response = api(fake)
    assert response["success"] is False
    assert "Cookie" in response["message"]
    assert len(calls) == 1
    assert api(fake)["success"] is False
    assert len(calls) == 1, "retries should be rate-limited"
    fake._collect_rescue_seeds = lambda **kwargs: [{"title": "Recovered", "size": 2.0}]
    assert api(fake, refresh=True)["loading"] is True
    fake._list_thread.join(timeout=5)
    assert api(fake)["data"][0]["title"] == "Recovered"


def test_worker_from_old_generation_cannot_publish_after_stop():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    started, finish = threading.Event(), threading.Event()

    def slow(**kwargs):
        started.set()
        assert finish.wait(5)
        return [{"title": "Stale", "size": 99}]

    fake._collect_rescue_seeds = slow
    assert api(fake)["loading"]
    assert started.wait(2)
    with fake._list_lock:
        fake._stopped = True
        fake._list_generation += 1
        fake._list_state = "idle"
    finish.set()
    fake._list_thread.join(timeout=5)
    assert fake._list_cache is None
    assert api(fake)["success"] is False


def test_refetch_explicitly_refreshes_cached_data():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    fake._list_cache = [{"title": "A"}]
    fake._list_state = "ready"
    fake._list_updated_at = time.time()
    assert api(fake)["data"][0]["title"] == "A"
    fake._collect_rescue_seeds = lambda **kwargs: [{"title": "B", "size": 1}]
    assert api(fake, refresh=True)["loading"] is True
    fake._list_thread.join(timeout=5)
    assert api(fake)["data"][0]["title"] == "B"


def test_ui_uses_short_polling_and_detail_page_has_no_blocking_fetch():
    code = _source()
    assert "async function load(force,downloaders)" in code
    assert "if(j.loading)" in code
    assert "list_rescue_seeds" in code
    assert "setTimeout(function(){ctl.abort()},15000)" in code
    assert "if(elapsed()>480)" in code
    plugin = next(x for x in ast.parse(code).body
                  if isinstance(x, ast.ClassDef) and x.name == "HHClubButler")
    overview = next(x for x in plugin.body
                    if isinstance(x, ast.FunctionDef)
                    and x.name == "_get_overview_cached_or_refresh")
    assert "self._refresh_overview()" not in ast.get_source_segment(code, overview)
    assert "API_TOKEN" not in code
    assert "?apikey=" not in code


def _fake_services(items_by_name):
    out = {}
    for name, (items, error) in items_by_name.items():
        out[name] = SimpleNamespace(
            type="qbittorrent",
            config=SimpleNamespace(type="qbittorrent"),
            instance=SimpleNamespace(get_torrents=lambda values=items, err=error: (values, err)))
    return out


def _site_fixture():
    fake = SimpleNamespace(
        _downloaders=["A", "B"], _list_warning="",
        _fetch_completed=lambda logs: [
            {"title": "Same.Title", "size": 8.0, "seed_id": 1},
            {"title": "Unique.Title", "size": 9.0, "seed_id": 2},
            {"title": "Unique.Title.Extra", "size": 10.0, "seed_id": 3},
        ],
        _norm_title=lambda name: str(name).lower().replace(".", ""),
        _append_downloader_incomplete=lambda rows, torrents: rows,
        _get_progress_ratio=lambda torrent, dltype: 1.0,
        _extract_tracker_text=lambda torrent, dltype: "https://hhanclub.net/announce",
    )
    return SUPPORT["enrich"](fake)


def test_site_rows_survive_missing_or_ambiguous_downloader_associations():
    collect = _method("_collect_rescue_seeds")
    fake = _site_fixture()
    fake._get_manage_services = lambda: _fake_services({
        "A": ([{"name": "Same.Title", "hash": "1111111111111111111111111111111111111111", "size": 8*1073741824},
               {"name": "Unique.Title", "hash": "3333333333333333333333333333333333333333", "size": 9*1073741824}], False),
        "B": ([{"name": "Same.Title", "hash": "2222222222222222222222222222222222222222", "size": 8*1073741824}], False),
    })
    result = collect(fake)
    assert len(result) == 3
    assert [x["seed_id"] for x in result] == [1, 2, 3]
    assert result[0]["match_status"] == "cross_seed"
    assert result[0]["can_delete"] is False
    assert result[0]["cross_seed_count"] == 2
    assert result[1]["downloader"] == "A"
    assert result[1]["can_manage"] is True
    assert result[2]["match_status"] == "unmatched"


def test_no_downloaders_still_shows_every_site_eligible_row():
    collect = _method("_collect_rescue_seeds")
    fake = _site_fixture()
    fake._get_manage_services = lambda: {}
    result = collect(fake)
    assert len(result) == 3
    assert not any(s["can_delete"] for s in result)
    assert "未选择" in fake._list_warning


def test_downloader_error_does_not_erase_site_inventory():
    collect = _method("_collect_rescue_seeds")
    fake = _site_fixture()
    fake._get_manage_services = lambda: _fake_services({
        "A": (None, True), "B": ([], False),
    })
    result = collect(fake)
    assert len(result) == 3
    assert all(s["match_status"] == "unmatched" for s in result)
    assert "读取失败" in fake._list_warning


def test_unreadable_site_fails_closed_rather_than_reusing_partial_data():
    collect = _method("_collect_rescue_seeds")
    fake = _site_fixture()
    def fails(logs):
        logs.append("站点完成页第2页获取失败")
        return []
    fake._fetch_completed = fails
    fake._get_manage_services = lambda: {}
    try:
        collect(fake)
    except RuntimeError as error:
        assert "不完整" in str(error)
    else:
        raise AssertionError("the site error was ignored")

def test_market_metadata_marks_patch_release_unpublished():
    import json
    manifest = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = manifest["HHClubButler"]
    assert entry["version"] == "3.0.12"
    assert entry["release"] is False
    assert "3.0.12" in entry["history"]



"""Regression tests for 524-safe polling, cache coalescing and stale-worker isolation.

Tests execute selected Python methods without importing MoviePilot or contacting trackers.
"""
from __future__ import annotations

import ast
import copy
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
    namespace = {"time": time, "threading": threading, "datetime": datetime,
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
        _list_thread=None, _list_cache_ttl=180.0,
    )
    fake._list_rescue_worker = lambda generation: _method("_list_rescue_worker")(fake, generation)
    return fake


def test_first_read_returns_loading_without_blocking_and_coalesces_requests():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    fetched = threading.Event()
    finish = threading.Event()
    counter = []

    def collect():
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
    def broken():
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
    fake._collect_rescue_seeds = lambda: [{"title": "Recovered", "size": 2.0}]
    assert api(fake, refresh=True)["loading"] is True
    fake._list_thread.join(timeout=5)
    assert api(fake)["data"][0]["title"] == "Recovered"


def test_worker_from_old_generation_cannot_publish_after_stop():
    api = _method("api_list_rescue_seeds")
    fake = _fixture()
    started, finish = threading.Event(), threading.Event()

    def slow():
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
    fake._collect_rescue_seeds = lambda: [{"title": "B", "size": 1}]
    assert api(fake, refresh=True)["loading"] is True
    fake._list_thread.join(timeout=5)
    assert api(fake)["data"][0]["title"] == "B"


def test_ui_uses_short_polling_and_detail_page_has_no_blocking_fetch():
    code = _source()
    assert "async function load(force)" in code
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


def test_snapshot_matches_exact_names_only_and_avoids_ambiguous_hashes():
    collect = _method("_collect_rescue_seeds")
    fake = SimpleNamespace()
    fake._norm_title = lambda name: name.lower().replace(".", "").strip()
    fake._get_manage_services = lambda: {
        "A": SimpleNamespace(instance=SimpleNamespace(get_torrents=lambda: (
            [{"name": "Same.Title", "hash": "1"},
             {"name": "Unique.Title", "hash": "3"}], None))),
        "B": SimpleNamespace(instance=SimpleNamespace(get_torrents=lambda: (
            [{"name": "Same.Title", "hash": "2"}], None))),
    }
    fake._get_current_seeding = lambda logs, torrents: {
        "seeds": [{"title": "Same.Title"}, {"title": "Unique.Title"},
                  {"title": "Unique.Title.Extra"}]
    }
    fake._get_downloader_detail_map = lambda torrents: {
        "sametitle": {"hash": "2", "downloader": "B"},
        "uniquetitle": {"hash": "3", "downloader": "A"},
    }
    data = collect(fake)
    assert "hash" not in data[0]
    assert data[1]["hash"] == "3" and data[1]["downloader"] == "A"
    assert len(data) == 2, "fuzzy-only site records must not appear as still seeding"
    assert all(row["title"] != "Unique.Title.Extra" for row in data)


def test_market_metadata_marks_patch_release_unpublished():
    import json
    manifest = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = manifest["HHClubButler"]
    assert entry["version"] == "3.0.3"
    assert entry["release"] is False
    assert "3.0.3" in entry["history"]


def test_zero_torrents_must_not_become_site_completed_seeds():
    collect = _method("_collect_rescue_seeds")
    fake = SimpleNamespace()
    fake._get_manage_services = lambda: {
        "QB": SimpleNamespace(instance=SimpleNamespace(
            get_torrents=lambda: ([], None)))}
    fake._norm_title = lambda name: str(name).lower()
    def current(logs, torrents=None):
        # Old bug: None was mistaken for "all site completed torrents".
        if torrents is None:
            return {"seeds": [{"title": "Already.Deleted"}]}
        return {"seeds": []}
    fake._get_current_seeding = current
    fake._get_downloader_detail_map = lambda torrents=None: {}
    assert collect(fake) == []


def test_unavailable_downloader_does_not_report_zero_seeds():
    collect = _method("_collect_rescue_seeds")
    fake = SimpleNamespace()
    fake._get_manage_services = lambda: {
        "QB": SimpleNamespace(instance=SimpleNamespace(
            get_torrents=lambda: (None, "connection failed")))}
    try:
        collect(fake)
    except RuntimeError as exc:
        assert "下载器" in str(exc)
    else:
        raise AssertionError("failed downloader must not appear as empty")

"""Asynchronous deletion: exactly-once admission, safe outcomes, and custom modal.

These tests extract actual methods from the V3 plugin; they never contact a
real MoviePilot instance or a real download client.
"""
from __future__ import annotations

import ast
import copy
import runpy
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/hhclubbutler/__init__.py"

def _source():
    return SOURCE.read_text(encoding="utf-8")

def _subject():
    original = next(n for n in ast.parse(_source()).body
                    if isinstance(n, ast.ClassDef) and n.name == "HHClubButler")
    chosen = {"_delete_job_view", "_invalidate_rescue_cache",
              "api_delete_rescue_seed", "api_delete_rescue_status",
              "_delete_rescue_worker", "_delete_rescue_exact"}
    members = [copy.deepcopy(n) for n in original.body
               if isinstance(n, ast.FunctionDef) and n.name in chosen]
    assert len(members) == len(chosen)
    cls = ast.ClassDef(name="DeleteSubject", bases=[], keywords=[],
                       body=members, decorator_list=[])
    namespace = {"threading": threading, "time": time, "re": re,
                 "logger": SimpleNamespace(info=Mock(), error=Mock())}
    helpers=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    namespace.update({name: helpers[name] for name in
                      ("normalize_name","translated_release_key",
                       "translated_size_matches","is_trusted_hh_tracker")})
    mod = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(mod, "<delete-test>", "exec"), namespace)
    return namespace["DeleteSubject"]

def _fixture():
    instance = _subject()()
    instance._enabled = True
    instance._stopped = False
    instance._downloaders = ["QB"]
    instance._delete_lock = threading.Lock()
    instance._delete_jobs = {}
    instance._delete_active_id = None
    instance._delete_generation = 0
    instance._run_lock = threading.Lock()
    instance._list_lock = threading.Lock()
    instance._list_generation = 0
    instance._list_state = "ready"
    instance._list_cache = [{"title": "Old.Movie", "downloader": "QB",
                             "hash": "HASH123"}]
    instance._list_updated_at = time.time()
    instance._list_error = ""
    instance._collect_rescue_seeds = lambda strict_downloaders=False: [
        {"title": "Old.Movie", "size": 8.0, "downloader": "QB",
         "hash": "HASH123", "can_delete": True, "match_status": "exact",
         "candidates": [{"downloader": "QB", "hash": "HASH123",
                         "can_remove": True, "can_delete_files": True,
                         "match_type": "exact"}]}]
    instance._last_overview = {"count": 1}
    instance._last_overview_ts = time.time()
    return instance

REQ_ID = "a7ab618f-1300-4551-bb7c-aba7e323d077"
OTHER_ID = "cb982a2e-778a-41e0-9c71-31f2ec19a738"

def _submit(host, request_id=REQ_ID, **kwargs):
    args = dict(title="Old.Movie", downloader="QB",
                torrent_hash="HASH123", confirm=True, request_id=request_id)
    args.update(kwargs)
    return host.api_delete_rescue_seed(**args)

def _done(host, request_id=REQ_ID):
    end = time.time() + 4
    while time.time() < end:
        result = host.api_delete_rescue_status(request_id=request_id)
        if result["success"] and result["data"]["status"] not in ("queued", "running"):
            return result["data"]
        time.sleep(0.01)
    raise AssertionError("background operation failed to complete")

def test_single_worker_deduplicates_post_and_keeps_results_readonly():
    host = _fixture()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def mocked(*args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        assert release.wait(3)
        return {"success": True, "state": "verified", "message": "已确认删除"}
    host._delete_rescue_exact = mocked
    first = _submit(host)
    assert first["success"]
    assert entered.wait(1)
    for _ in range(4):
        assert _submit(host)["success"]
    assert len(calls) == 1
    busy = _submit(host, request_id=OTHER_ID)
    assert busy["success"] is False
    assert "执行" in busy["message"]
    assert host.api_delete_rescue_status(REQ_ID)["data"]["status"] == "running"
    release.set()
    done = _done(host)
    assert done["status"] == "verified"
    assert len(calls) == 1
    for _ in range(4):
        assert host.api_delete_rescue_status(REQ_ID)["data"]["status"] == "verified"
    assert len(calls) == 1
    assert host._list_cache is None
    assert host._list_state == "idle"
    assert host._list_generation == 1
    assert host._last_overview is None

def test_reused_id_for_another_target_is_rejected_without_new_delete():
    host = _fixture()
    host._delete_rescue_exact = Mock(return_value={"success":False,
                                                     "state":"failed","message":"mock"})
    assert _submit(host)["success"]
    assert _done(host)["status"] == "failed"
    response = _submit(host, title="Different.Movie")
    assert response["success"] is False
    assert host._delete_rescue_exact.call_count == 1
    assert host._list_cache is not None

def test_failed_and_uncertain_status_not_mistaken_for_verified():
    host = _fixture()
    host._delete_rescue_exact = Mock(return_value={"success":False,
                                                     "state":"uncertain","message":"查无结果"})
    assert _submit(host)["success"]
    assert _done(host)["status"] == "uncertain"
    assert host._list_cache is None
    assert host._delete_rescue_exact.call_count == 1
    assert _submit(host)["data"]["status"] == "uncertain"
    assert host._delete_rescue_exact.call_count == 1

def test_invalid_request_or_disabled_plugin_cannot_start_job():
    host = _fixture()
    host._delete_rescue_exact = Mock()
    assert not _submit(host, request_id="tiny")["success"]
    assert not _submit(host, confirm=False)["success"]
    assert not _submit(host, downloader="UNKNOWN")["success"]
    host._stopped = True
    assert not _submit(host)["success"]
    host._delete_rescue_exact.assert_not_called()
    assert host.api_delete_rescue_status("none")["success"] is False

def test_exact_delete_waits_for_hash_to_disappear_from_downloader():
    host = _fixture()
    host._norm_title = lambda s: (s or "").lower().replace(".", "")
    host._extract_tracker_text = lambda t: t.get("tracker", "")
    host._get_current_seeding = lambda logs: {"seeds":[{"title":"Old.Movie"}]}
    delete = Mock(return_value=True)
    torrent = {"name":"Old.Movie","hash":"HASH123","tracker":"https://tracker.hhanclub.net/announce"}
    host._get_manage_services = lambda: {"QB": SimpleNamespace(instance=SimpleNamespace(
        get_torrents=lambda: (([] if delete.called else [torrent]), None),
        delete_torrents=delete))}
    result = host._delete_rescue_exact("Old.Movie","QB","HASH123",True,host._delete_generation)
    assert result["success"] and result["state"] == "verified"
    delete.assert_called_once_with(delete_file=True,ids=["HASH123"])

def test_delete_not_reissued_when_downloader_returns_false():
    host = _fixture()
    host._norm_title = lambda s: (s or "").lower().replace(".", "")
    host._extract_tracker_text = lambda t: t.get("tracker", "")
    host._get_current_seeding = lambda logs: {"seeds":[{"title":"Old.Movie"}]}
    delete = Mock(return_value=False)
    torrent = {"name":"Old.Movie","hash":"HASH123","tracker":"https://tracker.hhanclub.net/announce"}
    host._get_manage_services = lambda: {"QB": SimpleNamespace(instance=SimpleNamespace(
        get_torrents=lambda: ([torrent],None),delete_torrents=delete))}
    result = host._delete_rescue_exact("Old.Movie","QB","HASH123",True,host._delete_generation)
    assert result["state"] == "uncertain"
    delete.assert_called_once()

def test_reconfiguration_aborts_before_side_effect():
    host = _fixture()
    host._norm_title = lambda s: (s or "").lower().replace(".", "")
    host._extract_tracker_text = lambda t: t.get("tracker", "")
    host._get_current_seeding = lambda logs: {"seeds":[{"title":"Old.Movie"}]}
    delete = Mock(return_value=True)
    torrent = {"name":"Old.Movie","hash":"HASH123","tracker":"https://tracker.hhanclub.net/announce"}
    host._get_manage_services = lambda: {"QB": SimpleNamespace(instance=SimpleNamespace(
        get_torrents=lambda: ([torrent],None),delete_torrents=delete))}
    host._delete_generation = 2
    result = host._delete_rescue_exact("Old.Movie","QB","HASH123",True,generation=1)
    assert result["success"] is False
    delete.assert_not_called()

def test_custom_dialog_and_refresh_controls_without_native_alerts():
    code = _source()
    cls = next(n for n in ast.parse(code).body if isinstance(n, ast.ClassDef)
               and n.name=="HHClubButler")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name=="_build_rescue_panel_html")
    page = ast.get_source_segment(code,method)
    assert 'id="btnRefresh"' in page
    assert 'id="hhConfirmOverlay"' in page
    assert 'role="dialog"' in page
    assert 'aria-live="polite"' in page
    assert 'async function pollDeleteStatus(id)' in page
    assert "resumePendingDelete()" in page
    assert 'load(true)' in page
    assert "alert(" not in page and "confirm(" not in page
    assert "window.confirm" not in page
    assert "delete_rescue_status?request_id=" in page
    assert 'request_id:id' in page
    assert 'getElementById("hhConfirmDesc")' in page
    assert ".textContent=" in page

def test_status_route_is_admin_protected_and_uses_get():
    code=_source()
    cls=next(n for n in ast.parse(code).body if isinstance(n,ast.ClassDef)
             and n.name=="HHClubButler")
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                and n.name=="get_api")
    api=ast.get_source_segment(code,method)
    assert '"/delete_rescue_status"' in api
    assert '"methods": ["GET"], "allow_anonymous": True, "dependencies": page_deps' in api
    assert '"/delete_rescue_seed"' in api
    assert '"methods": ["POST"], "allow_anonymous": True, "dependencies": page_deps' in api


def test_readback_without_hash_is_uncertain_not_verified():
    host = _fixture()
    host._norm_title = lambda s: (s or "").lower().replace(".", "")
    host._extract_tracker_text = lambda t: t.get("tracker", "")
    host._get_current_seeding = lambda logs: {"seeds": [{"title": "Old.Movie"}]}
    deletion = Mock(return_value=True)
    record = {"name": "Old.Movie", "hash": "HASH123",
              "tracker": "https://tracker.hhanclub.net/announce"}
    client = SimpleNamespace(
        get_torrents=lambda: (([{"name": "Other.Movie"}] if deletion.called
                               else [record]), None),
        delete_torrents=deletion,
    )
    host._get_manage_services = lambda: {"QB": SimpleNamespace(instance=client)}
    result = host._delete_rescue_exact("Old.Movie", "QB", "HASH123", True)
    assert result["state"] == "uncertain"
    assert not result["success"]
    deletion.assert_called_once()

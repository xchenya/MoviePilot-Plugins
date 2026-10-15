"""Listing refreshes never issue a real downloader write or fetch a live site."""
import copy
from pathlib import Path
import runpy
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

Subject = runpy.run_path(str(Path(__file__).with_name("support.py")))["Subject"]
TITLE = "Example Release 2026 1080p WEB-DL"
A, B = "a" * 40, "b" * 40


def fixture():
    obj = Subject()
    obj._enabled = True
    obj._downloaders = ["QB", "TR"]
    raw = {"name": TITLE, "hash": A, "total_size": 8 * 1073741824,
           "progress": 1, "state": "seeding"}
    qb = NS(get_torrents=Mock(return_value=([raw], False)), delete_torrents=Mock())
    tr = NS(get_torrents=Mock(return_value=([], False)), delete_torrents=Mock())
    obj._get_manage_services = lambda: {
        "QB": NS(instance=qb, type="qbittorrent", config=NS(type="qbittorrent")),
        "TR": NS(instance=tr, type="transmission", config=NS(type="transmission")),
    }
    obj._fetch_completed = Mock(return_value=[{"seed_id": 42, "title": TITLE, "size": 8, "seeders": 1}])
    return obj, qb, tr


def read(obj, **kwargs):
    response = obj.api_list_rescue_seeds(**kwargs)
    if response.get("loading"):
        obj._list_thread.join(timeout=3)
        assert not obj._list_thread.is_alive()
        response = obj.api_list_rescue_seeds(downloaders=kwargs.get("downloaders", ""))
    return response


def test_qb_only_refresh_reuses_site_and_tr_and_preserves_eligibility():
    obj, qb, tr = fixture()
    first = read(obj)
    assert first["data"][0]["cross_seed_count"] == 1
    obj._invalidate_rescue_cache()  # Same transition as a completed deletion.
    qb.get_torrents.return_value = ([], False)
    response = read(obj, refresh=True, downloaders='["QB"]')
    assert response["success"]
    assert response["data"][0]["seed_id"] == 42
    assert response["data"][0]["candidates"] == []
    assert qb.get_torrents.call_count == 2
    assert tr.get_torrents.call_count == 1
    assert obj._fetch_completed.call_count == 1
    qb.delete_torrents.assert_not_called()
    tr.delete_torrents.assert_not_called()


def test_deleted_downloader_only_record_is_absent_after_targeted_read():
    obj, qb, _ = fixture()
    obj._fetch_completed.return_value = []
    qb.get_torrents.return_value[0][0].update(progress=.4, state="downloading")
    assert read(obj)["data"][0]["source"] == "downloader"
    qb.get_torrents.return_value = ([], False)
    assert read(obj, refresh=True, downloaders='["QB"]')["data"] == []
    assert obj._fetch_completed.call_count == 1


def test_ten_hashes_in_nine_groups_remain_ten_tasks_with_no_api_duplicates():
    obj, qb, _ = fixture()
    sites, tasks = [], []
    for i in range(9):
        name = f"Example Release {i} 2026 1080p WEB-DL"
        sites.append({"seed_id": i + 1, "title": name, "size": 8, "seeders": 1})
        tasks.append({"name": name, "hash": f"{i:040x}", "total_size": 8 * 1073741824,
                      "progress": 1, "state": "seeding"})
    tasks.append(dict(tasks[0], hash=B))
    qb.get_torrents.return_value = (tasks + [copy.deepcopy(tasks[0])], False)
    obj._fetch_completed.return_value = sites
    rows = read(obj)["data"]
    assert len(rows) == 9
    assert sum(row["cross_seed_count"] for row in rows) == 10


def test_failed_qb_read_stays_an_error_instead_of_serving_old_cache_as_fresh():
    obj, qb, tr = fixture()
    read(obj)
    previous = obj._list_snapshot
    qb.get_torrents.return_value = ([], True)
    response = read(obj, refresh=True, downloaders='["QB"]')
    assert not response["success"] and "更新下载器失败" in response["message"]
    assert obj._list_snapshot is previous
    assert tr.get_torrents.call_count == 1
    assert obj._fetch_completed.call_count == 1
    obj._list_finished_at = time.time() - 31
    qb.get_torrents.return_value = ([], False)
    recovered = read(obj, downloaders='["QB"]')
    assert recovered["success"] and recovered["data"][0]["candidates"] == []
    assert qb.get_torrents.call_count == 3, "expired error must trigger a new read, not serve stale cache"


def test_unavailable_unrequested_client_keeps_its_snapshot_without_being_read():
    obj, qb, tr = fixture()
    tr.get_torrents.return_value = ([{"name": TITLE, "hashString": B, "totalSize": 8 * 1073741824,
                                     "percentDone": 1, "status": "seeding"}], False)
    assert read(obj)["data"][0]["cross_seed_count"] == 2
    services = obj._get_manage_services()
    obj._get_manage_services = lambda: {"QB": services["QB"]}
    qb.get_torrents.return_value = ([], False)
    response = read(obj, refresh=True, downloaders='["QB"]')
    assert response["success"]
    assert response["data"][0]["candidates"][0]["downloader"] == "TR"
    assert qb.get_torrents.call_count == 2 and tr.get_torrents.call_count == 1


@pytest.mark.parametrize("names", ['["Unknown"]', '[]', '{}', 'null', '[1]', 'not-json'])
def test_invalid_scope_is_rejected_before_any_io(names):
    obj, qb, _ = fixture()
    assert not obj.api_list_rescue_seeds(refresh=True, downloaders=names)["success"]
    obj._fetch_completed.assert_not_called()
    qb.get_torrents.assert_not_called()


def test_partial_read_without_snapshot_does_not_silently_fetch_the_site():
    obj, qb, _ = fixture()
    response = obj.api_list_rescue_seeds(refresh=True, downloaders='["QB"]')
    assert not response["success"] and "完整列表" in response["message"]
    obj._fetch_completed.assert_not_called()
    qb.get_torrents.assert_not_called()


def test_manual_full_refresh_and_strict_delete_reads_never_reuse_display_snapshot():
    obj, _, _ = fixture()
    read(obj)
    read(obj, refresh=True)
    obj._collect_rescue_seeds(strict_downloaders=True)
    assert obj._fetch_completed.call_count == 3
    with pytest.raises(ValueError, match="删除核验不能使用"):
        obj._collect_rescue_seeds(strict_downloaders=True, snapshot=obj._list_snapshot,
                                  refresh_downloaders=("QB",))


def test_stop_discards_inflight_partial_snapshot():
    obj, qb, _ = fixture()
    read(obj)
    started, finish = threading.Event(), threading.Event()
    def slow():
        started.set()
        assert finish.wait(3)
        return [], False
    qb.get_torrents.side_effect = slow
    assert obj.api_list_rescue_seeds(refresh=True, downloaders='["QB"]')["loading"]
    worker = obj._list_thread
    assert started.wait(2)
    obj.stop_service()
    finish.set()
    worker.join(timeout=3)
    assert obj._list_snapshot is None and obj._list_cache is None


def test_concurrent_client_scopes_are_coalesced_without_dropping_the_second_client():
    obj, qb, tr = fixture()
    read(obj)
    started, finish = threading.Event(), threading.Event()
    def slow():
        started.set()
        assert finish.wait(3)
        return [], False
    qb.get_torrents.side_effect = slow
    assert obj.api_list_rescue_seeds(refresh=True, downloaders='["QB"]')["loading"]
    assert started.wait(2)
    worker = obj._list_thread
    assert obj.api_list_rescue_seeds(refresh=True, downloaders='["TR"]')["loading"]
    assert worker is obj._list_thread
    finish.set()
    worker.join(timeout=3)
    assert read(obj)["success"]
    assert qb.get_torrents.call_count == 2 and tr.get_torrents.call_count == 2
    assert obj._fetch_completed.call_count == 1


def test_cache_invalidation_finishes_before_terminal_deletion_status_is_visible():
    obj, _, _ = fixture()
    read(obj)
    request = "scoped-refresh-1234"
    obj._delete_jobs[request] = {"status": "queued", "seed_id": 42, "title": TITLE,
                                 "targets": (("QB", A),)}
    obj._delete_rescue_group = Mock(return_value={"state": "verified", "removed_count": 1})
    invalidate = obj._invalidate_rescue_cache
    def check():
        assert obj._delete_jobs[request]["status"] == "running"
        invalidate()
    obj._invalidate_rescue_cache = check
    obj._delete_rescue_group_worker(request, obj._delete_generation)
    assert obj._delete_jobs[request]["status"] == "verified"
    assert obj._list_cache is None and obj._list_snapshot is not None

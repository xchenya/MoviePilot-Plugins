"""Whole-call-chain regressions; only in-memory clients and isolated plugin state."""
from __future__ import annotations
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import runpy
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from bs4 import BeautifulSoup

LIB = runpy.run_path(str(Path(__file__).with_name("support.py")))
Subject = LIB["Subject"]
TITLE = "A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TRANSLATED = "上古情歌." + TITLE.replace(" ", ".")
A, B, C = "a" * 40, "b" * 40, "c" * 40
TRACKER = "https://tracker.hhanclub.net/announce"


def torrent(infohash=A, name=TITLE, progress=1, path="/fixture", tracker=TRACKER):
    return {"hash": infohash, "name": name, "total_size": round(41.34 * 1073741824),
            "progress": progress, "state": "seeding" if progress == 1 else "downloading",
            "save_path": path, "tracker": tracker, "added_on": time.time() - 3 * 86400}


class Client:
    def __init__(self, tasks):
        self.tasks = copy.deepcopy(tasks)
        self.files = {t["hash"]: [{"name": "release/payload.mkv"}] for t in tasks}
        self.calls = []
        self.accept = True
        self.readback = None
        self.partial = False

    def get_torrents(self):
        if self.calls and self.readback:
            return self.readback()
        return copy.deepcopy(self.tasks), False

    def get_files(self, infohash):
        return self.files.get(infohash)

    def delete_torrents(self, *, delete_file, ids):
        self.calls.append((delete_file, list(ids)))
        if self.accept:
            removed = set(ids[:1] if self.partial else ids)
            self.tasks = [t for t in self.tasks if t["hash"] not in removed]
        return self.accept


def host(tasks=None, site=True):
    obj = Subject()
    obj._enabled = True
    obj._downloaders = ["QB"]
    obj._push_downloader = "QB"
    client = Client(tasks if tasks is not None else [torrent()])
    services = {"QB": NS(instance=client, type="qbittorrent", config=NS(type="qbittorrent"))}
    obj._get_manage_services = lambda: services
    obj._fetch_completed = lambda logs: ([{"title": TITLE, "size": 41.34, "seeders": 5, "seed_id": 123}] if site else [])
    return obj, client


def delete(obj):
    row = obj._collect_rescue_seeds(strict_downloaders=True)[0]
    manifest = tuple(sorted((c["downloader"], c["hash"]) for c in row["candidates"]))
    return obj._delete_rescue_group(row["seed_id"], row["title"], manifest,
                                     obj._delete_generation, request_id="audit-request-1234")


@pytest.mark.parametrize("ratio", [0, .005, .01, .0101, .9995, 1])
def test_transmission_real_percent_property_units(ratio):
    tr = NS(percent_done=ratio, progress=round(ratio * 100, 2), status="seeding" if ratio == 1 else "downloading")
    assert Subject._get_progress_ratio(tr, "transmission") == ratio
    assert Subject._is_completed(tr, "transmission") is (ratio == 1)


@pytest.mark.parametrize("value", [0, .5, 1, 50, 99.95, 100])
def test_transmission_progress_only_is_always_percent(value):
    assert Subject._get_progress_ratio(NS(progress=value), "transmission") == value / 100


@pytest.mark.parametrize("progress", [None, float("nan"), float("inf"), -1, 1.1])
def test_invalid_qb_progress_never_counts_as_complete(progress):
    assert Subject._get_progress_ratio({"progress": progress}, "qbittorrent") is None
    assert not Subject._is_completed({"progress": progress, "state": "downloading"}, "qbittorrent")


def test_completed_progress_with_remaining_or_error_is_not_complete():
    assert not Subject._is_completed({"progress": 1, "amount_left": 100}, "qbittorrent")
    assert not Subject._is_completed({"progress": 1, "state": "missingfiles"}, "qbittorrent")


def test_group_readback_missing_hash_is_uncertain_and_one_shot():
    obj, client = host()
    client.readback = lambda: ([{"name": TITLE}], False)
    result = delete(obj)
    assert result["state"] == "uncertain"
    assert result["removed_count"] == 0
    assert len(client.calls) == 1


def test_group_exception_after_dispatch_preserves_uncertainty():
    obj, client = host()
    def broken():
        raise TimeoutError("mock readback timeout")
    client.readback = broken
    result = delete(obj)
    assert result["state"] == "uncertain"
    assert "已发送" in result["message"]
    assert len(client.calls) == 1


def test_same_client_partial_removal_reports_confirmed_count():
    obj, client = host([torrent(), torrent(B)])
    client.partial = True
    result = delete(obj)
    assert result["state"] == "uncertain" and result["removed_count"] == 1
    assert len(client.calls) == 1 and [t["hash"] for t in client.tasks] == [B]


def test_partial_readback_then_exception_keeps_observed_count():
    obj, client = host([torrent(), torrent(B)])
    client.partial = True
    reads = []
    def after():
        reads.append(1)
        if len(reads) > 1:
            raise TimeoutError("mock later readback failure")
        return copy.deepcopy(client.tasks), False
    client.readback = after
    result = delete(obj)
    assert result["state"] == "uncertain" and result["removed_count"] == 1
    assert len(client.calls) == 1


def test_uncertainty_guard_survives_new_request_and_restart():
    obj, client = host()
    client.accept = False
    assert delete(obj)["state"] == "uncertain"
    assert delete(obj)["state"] == "failed"
    assert len(client.calls) == 1
    restarted = Subject()
    restarted._temporary = obj._temporary
    restarted._guard_deletion  # Use the complete class, not a mocked guard.
    with pytest.raises(ValueError, match="禁止重发"):
        restarted._guard_deletion([("QB", A)], "different-request")
    client.tasks.clear()
    obj._collect_rescue_seeds(strict_downloaders=True)
    status = obj.api_delete_rescue_status("audit-request-1234")
    assert status["data"]["status"] == "resolved"
    restarted._delete_guard_loaded = False
    assert restarted.api_delete_rescue_status("audit-request-1234")["data"]["status"] == "resolved"


def test_guard_is_not_cleared_when_client_cannot_be_read():
    obj, client = host()
    obj._guard_deletion([("QB", A)], "old-request-1234")
    client.get_torrents = lambda: ([], True)
    obj._collect_rescue_seeds()
    with pytest.raises(ValueError):
        obj._guard_deletion([("QB", A)], "new-request-1234")


def test_malformed_hash_cannot_resolve_an_uncertain_deletion():
    obj, client = host()
    obj._guard_deletion([("QB", A)], "old-request-1234")
    client.tasks[0]["hash"] = "malformed"
    obj._collect_rescue_seeds()
    with pytest.raises(ValueError):
        obj._guard_deletion([("QB", A)], "new-request-1234")
    obj, client = host()
    client.readback = lambda: ([{"hash": "malformed", "name": TITLE}], False)
    assert delete(obj)["state"] == "uncertain" and len(client.calls) == 1


def test_guard_persistence_failure_prevents_any_command():
    obj, client = host()
    obj._save_delete_guard = Mock(side_effect=OSError("mock read-only plugin state"))
    assert delete(obj)["state"] == "failed"
    assert not client.calls


def test_known_shared_data_with_other_name_blocks_file_command():
    obj, client = host([torrent(), torrent(B, name="Other.Release.2020.1080p")])
    result = delete(obj)
    assert result["state"] == "failed"
    assert "共享" in result["message"] and not client.calls


def test_same_directory_distinct_files_does_not_false_block():
    obj, client = host([torrent(), torrent(B, name="Other.Release.2020.1080p")])
    client.files[B] = [{"name": "other/payload.mkv"}]
    assert delete(obj)["state"] == "verified"
    assert len(client.calls) == 1 and client.tasks[0]["hash"] == B


@pytest.mark.parametrize("base", ["relative", "/fixture/nested/..", "/fixture//"])
def test_non_target_uncertain_or_equivalent_directory_cannot_hide_shared_files(base):
    obj, client = host([torrent(), torrent(B, name="Other.Release.2020.1080p", path=base)])
    assert delete(obj)["state"] == "failed" and not client.calls


def test_windows_directory_case_does_not_hide_shared_file():
    obj, client = host([torrent(path="C:\\fixture"), torrent(B, name="Other.Release.2020.1080p", path="c:\\FIXTURE")])
    assert delete(obj)["state"] == "failed" and not client.calls


def test_qb_authoritative_content_path_detects_shared_parent():
    other = torrent(B, name="Other.Release.2020.1080p")
    other["content_path"] = "/fixture/release"
    obj, client = host([torrent(), other])
    assert delete(obj)["state"] == "failed"
    assert not client.calls


def test_unreadable_files_or_missing_path_fails_closed():
    obj, client = host()
    client.files[A] = None
    assert delete(obj)["state"] == "failed" and not client.calls
    client.files[A] = [{"name": "release/payload.mkv"}]
    client.tasks[0].pop("save_path")
    assert delete(obj)["state"] == "failed" and not client.calls


def test_cross_client_shared_files_block_non_target_hash():
    obj, client = host()
    other = Client([torrent(B, name="Other.Release.2020.1080p")])
    services = obj._get_manage_services()
    services["TR"] = NS(instance=other, type="transmission", config=NS(type="transmission"))
    other.tasks[0]["percentDone"] = 1
    obj._downloaders.append("TR")
    assert delete(obj)["state"] == "failed"
    assert not client.calls and not other.calls


def test_legacy_exact_endpoint_missing_total_size_cannot_delete():
    obj, client = host()
    client.tasks[0].pop("total_size")
    result = obj._delete_rescue_exact(TITLE, "QB", A, True, obj._delete_generation)
    assert not result["success"] and not client.calls


@pytest.mark.parametrize("infohash", ["all", "12", "x" * 40, "a" * 39, "a" * 65])
def test_invalid_infohash_cannot_authorize_any_deletion_entry(infohash):
    obj, client = host([torrent(infohash=infohash)])
    assert not obj._collect_rescue_seeds()[0]["can_delete_group"]
    assert not obj.api_delete_rescue_seed(title=TITLE, downloader="QB", torrent_hash=infohash,
        request_id="invalid-hash-request", confirm=True)["success"]
    assert not obj._delete_rescue_exact(TITLE, "QB", infohash, True)["success"]
    assert not client.calls


def test_bearer_run_route_requires_admin_identity():
    obj, _ = host()
    scope = Subject.get_api.__globals__
    class Denied(Exception):
        def __init__(self, **kwargs):
            self.status_code = kwargs["status_code"]
    scope["HTTPException"] = Denied
    check = scope["_require_bear_admin"]
    assert check in next(route for route in obj.get_api() if route["path"] == "/run")["dependencies"]
    with pytest.raises(Denied) as caught:
        check(identity=NS(super_user=False))
    assert caught.value.status_code == 403
    check(identity=NS(super_user=True))


def test_incomplete_alias_group_has_all_hashes_and_remains_non_site():
    obj, client = host([torrent(progress=.4), torrent(B, name=TRANSLATED, progress=.2)], site=False)
    rows = obj._collect_rescue_seeds(strict_downloaders=True)
    assert len(rows) == 1 and rows[0]["seed_id"] < 0
    assert rows[0]["source"] == "downloader" and rows[0]["cross_seed_count"] == 2
    assert rows[0]["can_delete_group"]
    assert delete(obj)["state"] == "verified"
    assert set(client.calls[0][1]) == {A, B}


def test_client_names_differing_only_in_case_are_distinct_downloaders():
    obj, _ = host()
    services = obj._get_manage_services()
    services["qb"] = NS(instance=Client([torrent()]), type="qbittorrent", config=NS(type="qbittorrent"))
    obj._downloaders.append("qb")
    row = obj._collect_rescue_seeds(strict_downloaders=True)[0]
    assert row["cross_seed_count"] == 2 and set(row["downloaders"]) == {"QB", "qb"}


def test_unfinished_threshold_does_not_drop_99_point_95_percent():
    obj, _ = host([torrent(progress=.9995)], site=False)
    rows = obj._collect_rescue_seeds()
    assert len(rows) == 1 and not rows[0]["candidates"][0]["completed"]


def test_automatic_snapshot_preserves_origin_hash_and_strict_identity():
    obj, _ = host()
    current = obj._get_current_seeding([])
    assert current["count"] == 1
    assert current["seeds"][0]["auto_delete_ready"]
    assert current["seeds"][0]["candidates"][0]["hash"] == A
    obj._get_manage_services()["QB"].instance.tasks[0]["name"] += " PROPER"
    assert obj._get_current_seeding([])["count"] == 0


def test_automatic_read_failure_and_unknown_progress_never_become_empty_success():
    obj, client = host()
    client.get_torrents = lambda: ([], True)
    assert obj._get_downloader_seeds([]) is None
    assert obj._get_current_seeding([]).get("error")
    client.get_torrents = lambda: ([{"name": TITLE, "state": "downloading"}], False)
    assert obj._get_downloader_seeds([], any_tracker=True) == set()


def automatic_host(accept=True):
    obj, client = host()
    obj._mode = "wash"
    obj._target_volume = 50
    obj._get_site_cookie = lambda: "fake"
    obj._fetch_rescue_all = lambda logs: [{"title": "New.Release.2026.1080p.WEB-DL", "size": 40,
                                        "seeders": 1, "seed_id": 456, "href": "/download.php?id=456"}]
    obj._build_overview_from_current = lambda current: {"count": current["count"]}
    obj._save_log = Mock()
    obj._push_seeds = Mock(return_value=(1, 0, []))
    client.accept = accept
    return obj, client


def test_automatic_wash_really_deletes_before_dependent_push():
    obj, client = automatic_host()
    obj.run()
    assert len(client.calls) == 1 and obj._push_seeds.call_count == 1
    assert "删除 1" in obj._last_result


def test_automatic_wash_false_acceptance_stops_push_and_false_summary():
    obj, client = automatic_host(accept=False)
    obj.run()
    assert len(client.calls) == 1
    obj._push_seeds.assert_not_called()
    assert "停止" in obj._last_result and "已核实移除 0" in obj._last_result


@pytest.mark.parametrize("changes", [{"tracker": ""}, {"progress": .5, "state": "downloading"}])
def test_automatic_wash_preserves_groups_without_complete_trusted_copies(changes):
    obj, client = automatic_host()
    client.tasks[0].update(changes)
    if changes.get("progress"):
        client.tasks.append(torrent(B))  # One completed sibling cannot authorize the unfinished one.
    obj.run()
    assert not client.calls and not obj._push_seeds.called


@pytest.mark.parametrize("changes", [{"tracker": ""}, {"progress": .5, "state": "downloading"}])
def test_automatic_policy_is_rechecked_after_selection(changes):
    obj, client = host()
    row = obj._get_current_seeding([])["seeds"][0]
    client.tasks[0].update(changes)
    result = obj._delete_seeds([row], [])
    assert not result["success"] and not client.calls


def test_manual_group_without_tracker_remains_allowed():
    obj, client = host([torrent(tracker="")])
    assert delete(obj)["state"] == "verified" and len(client.calls) == 1


def test_automatic_cleanup_rechecks_completion_at_final_snapshot():
    obj, client = host([torrent(progress=.4)], site=False)
    obj._auto_clean_days = 1
    row = obj._collect_rescue_seeds()[0]
    original, reads = client.get_torrents, []
    def snapshot():
        reads.append(1)
        if len(reads) == 2:  # After the eligibility lookup, before issuing the command.
            client.tasks[0].update(progress=1, state="seeding")
        return original()
    client.get_torrents = snapshot
    result = obj._delete_seeds([row], [], auto_mode="stale")
    assert not result["success"] and not client.calls


def test_old_automatic_overview_cannot_replace_new_configuration_cache():
    obj, _ = automatic_host()
    def reconfigure(current):
        obj._delete_generation += 1
        obj._last_overview = {"new_configuration": True}
        return {"old_configuration": True}
    obj._build_overview_from_current = reconfigure
    obj.run()
    assert obj._last_overview == {"new_configuration": True}


def test_disable_during_read_stops_old_automatic_run():
    obj, client = automatic_host()
    fetch = obj._fetch_rescue_all
    def stop(logs):
        obj.stop_service()
        return fetch(logs)
    obj._fetch_rescue_all = stop
    obj.run()
    assert not client.calls and not obj._push_seeds.called


def test_stop_after_durable_reservation_releases_known_unsent_hash():
    obj, client = host()
    original = obj._guard_deletion
    def stop(targets, request):
        original(targets, request)
        obj.stop_service()
    obj._guard_deletion = stop
    assert delete(obj)["state"] == "failed" and not client.calls
    assert not obj._delete_guard


def test_wash_reserves_capacity_for_existing_unfinished_downloads():
    obj, _ = host()
    obj._target_volume = 100
    current = [{"title": TITLE, "size": 40, "seeders": 5, "auto_delete_ready": True}]
    candidate = {"title": "Better release", "size": 80, "seeders": 1}
    # Current 40 + in-flight 50 leaves only 10; replacing 40 cannot fit an 80 GiB release.
    result = obj._optimize_wash([candidate], current, 10, [])
    assert result["picked"] == [] and result["del_seeds"] == []


def test_zero_target_is_unlimited_but_reached_positive_target_is_empty():
    obj, _ = host()
    candidate = {"title": TITLE, "size": 41.34, "seeders": 1}
    obj._target_volume = 0
    assert obj._optimize_incremental([candidate], 0, 0, [])["picked"] == [candidate]
    obj._target_volume = 50
    assert obj._optimize_incremental([candidate], 0, 50, [])["picked"] == []


def test_automatic_cleanup_false_result_not_counted_as_success():
    obj, client = host([torrent(progress=.4)], site=False)
    obj._auto_clean_days = 1
    client.accept = False
    with pytest.raises(RuntimeError, match="结果不确定"):
        obj._clean_stale_downloads([], [])
    assert len(client.calls) == 1


def test_automatic_cleanup_does_not_trust_station_name_in_url_path():
    obj, client = host([torrent(progress=.4, tracker="https://other.example/hhanclub")], site=False)
    obj._auto_clean_days = 1
    assert obj._clean_stale_downloads([], []) == 0 and not client.calls


@pytest.mark.parametrize("url", ["https://other.example/download.php", "http://hhanclub.net/download.php",
                                "https://hhanclub.net.evil.example/a", "https://u:p@hhanclub.net/a"])
def test_off_site_or_unsafe_download_url_never_receives_cookie(url):
    obj, _ = host()
    obj._get_site_url = lambda: "https://hhanclub.net"
    session = NS(get=Mock())
    with pytest.raises(ValueError):
        obj._download_response(session, url)
    session.get.assert_not_called()


def test_redirect_is_validated_before_second_http_request():
    obj, _ = host()
    obj._get_site_url = lambda: "https://hhanclub.net"
    session = NS(get=Mock(return_value=NS(status_code=302, headers={"Location": "https://other.example/a"})))
    with pytest.raises(ValueError):
        obj._download_response(session, "https://hhanclub.net/download.php?id=1")
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_partial_push_and_cancellation_report_every_unsent_title():
    obj, client = host()
    obj._get_site_cookie = lambda: "fake"
    obj._get_site_url = lambda: "https://hhanclub.net"
    obj._session = lambda: object()
    add = Mock(side_effect=[True, False])
    obj._get_downloader_obj = lambda: NS(config=NS(type="qbittorrent"), instance=NS(add_torrent=add))
    obj._download_response = lambda session, url: NS(status_code=200, content=b"mock bytes")
    seeds = [{"title": str(i), "href": "/download.php?id=" + str(i)} for i in range(2)]
    ok, failed, failures = obj._push_seeds(seeds, [])
    assert ok == 1 and failed == 1 and failures[0]["title"] == "1"
    obj._stopped = True
    ok, failed, failures = obj._push_seeds(seeds, [])
    assert ok == 0 and failed == 2 and {f["title"] for f in failures} == {"0", "1"}
    assert add.call_count == 2


def test_failed_push_not_counted_in_automatic_summary():
    obj, _ = automatic_host()
    obj._push_seeds = Mock(return_value=(0, 1, [{"title": "New.Release.2026.1080p.WEB-DL", "reason": "mock rejection"}]))
    obj.run()
    assert "已接收下载 0" in obj._last_result and "新增体积 0.0" in obj._last_result


def test_network_exception_secrets_are_redacted():
    for text in ["https://hhanclub.net/a?passkey=FAKE_SECRET", "Cookie: uid=1; pass=FAKE_SECRET",
                 "Authorization: Bearer FAKE_SECRET", "token=FAKE_SECRET password=FAKE_SECRET",
                 "{'Cookie': 'FAKE_SECRET'}", "Invalid header value: 'FAKE_SECRET'"]:
        assert "FAKE_SECRET" not in Subject._safe_error(text)


def test_monthly_api_is_short_coalesced_and_generation_safe():
    obj, _ = host()
    started, finish, done = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def result(refresh):
        calls.append(refresh)
        started.set()
        assert finish.wait(3)
        done.set()
        return {"records_total": 2}
    obj._monthly_stats_result = result
    before = time.monotonic()
    assert obj.api_monthly_stats_data(refresh=1)["loading"]
    assert time.monotonic() - before < .5 and started.wait(1)
    for _ in range(3):
        assert obj.api_monthly_stats_data(refresh=1)["loading"]
    obj.stop_service()
    finish.set()
    assert done.wait(1)
    assert calls == [1] and obj._stats_job["state"] == "idle"


def test_monthly_retry_counter_resets_on_new_day_and_save_is_serialized():
    obj, _ = host()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    data = {"records": [], "last_attempt_date": yesterday, "attempt_count": 3}
    obj._load_monthly_stats = lambda: copy.deepcopy(data)
    obj._fetch_settlement_history = lambda: []
    obj._save_monthly_stats = Mock()
    assert obj._ensure_monthly_stats()["attempt_count"] == 1
    running, peak = 0, 0
    def fetch():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        time.sleep(.03)
        running -= 1
        return []
    obj._fetch_settlement_history = fetch
    threads = [threading.Thread(target=obj._ensure_monthly_stats, kwargs={"force": True}) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(2)
    assert peak == 1


def test_actual_html_parser_follows_later_discovered_pages():
    obj, _ = host()
    obj._fetch_completed = Subject._fetch_completed.__get__(obj, Subject)
    obj._parse_completed_page.__func__.__globals__["BeautifulSoup"] = BeautifulSoup
    def html(sid, next_page):
        return (f'<a href="?action=7&page={next_page}">next</a><table><tr><th>种子ID</th><th>名称</th>'
                f'<th>大小</th><th>初始保种</th></tr><tr><td>{sid}</td><td>{TITLE}</td><td>41.34 GB</td><td>2</td></tr></table>')
    pages = [html(1, 1), html(2, 2), html(3, 2)]
    obj._get_site_uid = lambda: "fixture"
    obj._get_site_url = lambda: "https://hhanclub.net"
    obj._session = lambda: object()
    obj._get_with_retry = Mock(side_effect=[NS(text=page) for page in pages])
    assert [row["seed_id"] for row in obj._fetch_completed([])] == [1, 2, 3]
    assert obj._get_with_retry.call_count == 3


def test_candidate_pagination_bound_and_single_page_default():
    obj, _ = host()
    Subject._parse_rescue_page.__globals__["BeautifulSoup"] = BeautifulSoup
    assert obj._parse_rescue_page("<html></html>") == ([], 0)
    with pytest.raises(ValueError):
        obj._parse_rescue_page('<a href="?page=501">invalid</a>')

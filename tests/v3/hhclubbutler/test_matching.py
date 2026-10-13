"""HHClubButler V3 rescue inventory: site authority and safe downloader matching."""
from __future__ import annotations

from pathlib import Path
import runpy
import time


ROOT = Path(__file__).resolve().parents[3]
MATCHING = ROOT / "plugins.v3/hhclubbutler/matching.py"


def _match():
    return runpy.run_path(str(MATCHING))["associate_rescue_seeds"]


def _site(title, size=8.0, sid=1):
    return {"title": title, "size": size, "seed_id": sid, "seeders": 2,
            "completed_at": "2026-10-13", "qualified": "未达标"}


def _torrent(name, downloader="qBittorrent", size=8.0, hash_value="abc123",
             site_tracker=True, progress=1.0):
    return {"name": name, "downloader": downloader, "size_gb": size,
            "hash": hash_value, "site_tracker": site_tracker,
            "progress": progress, "path": "/pt/" + name}


def test_eligible_site_inventory_survives_no_downloader_matches():
    rows, stats = _match()([
        _site("City Founding Pioneer S01 2026 1080p MYVIDEO WEB-DL AAC2 0 H 265-HHWEB", sid=1),
        _site("Another Release Season 3 WEB-DL", sid=2),
    ], [])
    assert len(rows) == 2
    assert stats["eligible"] == 2
    assert stats["linked"] == 0 and stats["unmatched"] == 2
    assert all(row["can_delete"] is False and not row["hash"] for row in rows)
    assert [row["seed_id"] for row in rows] == [1, 2]


def test_exact_punctuation_and_unicode_width_association_is_deletable():
    title = "City Founding Pioneer S01 2026 1080p MYVIDEO WEB-DL AAC2 0 H 265-HHWEB"
    candidate = "Ｃｉｔｙ.Founding.Pioneer.S01.2026.1080p.MYVIDEO.WEB-DL.AAC2.0.H.265-HHWEB"
    rows, stats = _match()([_site(title)], [_torrent(candidate)])
    assert stats["linked"] == 1 and stats["exact"] == 1
    assert rows[0]["downloader"] == "qBittorrent"
    assert rows[0]["hash"] == "abc123"
    assert rows[0]["can_delete"] is True
    assert rows[0]["match_status"] == "exact"


def test_fuzzy_similar_title_matches_readonly_with_size_check():
    title = "Another Amazing TV Series S01 2026 1080p WEB-DL H264-HHWEB"
    cand = title + "-PROPER"
    rows, stats = _match()([_site(title, 10.0)], [_torrent(cand, size=10.05)])
    assert stats["linked"] == 1
    assert rows[0]["downloader"] == "qBittorrent"
    assert rows[0]["match_status"] == "similar"
    assert rows[0]["hash"] == ""
    assert not rows[0]["can_delete"]


def test_fuzzy_size_contradiction_must_not_link():
    title = "Another Amazing TV Series S01 2026 1080p WEB-DL H264-HHWEB"
    rows, stats = _match()([_site(title, 10.0)], [_torrent(title+"-PROPER", size=28.0)])
    assert stats["unmatched"] == 1
    assert not rows[0]["downloader"]


def test_unknown_tracker_or_incomplete_torrent_is_not_deletable():
    title = "Example Drama S01 2025 1080p WEB-DL DDP5.1"
    rows, _ = _match()([_site(title)], [_torrent(title, site_tracker=False)])
    assert rows[0]["match_status"] == "unverified"
    assert not rows[0]["can_delete"]
    assert rows[0]["downloader"] == "qBittorrent"
    rows, _ = _match()([_site(title)], [_torrent(title, progress=0.4)])
    assert rows[0]["match_status"] == "downloading"
    assert not rows[0]["can_delete"]


def test_duplicate_exact_torrents_display_both_downloaders_but_block_deletion():
    title = "Example Drama S01 2025 1080p WEB-DL DDP5.1"
    rows, stats = _match()([_site(title)], [
        _torrent(title, downloader="qBittorrent", hash_value="aaa"),
        _torrent(title, downloader="Transmission", hash_value="bbb"),
    ])
    assert rows[0]["downloaders"] == ["Transmission", "qBittorrent"]
    assert "Transmission" in rows[0]["downloader"] and "qBittorrent" in rows[0]["downloader"]
    assert rows[0]["match_status"] == "ambiguous"
    assert rows[0]["can_delete"] is False
    assert not rows[0]["hash"]
    assert stats["ambiguous"] == 1


def test_duplicate_site_titles_can_never_become_deletable():
    title = "Example Drama S01 2025 1080p WEB-DL DDP5.1"
    rows, _ = _match()([_site(title, sid=1), _site(title, sid=2)],
                       [_torrent(title)])
    assert len(rows) == 2
    assert all(r["match_status"] == "ambiguous" for r in rows)
    assert not any(r["can_delete"] for r in rows)


def test_one_downloader_torrent_never_assigned_as_deletable_to_two_site_rows():
    base = "Example Super Interesting Television Series S01 2025 1080p WEB-DL"
    rows, stats = _match()([_site(base, sid=1), _site(base + " PROPER", sid=2)],
                           [_torrent(base, size=8)])
    assert len(rows) == 2
    assert stats["eligible"] == 2
    assert not all(row["can_delete"] for row in rows)


def test_large_unmatched_site_list_remains_complete():
    originals = [_site("Rescue Movie %04d S01 2026 1080p WEB-DL" % i, sid=i)
                 for i in range(700)]
    others = [_torrent("Other Release %04d S01 2026 1080p WEB-DL" % i,
                       hash_value=str(i)) for i in range(900)]
    started = time.monotonic()
    rows, stats = _match()(originals, others)
    assert len(rows) == len(originals)
    assert stats["eligible"] == 700
    assert time.monotonic() - started < 8


def test_manager_collect_does_not_intersect_site_inventory():
    import ast
    source=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text(encoding="utf-8")
    clazz=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef)
               and n.name=="HHClubButler")
    method=next(n for n in clazz.body if isinstance(n,ast.FunctionDef)
                and n.name=="_collect_rescue_seeds")
    body=ast.get_source_segment(source,method)
    assert "self._fetch_completed(logs)" in body
    assert "self._get_current_seeding(" not in body
    assert "associate_rescue_seeds(completed, downloader_rows)" in body
    assert "if not names.get(key)" not in body


def test_unknown_progress_without_seeding_state_is_read_only():
    title = "Example Drama S01 2025 1080p WEB-DL DDP5.1"
    torrent = _torrent(title, progress=None)
    rows, _ = _match()([_site(title)], [torrent])
    assert rows[0]["downloader"] == "qBittorrent"
    assert rows[0]["match_status"] == "unverified"
    assert not rows[0]["can_delete"]
    torrent["state"] = "seeding"
    rows, _ = _match()([_site(title)], [torrent])
    assert rows[0]["can_delete"]

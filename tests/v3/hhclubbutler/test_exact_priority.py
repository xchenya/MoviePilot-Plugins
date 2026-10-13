"""Regression for widespread false 'ambiguous' results in HH manager.

A less reliable fuzzy suggestion must never demote a site row with a
unique exact downloader match. No real network or downloader is used.
"""
from __future__ import annotations

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[3]
MATCHING = ROOT / "plugins.v3/hhclubbutler/matching.py"


def _match():
    return runpy.run_path(str(MATCHING))["associate_rescue_seeds"]


def _site(title: str, seed_id: int = 1, size: float = 8.0):
    return {"title": title, "seed_id": seed_id, "size": size}


def _torrent(title: str, downloader: str = "Transmission",
             hash_value: str = "a"*40, size: float = 8.0):
    return {
        "name": title, "downloader": downloader, "hash": hash_value,
        "size_gb": size, "site_tracker": True, "progress": 1.0,
    }


def test_exact_claim_cannot_be_stolen_by_alternate_site_release():
    title = "A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"
    site_rows = [_site(title, 101), _site(title+".PROPER", 102)]
    rows, stats = _match()(site_rows, [_torrent(title)])
    assert rows[0]["match_status"] == "exact"
    assert rows[0]["can_delete"] is True
    assert rows[0]["downloader"] == "Transmission"
    assert rows[1]["match_status"] == "unmatched"
    assert rows[1]["can_delete"] is False
    assert not rows[1]["hash"]
    assert stats["ambiguous"] == 0
    assert stats["exact"] == 1
    assert stats["fuzzy_exact_claims_blocked"] >= 1


def test_same_torrent_represented_twice_does_not_invent_ambiguity():
    title = "The.Legend.of.Treasure.Basin.S01.2003.1080p.WEB-DL.H265-HHWEB"
    torrent = _torrent(title, hash_value="b"*40)
    rows, stats = _match()([_site(title)], [dict(torrent), dict(torrent)])
    assert rows[0]["match_status"] == "exact"
    assert rows[0]["can_delete"]
    assert stats["duplicate_downloader_rows_ignored"] == 1
    assert stats["ambiguous"] == 0


def test_same_name_but_different_hashes_remains_truly_ambiguous():
    title = "Numbers.S01.2023.1080p.VIU.WEB-DL.H265-HHWEB"
    rows, stats = _match()([_site(title)], [
        _torrent(title,hash_value="c"*40),
        _torrent(title,hash_value="d"*40),
    ])
    assert rows[0]["match_status"] == "ambiguous"
    assert "同一下载器" in rows[0]["match_reason"]
    assert not rows[0]["can_delete"]
    assert stats["ambiguity_multiple_tasks"] == 1


def test_same_hash_across_two_separate_downloaders_keeps_true_conflict():
    title = "Once.Upon.a.Star.2023.1080p.NF.WEB-DL.H265-HHWEB"
    rows, stats = _match()([_site(title)], [
        _torrent(title,downloader="Transmission",hash_value="a"*40),
        _torrent(title,downloader="qBittorrent",hash_value="a"*40),
    ])
    assert rows[0]["match_status"] == "ambiguous"
    assert rows[0]["downloaders"] == ["Transmission","qBittorrent"]
    assert not rows[0]["can_delete"]
    assert stats["ambiguity_multiple_tasks"] == 1


def test_fuzzy_match_without_exact_claim_is_visible_but_readonly():
    title = "American.Vandal.S01.2018.1080p.NF.WEB-DL.H265-HHWEB"
    rows, stats = _match()([_site(title)], [_torrent(title+"-REPACK")])
    assert rows[0]["matched"]
    assert rows[0]["match_status"] == "similar"
    assert rows[0]["downloader"] == "Transmission"
    assert not rows[0]["can_delete"]


def test_bulk_similar_alternates_do_not_contaminate_exact_ownership():
    originals = [f"Film{i:04d}.Special.Series.S01.2025.1080p.WEB-DL.H265-HHWEB"
                 for i in range(235)]
    site = []
    torrents = []
    for idx, name in enumerate(originals):
        site.append(_site(name,seed_id=idx*2+1))
        site.append(_site(name+".PROPER",seed_id=idx*2+2))
        torrents.append(_torrent(name,hash_value=f"{idx+1:040x}"))
    rows,stats = _match()(site,torrents)
    assert len(rows) == 470
    assert stats["ambiguous"] == 0
    assert stats["exact"] == 235
    assert stats["deletable"] == 235
    assert stats["linked"] == 235
    assert stats["unmatched"] == 235


def test_ambiguous_breakdown_is_a_partition_of_ambiguous_count():
    a="The.Life.Story.S01.2026.1080p.WEB-DL.H265-HHWEB"
    b="Other.Series.2025.1080p.WEB-DL.H265-HHWEB"
    rows,stats=_match()(
        [_site(a,seed_id=1),_site(b,seed_id=2)],
        [_torrent(a,hash_value="ab"*20),
         _torrent(b,hash_value="cd"*20),
         _torrent(b,hash_value="ef"*20)])
    assert stats["ambiguous"] == (
        stats["ambiguity_duplicate_site_titles"]
        + stats["ambiguity_multiple_tasks"]
        + stats["ambiguity_shared_fuzzy"]
    )
    assert stats["exact"] == 1 and stats["ambiguous"] == 1

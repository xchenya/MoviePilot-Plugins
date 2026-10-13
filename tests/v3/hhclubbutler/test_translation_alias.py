"""V3.0.6: Chinese translation prefix + exact English release suffix matching.

Pure matching tests: no MoviePilot instance, private API, or downloader deletion.
"""
from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
MATCHING = ROOT / "plugins.v3/hhclubbutler/matching.py"


def _match():
    return runpy.run_path(str(MATCHING))["associate_rescue_seeds"]


def _site(title, size=41.34, sid=51999):
    return {"title": title, "size": size, "seed_id": sid}


def _torrent(title, size=41.34, dl="Transmission", hash_value="a"*40):
    return {"name": title, "size_gb": size, "downloader": dl,
            "hash": hash_value, "site_tracker": True, "progress": 1.0}


EN = "A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR = "上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"


def test_user_example_links_as_translated_not_fuzzy_or_ambiguous():
    rows, stats = _match()([_site(EN)], [_torrent(TR)])
    assert stats["eligible"] == 1
    assert stats["linked"] == 1
    assert stats["translated"] == 1
    assert stats["ambiguous"] == 0
    assert rows[0]["downloader"] == "Transmission"
    assert rows[0]["match_status"] == "translated"
    assert rows[0]["matched"]
    assert "中文译名" in rows[0]["match_reason"]
    assert not rows[0]["can_delete"]
    assert rows[0]["hash"] == ""


def test_chinese_prefix_with_hyphen_and_spaces_is_supported():
    translated = "上古情歌 - A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
    rows, stats = _match()([_site(EN)], [_torrent(translated)])
    assert rows[0]["match_status"] == "translated"
    assert stats["translated"] == 1


def test_translation_alias_requires_real_size_evidence():
    rows, stats = _match()([_site(EN,41.34)], [_torrent(TR,47.90)])
    assert stats["translated"] == 0
    assert not rows[0]["can_delete"]
    assert rows[0]["match_status"] in ("unmatched","similar")
    rows2, stats2 = _match()([_site(EN,41.34)], [_torrent(TR,0)])
    assert stats2["translated"] == 0
    assert not rows2[0]["can_delete"]


def test_translation_alias_cannot_capture_different_english_release():
    wrong = "上古情歌.A.Lifetime.Love.S02.2017.1080p.WEB-DL.H264.AAC-HHWEB"
    rows, stats = _match()([_site(EN)], [_torrent(wrong)])
    assert stats["translated"] == 0
    assert not rows[0]["can_delete"]


def test_translated_match_has_priority_over_fuzzy_other_release():
    more_site = EN + " PROPER"
    rows, stats = _match()([_site(EN,sid=1),_site(more_site,sid=2)],[_torrent(TR)])
    assert rows[0]["match_status"] == "translated"
    assert rows[1]["match_status"] == "unmatched"
    assert stats["translated"] == 1
    assert stats["ambiguous"] == 0


def test_two_distinct_translated_downloads_are_truly_ambiguous():
    rows, stats = _match()([_site(EN)], [
        _torrent(TR,hash_value="b"*40),
        _torrent("上古情歌 - "+EN,hash_value="c"*40)])
    assert rows[0]["match_status"] == "ambiguous"
    assert rows[0]["can_delete"] is False
    assert stats["ambiguity_multiple_tasks"] == 1


def test_full_exact_and_translated_in_two_downloaders_preserve_conflict():
    rows, stats = _match()([_site(EN)], [
        _torrent(EN,dl="qBittorrent",hash_value="d"*40),
        _torrent(TR,dl="Transmission",hash_value="e"*40)])
    assert rows[0]["match_status"] == "ambiguous"
    assert rows[0]["downloaders"] == ["Transmission","qBittorrent"]
    assert not rows[0]["can_delete"]
    assert stats["ambiguous"] == 1


def test_bulk_translated_examples_do_not_pollute_ambiguity():
    site=[]
    torrents=[]
    for i in range(235):
        base=f"A Lifetime Love S{i:03d} 2017 1080p WEB-DL H264 AAC-HHWEB"
        site.append(_site(base,41.34,sid=i*2+1))
        site.append(_site(base+" PROPER",41.34,sid=i*2+2))
        translated=f"上古情歌.A.Lifetime.Love.S{i:03d}.2017.1080p.WEB-DL.H264.AAC-HHWEB"
        torrents.append(_torrent(translated,hash_value=f"{i+1:040x}"))
    rows,stats=_match()(site,torrents)
    assert stats["eligible"] == 470
    assert stats["translated"] == 235
    assert stats["ambiguous"] == 0
    assert stats["unmatched"] == 235
    assert stats["deletable"] == 0
    assert sum(x["match_status"]=="translated" for x in rows) == 235


def test_do_not_strong_match_chinese_english_prefix_without_release_marker():
    site="Some Short Film"
    tr="上古情歌.Some.Short.Film"
    rows, stats=_match()([_site(site,2.0)],[_torrent(tr,2.0)])
    assert stats["translated"] == 0
    assert not rows[0]["can_delete"]

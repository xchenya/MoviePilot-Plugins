"""V3.0.7: strong translated-name identity and trusted tracker boundaries.

No real downloader operations are performed in these tests.
"""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[3]
MATCHER=ROOT/"plugins.v3/hhclubbutler/matching.py"

def _functions():
    return runpy.run_path(str(MATCHER))

SITE="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"

def site(name=SITE,size=41.34,sid=51999):
    return {"title":name,"size":size,"seed_id":sid}

def torrent(name=TR,size=41.34,hash="a"*40,verified=True,progress=1.0,downloader="Transmission"):
    return {"name":name,"size_gb":size,"hash":hash,"progress":progress,
            "downloader":downloader,"site_tracker":verified,
            "trusted_tracker":verified}

def test_normalized_english_full_name_and_rounded_size_are_confirmed_for_association():
    f=_functions()["associate_rescue_seeds"]
    rows,stats=f([site()],[torrent(verified=False)])
    assert len(rows)==1
    assert rows[0]["match_status"]=="translated"
    assert rows[0]["downloader"]=="Transmission"
    assert rows[0]["matched"]
    assert not rows[0]["can_delete"]   # missing strong tracker prevents file deletion
    assert stats["translated"]==1
    assert stats["ambiguous"]==0

def test_strong_tracker_translated_name_and_size_allow_explicit_delete():
    f=_functions()["associate_rescue_seeds"]
    rows,stats=f([site()],[torrent(verified=True)])
    assert rows[0]["can_delete"]
    assert rows[0]["hash"]=="a"*40
    assert rows[0]["match_status"]=="translated"
    assert rows[0]["trusted_tracker"]
    assert "Tracker" in rows[0]["match_reason"]
    assert stats["deletable"]==1

def test_translation_size_tolerance_is_not_one_point_five_percent():
    f=_functions()["associate_rescue_seeds"]
    rows,stats=f([site(size=41.34)],[torrent(size=41.36,verified=True)])
    assert stats["translated"]==0
    assert not rows[0]["can_delete"]
    rows,stats=f([site(size=41.34)],[torrent(size=41.349,verified=True)])
    assert stats["translated"]==1
    assert rows[0]["can_delete"]

def test_untrusted_tracker_is_readonly_even_with_identical_name_and_size():
    f=_functions()["associate_rescue_seeds"]
    rows,_=f([site()],[torrent(verified=False)])
    assert rows[0]["match_status"]=="translated"
    assert not rows[0]["hash"]
    assert not rows[0]["can_delete"]

def test_tracker_host_only_accepts_exact_hostname_not_domain_suffix():
    check=_functions()["is_trusted_hh_tracker"]
    assert check("https://tracker.hhanclub.net/announce")
    assert check("udp://tracker.hhanclub.net:6969/announce")
    assert check("https://tracker.hhanclub.net:443/a")
    assert check("TRACKER.HHANCLUB.NET")
    for bad in (
        "https://tracker.hhanclub.net.evil.example/announce",
        "https://tracker.hhanclub.net.attacker.net/announce",
        "https://fake-tracker.hhanclub.net/a",
        "https://tracker.hhanclub.net@evil.example/announce",
        "https://hhanclub.net.evil.example/announce",
        "https://other.net/tracker.hhanclub.net/announce",
        "https://other.net?a=tracker.hhanclub.net",
    ):
        assert not check(bad), bad

def test_untrusted_full_exact_match_is_not_changed_by_translated_policy():
    f=_functions()["associate_rescue_seeds"]
    rows,_=f([site()],[torrent(name=SITE,verified=False)])
    assert rows[0]["match_status"]=="unverified"
    assert not rows[0]["can_delete"]

def test_ambiguity_keeps_translated_downloads_non_deletable():
    f=_functions()["associate_rescue_seeds"]
    rows,stats=f([site()],[torrent(hash="a"*40),torrent(hash="b"*40)])
    assert stats["cross_seed"]==1
    assert rows[0]["can_manage"]
    assert not rows[0]["can_delete"]
    assert not rows[0]["hash"]

def test_different_english_release_s02_must_not_become_confirmed():
    f=_functions()["associate_rescue_seeds"]
    wrong="上古情歌.A.Lifetime.Love.S02.2017.1080p.WEB-DL.H264.AAC-HHWEB"
    rows,stats=f([site()],[torrent(name=wrong)])
    assert stats["translated"]==0
    assert not rows[0]["can_delete"]

def test_translated_match_not_assigned_to_other_similar_site_version():
    f=_functions()["associate_rescue_seeds"]
    rows,stats=f([site(sid=100),site(name=SITE+" PROPER",sid=101)],[torrent()])
    assert rows[0]["can_delete"]
    assert rows[1]["match_status"]=="unmatched"
    assert stats["ambiguous"]==0

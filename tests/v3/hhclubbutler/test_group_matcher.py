"""Group deletion readiness must never depend on optional Tracker data."""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[3]
NAME="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"

def associated(seeds,torrents):
    mod=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    return mod["associate_rescue_seeds"](seeds,torrents)

def site(seed_id=51999):
    return {"title":NAME,"size":41.34,"seed_id":seed_id}

def t(hash_value,tracker="",name=TR,size=41.34,progress=1):
    return {"name":name,"size_gb":size,"hash":hash_value,
            "progress":progress,"downloader":"Transmission",
            "tracker":tracker,"site_tracker":False,"trusted_tracker":False}

def test_multiple_hashes_same_title_no_tracker_can_delete_group():
    data,stats=associated([site()],[t("a"*40),t("b"*40)])
    assert data[0]["cross_seed_count"]==2
    assert data[0]["can_delete_group"]
    assert stats["group_delete_ready"]==1
    assert not data[0]["can_delete"]  # legacy singular endpoint not used

def test_one_client_with_different_trackers_still_full_group():
    data,stats=associated([site()],[t("a"*40,"https://other.net/a"),t("b"*40,"")])
    assert data[0]["can_delete_group"]
    assert data[0]["cross_seed_count"]==2

def test_small_positive_size_difference_accepted_but_wrong_size_blocks_group():
    data,_=associated([site()],[t("a"*40,size=41.349)])
    assert data[0]["can_delete_group"]
    data,_=associated([site()],[t("a"*40,size=41.5)])
    assert not data[0]["can_delete_group"]

def test_group_does_not_delete_if_one_hash_missing():
    data,_=associated([site()],[t("a"*40),t("")])
    assert not data[0]["can_delete_group"]

def test_unfinished_task_can_be_manually_deleted_with_verified_group():
    data,_=associated([site()],[t("a"*40,progress=1),t("b"*40,progress=0.3)])
    assert data[0]["can_delete_group"]
    assert data[0]["cross_seed_count"] == 2
    assert any(not copy["completed"] for copy in data[0]["candidates"])

def test_duplicate_site_titles_disable_group_authorization():
    data,_=associated([site(1),site(2)],[t("a"*40),t("b"*40)])
    assert len(data)==2
    assert all(not row["can_delete_group"] for row in data)

def test_fuzzy_only_match_is_not_group_deletable():
    data,_=associated([site()],[t("a"*40,name=TR+"-PROPER")])
    assert not data[0]["can_delete_group"]

def test_normalize_name_requires_complete_english_release_not_prefix():
    data,_=associated([site()],[t("a"*40,name=TR.replace("S01","S02"))])
    assert not data[0]["can_delete_group"]

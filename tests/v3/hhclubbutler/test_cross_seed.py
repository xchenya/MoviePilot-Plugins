"""Cross-seeding: multiple hashes per release are legitimate user-managed tasks."""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[3]
HHA="https://tracker.hhanclub.net/announce"
SITE="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
CHINESE="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"

def lib():
    return runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))

def site(title=SITE,sid=51999):
    return {"title":title,"size":41.34,"seed_id":sid}

def tr(name=CHINESE,sha="a"*40,host=HHA,downloader="Transmission",size=41.34):
    return {
       "name":name,"hash":sha,"downloader":downloader,"size_gb":size,
       "tracker":host.split("/")[2],"site_tracker":("hhanclub.net" in host),
       "trusted_tracker":lib()["is_trusted_hh_tracker"](host),
       "progress":1.0,"state":"seeding"
    }

def test_multiple_same_name_hashes_are_crossseeds_not_ambiguity():
    a=tr(sha="a"*40)
    b=tr(sha="b"*40,host="https://tracker.otherpt.example/announce")
    c=tr(sha="c"*40,host="https://tracker.thirdpt.example/announce")
    rows,stats=lib()["associate_rescue_seeds"]([site()],[a,b,c])
    row=rows[0]
    assert row["match_status"]=="cross_seed"
    assert row["cross_seed_count"]==3
    assert row["auxiliary_count"]==2
    assert stats["cross_seed"]==1
    assert stats["ambiguous"]==0
    assert len(row["candidates"])==3
    assert {c["hash"] for c in row["candidates"]}=={"a"*40,"b"*40,"c"*40}
    assert row["can_manage"] is True
    assert row["can_delete"] is False

def test_each_copy_explicitly_removable_but_file_deletion_disabled():
    rows,_=lib()["associate_rescue_seeds"]([site()],[
        tr(sha="a"*40),
        tr(sha="b"*40,host="https://tracker.otherpt.example/announce")
    ])
    tasks=rows[0]["candidates"]
    assert all(x["can_remove"] for x in tasks)
    assert all(not x["can_delete_files"] for x in tasks)
    assert tasks[0]["trusted_tracker"] is True
    assert tasks[1]["trusted_tracker"] is False

def test_different_client_and_hash_remain_separate_selectable_tasks():
    rows,_=lib()["associate_rescue_seeds"]([site()],[
        tr(sha="a"*40),
        tr(sha="b"*40,downloader="qBittorrent")
    ])
    assert rows[0]["cross_seed_count"]==2
    assert set(rows[0]["downloaders"])=={"Transmission","qBittorrent"}
    assert {(x["downloader"],x["hash"]) for x in rows[0]["candidates"]}=={
        ("Transmission","a"*40),("qBittorrent","b"*40)
    }

def test_same_hash_twice_in_same_client_is_not_two_copies():
    record=tr(sha="b"*40)
    rows,stats=lib()["associate_rescue_seeds"]([site()],[record,dict(record)])
    assert rows[0]["cross_seed_count"]==1
    assert len(rows[0]["candidates"])==1
    assert stats["duplicate_downloader_rows_ignored"]==1

def test_multiple_exact_downloads_one_trusted_one_unverified_still_selectable():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(name=SITE,sha="a"*40),
        tr(name=SITE,sha="b"*40,host="https://other.example/announce")])
    assert rows[0]["match_status"]=="cross_seed"
    assert all(x["can_remove"] for x in rows[0]["candidates"])
    assert all(not x["can_delete_files"] for x in rows[0]["candidates"])

def test_similar_but_not_complete_release_name_does_not_grant_remove():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(name=CHINESE+"-REPACK",sha="a"*40)])
    assert all(not x["can_remove"] for x in rows[0]["candidates"])
    assert all(not x["can_delete_files"] for x in rows[0]["candidates"])

def test_duplicate_site_title_keeps_crossseed_count_but_blocks_task_removal():
    records=[site(sid=1),site(sid=2)]
    rows,stats=lib()["associate_rescue_seeds"](records,[tr(sha="a"*40),tr(sha="b"*40)])
    assert len(rows)==2
    assert all(row["cross_seed_count"]==2 for row in rows)
    assert all(not any(c["can_remove"] for c in row["candidates"]) for row in rows)
    assert stats["ambiguity_duplicate_site_titles"]==2

def test_single_exact_trusted_copy_still_can_delete_files():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(name=SITE,sha="a"*40)])
    assert rows[0]["can_delete"]
    assert rows[0]["candidates"][0]["can_delete_files"]
    assert rows[0]["cross_seed_count"]==1

def test_empty_hash_never_enables_remove():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(sha="")])
    assert rows[0]["matched"] is True
    assert rows[0]["candidates"][0]["can_remove"] is False

def test_unrelated_domain_not_trusted_for_file_removal():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(sha="a"*40,host="https://tracker.hhanclub.net.fake.example/a")])
    assert rows[0]["cross_seed_count"]==1
    assert not rows[0]["candidates"][0]["can_delete_files"]
    assert rows[0]["candidates"][0]["can_remove"]

def test_two_hashes_cannot_get_file_deletion_permission_via_any_group_member():
    rows,_=lib()["associate_rescue_seeds"]([site()],[tr(sha="a"*40),
                                                 tr(sha="b"*40)])
    assert not any(x["can_delete_files"] for x in rows[0]["candidates"])

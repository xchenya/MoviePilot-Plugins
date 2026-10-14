"""Explicit per-hash cross-seed removal keeps shared payloads on disk.

Only mocked download clients are used. No real torrent data is touched.
"""
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[3]
HHA="https://tracker.hhanclub.net/announce"
SITE="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"
A="a"*40
B="b"*40

def fixture():
    existing=runpy.run_path(str(ROOT/"tests/v3/hhclubbutler/test_delete_job.py"))
    lib=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    host=existing["_fixture"]()
    host._norm_title=lib["normalize_name"]
    source=[
      {"name":TR,"size_gb":41.34,"hash":A,"downloader":"QB",
       "trusted_tracker":True,"site_tracker":True,"progress":1.0,
       "tracker":"tracker.hhanclub.net"},
      {"name":TR,"size_gb":41.34,"hash":B,"downloader":"QB",
       "trusted_tracker":False,"site_tracker":False,"progress":1.0,
       "tracker":"tracker.otherpt.example"},
    ]
    data=lib["associate_rescue_seeds"]([{"title":SITE,"size":41.34}],source)[0]
    assert data[0]["cross_seed_count"]==2
    called=[]
    host._collect_rescue_seeds=lambda strict_downloaders=False: (called.append(strict_downloaders) or data)
    removed=Mock(return_value=True)
    torrents=[
      {"name":TR,"hash":A,"tracker":HHA,"size":round(41.34*1073741824)},
      {"name":TR,"hash":B,"tracker":"https://tracker.otherpt.example/announce",
       "size":round(41.34*1073741824)}
    ]
    client=SimpleNamespace(
      get_torrents=lambda:([t for t in torrents if not removed.called or t["hash"]!=B],None),
      delete_torrents=removed,
    )
    host._get_manage_services=lambda:{"QB":SimpleNamespace(instance=client)}
    host._extract_tracker_text=lambda t:t.get("tracker","")
    return host,removed,called,client

def test_selected_non_hh_crossseed_is_task_only_and_keeps_data():
    host,remove,calls,_=fixture()
    out=host._delete_rescue_exact(SITE,"QB",B,True,0,delete_file=False)
    assert out["success"] and out["state"]=="verified",out
    remove.assert_called_once_with(delete_file=False,ids=[B])
    assert calls==[False]

def test_malicious_payload_file_deletion_on_crossseed_is_rejected():
    host,remove,_,_=fixture()
    out=host._delete_rescue_exact(SITE,"QB",A,True,0,delete_file=True)
    assert not out["success"]
    assert "辅种" in out["message"] or "共享" in out["message"]
    remove.assert_not_called()

def test_crossseed_wrong_selected_hash_not_touched():
    host,remove,_,_=fixture()
    out=host._delete_rescue_exact(SITE,"QB","c"*40,True,0,delete_file=False)
    assert not out["success"]
    remove.assert_not_called()

def test_hash_based_removal_does_not_touch_second_task():
    host,remove,_,client=fixture()
    out=host._delete_rescue_exact(SITE,"QB",B,True,0,delete_file=False)
    assert out["success"]
    remains,_=client.get_torrents()
    assert [t["hash"] for t in remains]==[A]

def test_job_idempotency_binds_delete_file_mode():
    host,remove,_,_=fixture()
    host._delete_rescue_exact=lambda *a,**kw:{"success":False,"state":"failed","message":"mock"}
    request_id="3ac05f3f-bace-4b20-bd7b-122c8cf56207"
    a=host.api_delete_rescue_seed(title=SITE,downloader="QB",torrent_hash=B,
                                  confirm=True,request_id=request_id,delete_file=False)
    assert a["success"]
    b=host.api_delete_rescue_seed(title=SITE,downloader="QB",torrent_hash=B,
                                  confirm=True,request_id=request_id,delete_file=True)
    assert not b["success"]
    assert "同一请求" in b["message"]
    remove.assert_not_called()

def test_crossseed_ui_contract_selects_hash_and_preserves_data():
    src=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text()
    assert 'id="hhCopyOverlay"' in src
    assert 'id="hhCopyList"' in src
    assert 'id="crossSeedGroups"' in src
    assert 'id="auxiliaryTaskCount"' in src
    assert 'data-del="' in src
    assert 'copyPickerResolve' in src
    assert 'delete_file:item.delete_file===false?"false":"true"' in src
    assert "seed.cross_seed_count>1" in src
    assert 'item.delete_file===false' in src

def test_single_verified_hh_still_can_delete_file_explicitly():
    # Existing single-copy behavior must not be silently switched to task-only.
    host,remove,_,_=fixture()
    lib=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    one=lib["associate_rescue_seeds"]([{"title":SITE,"size":41.34}],[{
        "name":TR,"size_gb":41.34,"hash":A,"downloader":"QB",
        "site_tracker":True,"trusted_tracker":True,"progress":1.0,
        "tracker":"tracker.hhanclub.net"
    }])[0]
    host._collect_rescue_seeds=lambda strict_downloaders=False:one
    client=SimpleNamespace(
      get_torrents=lambda:(([] if remove.called else
          [{"name":TR,"hash":A,"tracker":HHA,"size":round(41.34*1073741824)}]),None),
      delete_torrents=remove,
    )
    host._get_manage_services=lambda:{"QB":SimpleNamespace(instance=client)}
    out=host._delete_rescue_exact(SITE,"QB",A,True,0,delete_file=True)
    assert out["success"]
    remove.assert_called_once_with(delete_file=True,ids=[A])

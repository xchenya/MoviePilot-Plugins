"""Mock-only check for translated name accepted by server-side preflight."""
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[3]
EN="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"
H="a"*40

def test_translated_server_preflight_verifies_fresh_hash_and_tracker():
    source=runpy.run_path(str(ROOT/"tests/v3/hhclubbutler/test_delete_job.py"))
    matcher=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    host=source["_fixture"]()
    host._norm_title=lambda v: matcher["normalize_name"](v)
    remote={"name":TR,"hash":H,"size":int(41.34*1073741824),
            "tracker":"https://tracker.hhanclub.net/announce"}
    metadata={"name":TR,"hash":H,"size_gb":41.34,
              "site_tracker":True,"trusted_tracker":True,
              "progress":1.0,"downloader":"QB"}
    rows,_=matcher["associate_rescue_seeds"]([{"title":EN,"size":41.34}],[metadata])
    host._collect_rescue_seeds=lambda strict_downloaders=False: rows
    host._extract_tracker_text=lambda item:item.get("tracker","")
    acted=Mock(return_value=True)
    client=SimpleNamespace(get_torrents=lambda:(([] if acted.called else [remote]),None),
                           delete_torrents=acted)
    host._get_manage_services=lambda:{"QB":SimpleNamespace(instance=client)}
    outcome=host._delete_rescue_exact(EN,"QB",H,True,0)
    assert outcome["success"],outcome
    acted.assert_called_once()

def test_failed_fresh_snapshot_returns_failed_without_dispatch():
    source=runpy.run_path(str(ROOT/"tests/v3/hhclubbutler/test_delete_job.py"))
    host=source["_fixture"]()
    called=[]
    def unavailable(strict_downloaders=False):
        called.append(strict_downloaders)
        raise RuntimeError("downloader unavailable")
    host._collect_rescue_seeds=unavailable
    result=host._delete_rescue_exact(EN,"QB",H,True,0)
    assert called==[True]
    assert not result["success"]
    assert result["state"]=="failed"

def test_changed_tracker_after_verified_snapshot_blocks_operation():
    old=runpy.run_path(str(ROOT/"tests/v3/hhclubbutler/test_delete_job.py"))
    match=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    host=old["_fixture"]()
    host._norm_title=match["normalize_name"]
    site={"title":EN,"size":41.34}
    metadata={"name":TR,"size_gb":41.34,"hash":H,"downloader":"QB",
              "site_tracker":True,"trusted_tracker":True,"progress":1.0}
    rows,_=match["associate_rescue_seeds"]([site],[metadata])
    host._collect_rescue_seeds=lambda strict_downloaders=False: rows
    host._extract_tracker_text=lambda x:x.get("tracker","")
    fake={"name":TR,"hash":H,"size":int(41.34*1073741824),
          "tracker":"https://tracker.hhanclub.net.fake.example/announce"}
    action=Mock(return_value=True)
    client=SimpleNamespace(get_torrents=lambda:([fake],False),delete_torrents=action)
    host._get_manage_services=lambda:{"QB":SimpleNamespace(instance=client)}
    result=host._delete_rescue_exact(EN,"QB",H,True,0)
    assert not result["success"]
    action.assert_not_called()

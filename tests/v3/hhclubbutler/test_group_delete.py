"""Idempotent all-cross-seed deletion and fail-closed inventory reconciliation.

All clients here are in-memory mocks; no live downloader or filesystem data
is touched.
"""
from __future__ import annotations

import ast
import copy
import re
import runpy
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SUPPORT = __import__("runpy").run_path(str(Path(__file__).with_name("support.py")))

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/"plugins.v3/hhclubbutler/__init__.py"
HASH_A="a"*40
HASH_B="b"*40
HASH_C="c"*40
TITLE="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
TR_NAME="上古情歌.A.Lifetime.Love.S01.2017.1080p.WEB-DL.H264.AAC-HHWEB"
REQUEST="99ee11aa-0001-4000-8000-abcdefabcdef"

def subject():
    tree=ast.parse(BASE.read_text(encoding="utf-8"))
    old=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=="HHClubButler")
    names={"_delete_job_view","_invalidate_rescue_cache",
           "api_delete_rescue_group","_delete_rescue_group_worker",
           "_delete_rescue_group","api_delete_rescue_status"}
    nodes=[copy.deepcopy(n) for n in old.body
           if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    klass=ast.ClassDef(name="Subject",bases=[],keywords=[],body=nodes,decorator_list=[])
    match=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    namespace={"HHClubButler": SUPPORT["Subject"], "re":re,"time":time,"threading":threading,
               "RescueGroupDeleteRequest":SimpleNamespace,
               "logger":SimpleNamespace(info=Mock(),warning=Mock(),error=Mock()),
               "normalize_name":match["normalize_name"],
               "translated_release_key":match["translated_release_key"],
               "translated_size_matches":match["translated_size_matches"]}
    module=ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[]))
    exec(compile(module,"<group-delete>", "exec"),namespace)
    return namespace["Subject"]

class Client:
    def __init__(self,torrents,accept=True):
        self.torrents=list(torrents)
        self.calls=[]
        self.accept=accept
        self.instance=self
    def get_torrents(self):
        return list(self.torrents),False
    def get_files(self, tid):
        return [{"name": "release/payload.mkv"}]
    def delete_torrents(self,delete_file,ids):
        self.calls.append({"delete_file":delete_file,"ids":list(ids)})
        if self.accept:
            hashes={str(i).lower() for i in ids}
            self.torrents=[t for t in self.torrents if str(t["hash"]).lower() not in hashes]
        return self.accept

def torrent(name,hash_value):
    return {"name":name,"hash":hash_value,
            "save_path":"/fixtures", "size":round(41.34*1073741824),"progress":1.0}

def fixture(client_failure=None,fresh_targets=None):
    o=subject()()
    o._enabled=True;o._stopped=False;o._delete_generation=0
    o._downloaders=["QB","TR"]
    o._delete_lock=threading.Lock()
    o._list_lock=threading.Lock()
    o._run_lock=threading.Lock()
    o._delete_jobs={};o._delete_active_id=None
    o._list_generation=0;o._list_cache=[{"title":TITLE}]
    o._list_state="ready";o._list_updated_at=time.time()
    o._list_warning="";o._list_error=""
    o._last_overview={"count":1};o._last_overview_ts=time.time()
    o._get_progress_ratio=lambda t,dl:float(t.get("progress") or 0)
    qb=Client([torrent(TITLE,HASH_C)],accept=client_failure!="QB")
    tr=Client([torrent(TR_NAME,HASH_A),torrent(TR_NAME,HASH_B)],accept=client_failure!="TR")
    services={"QB":SimpleNamespace(instance=qb),"TR":SimpleNamespace(instance=tr)}
    o._get_manage_services=lambda:services
    expected=(("QB",HASH_C),("TR",HASH_A),("TR",HASH_B))
    targets=fresh_targets if fresh_targets is not None else expected
    o._collect_rescue_seeds=lambda strict_downloaders=False:[
        {"title":TITLE,"size":41.34,"seed_id":51999,
         "can_delete_group":True,
         "candidates":[{"downloader":d,"hash":h} for d,h in targets]}
    ]
    return SUPPORT["enrich"](o),services,expected

def request(targets,request_id=REQUEST,confirm=True,seed_id=51999):
    return SimpleNamespace(
        title=TITLE,seed_id=seed_id,confirm=confirm,delete_file=True,
        request_id=request_id,
        targets=[SimpleNamespace(downloader=d,hash=h) for d,h in targets]
    )

def wait_for(subject_obj,request_id=REQUEST):
    until=time.monotonic()+5
    while time.monotonic()<until:
        status=subject_obj.api_delete_rescue_status(request_id=request_id)
        if status["success"] and status["data"]["status"] not in ("queued","running"):
            return status["data"]
        time.sleep(0.01)
    raise AssertionError("timeout waiting for in-memory group worker")

def test_two_downloaders_three_hashes_submit_once_and_all_data_flags_true():
    o,svcs,manifest=fixture()
    ack=o.api_delete_rescue_group(request(manifest))
    assert ack["success"]
    status=wait_for(o)
    assert status["status"]=="verified",status
    assert status["removed_count"]==3 and status["total_count"]==3
    assert svcs["QB"].instance.calls==[{"delete_file":True,"ids":[HASH_C]}]
    assert svcs["TR"].instance.calls==[{"delete_file":True,"ids":[HASH_A,HASH_B]}]
    assert o._list_cache is None

def test_tracker_missing_does_not_block_group_deletion():
    o,svcs,manifest=fixture()
    # Simulated torrent objects deliberately have no Tracker fields.
    result=o._delete_rescue_group(51999,TITLE,manifest,0)
    assert result["state"]=="verified"
    assert len(svcs["TR"].instance.calls)==1

def test_stale_new_crossseed_must_not_be_deleted_without_new_confirmation():
    additional=(("QB",HASH_C),("TR",HASH_A),("TR",HASH_B),("TR","d"*40))
    o,svcs,original=fixture(fresh_targets=additional)
    result=o._delete_rescue_group(51999,TITLE,original,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls and not svcs["TR"].instance.calls

def test_missing_crossseed_in_download_client_aborts_group():
    o,svcs,manifest=fixture()
    svcs["TR"].instance.torrents.pop()
    result=o._delete_rescue_group(51999,TITLE,manifest,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls and not svcs["TR"].instance.calls

def test_second_client_failure_reports_partial_and_no_second_attempt():
    o,svcs,manifest=fixture(client_failure="TR")
    ack=o.api_delete_rescue_group(request(manifest))
    assert ack["success"]
    result=wait_for(o)
    assert result["status"]=="uncertain"
    assert result["removed_count"]==1
    assert len(svcs["QB"].instance.calls)==1
    assert len(svcs["TR"].instance.calls)==1
    for _ in range(4):
        assert o.api_delete_rescue_status(request_id=REQUEST)["data"]["removed_count"]==1
    assert len(svcs["TR"].instance.calls)==1

def test_duplicate_request_id_returns_existing_job_and_never_deletes_twice():
    o,svcs,manifest=fixture()
    one=o.api_delete_rescue_group(request(manifest))
    assert one["success"]
    wait_for(o)
    other=o.api_delete_rescue_group(request(manifest))
    assert other["success"] and other["data"]["status"]=="verified"
    assert len(svcs["QB"].instance.calls)==1
    assert len(svcs["TR"].instance.calls)==1

def test_request_id_mismatch_rejected_without_side_effect():
    o,svcs,manifest=fixture()
    o.api_delete_rescue_group(request(manifest))
    wait_for(o)
    wrong=o.api_delete_rescue_group(request(manifest[:-1]))
    assert not wrong["success"]
    assert len(svcs["TR"].instance.calls)==1

def test_unconfirmed_group_operation_has_no_download_side_effects():
    o,svcs,manifest=fixture()
    result=o.api_delete_rescue_group(request(manifest,confirm=False))
    assert not result["success"]
    assert not svcs["QB"].instance.calls
    assert not svcs["TR"].instance.calls

def test_progress_unknown_and_missing_size_prevents_data_deletion():
    o,svcs,manifest=fixture()
    svcs["TR"].instance.torrents[0]["size"]=None
    result=o._delete_rescue_group(51999,TITLE,manifest,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls and not svcs["TR"].instance.calls

def test_wrong_filename_content_never_authorizes_group():
    o,svcs,manifest=fixture()
    svcs["TR"].instance.torrents[0]["name"]=TR_NAME.replace("S01","S02")
    result=o._delete_rescue_group(51999,TITLE,manifest,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls and not svcs["TR"].instance.calls

def test_request_cannot_be_enlarged_with_malformed_or_duplicate_hash():
    o,svcs,manifest=fixture()
    assert not o.api_delete_rescue_group(request((("QB","xxxx"),)))["success"]
    assert not o.api_delete_rescue_group(request((manifest[0],manifest[0])))["success"]
    assert not svcs["QB"].instance.calls

def test_site_record_id_mismatch_blocks_delete():
    o,svcs,manifest=fixture()
    result=o._delete_rescue_group(99999,TITLE,manifest,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls

def test_generation_change_before_start_blocks_without_dispatch():
    o,svcs,manifest=fixture()
    result=o._delete_rescue_group(51999,TITLE,manifest,generation=1)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls

def test_candidate_group_not_authorized_is_rejected_even_with_manifest():
    o,svcs,manifest=fixture()
    o._collect_rescue_seeds=lambda strict_downloaders=False:[{
        "title":TITLE,"size":41.34,"seed_id":51999,
        "can_delete_group":False,"candidates":[{"downloader":d,"hash":h} for d,h in manifest]
    }]
    result=o._delete_rescue_group(51999,TITLE,manifest,0)
    assert result["state"]=="failed"
    assert not svcs["QB"].instance.calls

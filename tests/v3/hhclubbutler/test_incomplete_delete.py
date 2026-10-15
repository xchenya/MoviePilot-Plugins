"""Downloader-only incomplete torrents can be removed after explicit confirmation.

No download client is contacted: all operations execute in mock objects.
"""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[3]
A="a"*40


def fixture():
    tests=runpy.run_path(str(ROOT/"tests/v3/hhclubbutler/test_group_delete.py"))
    o,services,_=tests["fixture"]()
    qb=services["QB"].instance
    qb.torrents=[tests["torrent"](tests["TITLE"],tests["HASH_C"])]
    qb.torrents[0]["progress"]=.34
    tr=services["TR"].instance
    tr.torrents=[]
    task_id=-909512442331
    target=(("QB",tests["HASH_C"]),)
    o._collect_rescue_seeds=lambda strict_downloaders=False:[{
        "title":tests["TITLE"],"size":41.34,"seed_id":task_id,
        "source":"downloader","can_delete_group":True,
        "candidates":[{"downloader":"QB","hash":tests["HASH_C"]}]
    }]
    return o,services,tests,task_id,target


def test_unfinished_qb_task_and_file_can_be_deleted_explicitly():
    host,services,tests,seed_id,targets=fixture()
    out=host._delete_rescue_group(seed_id,tests["TITLE"],targets,0)
    assert out["state"]=="verified",out
    assert out["removed_count"]==1
    assert services["QB"].instance.calls==[
        {"delete_file":True,"ids":[tests["HASH_C"]]}
    ]
    assert services["TR"].instance.calls==[]


def test_negative_seed_id_allowed_through_group_api_and_worker():
    host,services,tests,seed_id,targets=fixture()
    request=tests["request"](targets,seed_id=seed_id)
    accepted=host.api_delete_rescue_group(request)
    assert accepted["success"]
    done=tests["wait_for"](host)
    assert done["status"]=="verified",done
    assert done["removed_count"]==1
    assert services["QB"].instance.calls==[
        {"delete_file":True,"ids":[tests["HASH_C"]]}
    ]


def test_cannot_fake_downloader_only_id_as_site_eligibility():
    host,services,tests,seed_id,targets=fixture()
    host._collect_rescue_seeds=lambda strict_downloaders=False:[{
        "title":tests["TITLE"],"size":41.34,"seed_id":seed_id,
        "source":"site","can_delete_group":True,
        "candidates":[{"downloader":"QB","hash":tests["HASH_C"]}]
    }]
    result=host._delete_rescue_group(seed_id,tests["TITLE"],targets,0)
    assert result["state"]=="failed"
    assert services["QB"].instance.calls==[]


def test_changes_to_download_infohash_cancel_before_file_delete():
    host,services,tests,seed_id,targets=fixture()
    host._collect_rescue_seeds=lambda strict_downloaders=False:[{
        "title":tests["TITLE"],"size":41.34,"seed_id":seed_id,
        "source":"downloader","can_delete_group":True,
        "candidates":[{"downloader":"QB","hash":"d"*40}]
    }]
    result=host._delete_rescue_group(seed_id,tests["TITLE"],targets,0)
    assert result["state"]=="failed"
    assert services["QB"].instance.calls==[]


def test_name_mismatch_or_size_change_prevents_deletion():
    host,services,tests,seed_id,targets=fixture()
    services["QB"].instance.torrents[0]["name"]="unrelated.file.2026.mkv"
    result=host._delete_rescue_group(seed_id,tests["TITLE"],targets,0)
    assert result["state"]=="failed"
    assert services["QB"].instance.calls==[]
    services["QB"].instance.torrents[0]["name"]=tests["TITLE"]
    services["QB"].instance.torrents[0]["size"]=int(44.8*1073741824)
    result=host._delete_rescue_group(seed_id,tests["TITLE"],targets,0)
    assert result["state"]=="failed"
    assert services["QB"].instance.calls==[]


def test_deletion_remains_user_confirmed_not_auto_cleaned():
    host,services,tests,seed_id,targets=fixture()
    req=tests["request"](targets,confirm=False,seed_id=seed_id)
    result=host.api_delete_rescue_group(req)
    assert not result["success"]
    assert services["QB"].instance.calls==[]

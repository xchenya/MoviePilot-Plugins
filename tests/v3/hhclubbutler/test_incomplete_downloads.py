"""Downloader-only incomplete tasks are distinct from HH site's eligibility."""
from __future__ import annotations
import ast
import hashlib
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[3]
NAME="A Lifetime Love S01 2017 1080p WEB-DL H264 AAC-HHWEB"
A="a"*40
B="b"*40


def _method(name):
    src=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text()
    cls=next(n for n in ast.parse(src).body if isinstance(n,ast.ClassDef)
             and n.name=="HHClubButler")
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    match=runpy.run_path(str(ROOT/"plugins.v3/hhclubbutler/matching.py"))
    import datetime,time,re
    scope={"associate_rescue_seeds":match["associate_rescue_seeds"],
           "normalize_name":match["normalize_name"],
           "is_trusted_hh_tracker":match["is_trusted_hh_tracker"],
           "datetime":datetime.datetime,"time":time,"re":re,
           "hashlib":hashlib,
           "logger":SimpleNamespace(info=Mock(),warning=Mock(),error=Mock())}
    m=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    exec(compile(m,f"<test:{name}>","exec"),scope)
    return scope[name]


def _raw(progress=0.4,hash_value=A,size=41.34,name=NAME):
    return {"name":name,"size_gb":size,"progress":progress,
            "downloader":"QB","hash":hash_value,"state":"downloading",
            "site_tracker":False,"trusted_tracker":False}


def test_synthetic_downloader_only_row_is_marked_incomplete_and_deletable():
    append=_method("_append_downloader_incomplete")
    out=append([],[_raw()])
    assert len(out)==1
    record=out[0]
    assert record["source"]=="downloader"
    assert record["seed_id"]<0
    assert record["qualified"]=="未完成下载"
    assert record["can_delete_group"]
    assert record["can_manage"]
    assert record["cross_seed_count"]==1
    assert record["candidates"][0]["completed"] is False
    assert record["size"]==41.34


def test_synthetic_id_is_stable_and_js_safe():
    append=_method("_append_downloader_incomplete")
    v1=append([],[_raw(progress=.10)])
    v2=append([],[_raw(progress=.85)])
    assert v1[0]["seed_id"]==v2[0]["seed_id"]
    assert -(2**53)<v1[0]["seed_id"]<0


def test_site_eligibility_and_downloader_only_rows_are_separate():
    append=_method("_append_downloader_incomplete")
    site=[{"title":"Other title","seed_id":12345,"source":"site","candidates":[]}]
    result=append(site,[_raw()])
    assert len(result)==2
    assert sum(r.get("source")=="downloader" for r in result)==1
    assert result[0]["seed_id"]==12345
    assert result[1]["seed_id"]<0


def test_site_linked_unfinished_torrent_is_not_duplicated():
    append=_method("_append_downloader_incomplete")
    site=[{"title":NAME,"seed_id":12345,"candidates":[{"downloader":"QB","hash":A}]}]
    result=append(site,[_raw()])
    assert len(result)==1


def test_multiple_unfinished_hashes_are_one_group():
    append=_method("_append_downloader_incomplete")
    result=append([],[_raw(.25,A),_raw(.75,B)])
    assert len(result)==1
    assert result[0]["cross_seed_count"]==2
    assert result[0]["can_delete_group"]
    assert {x["hash"] for x in result[0]["candidates"]}=={A,B}


def test_completed_sibling_with_same_title_belongs_to_unfinished_group():
    append=_method("_append_downloader_incomplete")
    result=append([],[_raw(.34,A),_raw(1,B)])
    assert len(result)==1
    assert result[0]["cross_seed_count"]==2


def test_only_completed_downloads_are_not_added_to_downloader_only_list():
    append=_method("_append_downloader_incomplete")
    assert append([],[_raw(1,A)])==[]


def test_other_name_even_same_size_is_a_separate_group():
    append=_method("_append_downloader_incomplete")
    result=append([],[_raw(.4,A),_raw(.6,B,name=NAME+" PROPER")])
    assert len(result)==2


def test_invalid_unavailable_size_or_progress_cannot_be_synthetic_delete():
    append=_method("_append_downloader_incomplete")
    assert append([],[_raw(.4,A,size=0)])==[]
    assert append([],[_raw(None,A)])==[]
    assert append([],[_raw(.4,"")])==[]


def test_actual_collector_includes_downloader_only_incomplete_even_with_empty_site():
    collect=_method("_collect_rescue_seeds")
    append=_method("_append_downloader_incomplete")
    import types
    torrent={"name":NAME,"hash":A,
             "size":int(41.34*1073741824),"progress":0.4,
             "tracker":"", "state":"downloading"}
    fake=SimpleNamespace(
        _fetch_completed=lambda logs:[],
        _downloaders=["QB"],
        _get_manage_services=lambda:{"QB":SimpleNamespace(instance=SimpleNamespace(
            get_torrents=lambda:([torrent],False)),config=SimpleNamespace(type="qbittorrent"))},
        _get_progress_ratio=lambda t,dl:t["progress"],
        _extract_tracker_text=lambda t,dl:"",
        _append_downloader_incomplete=append,
        _list_warning="",
    )
    result=collect(fake)
    assert len(result)==1
    assert result[0]["source"]=="downloader"
    assert result[0]["can_delete_group"]
    assert result[0]["seed_id"]<0


def test_ui_has_separate_download_incomplete_filter_and_selection_keys():
    src=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text()
    assert 'data-tier="incomplete"' in src
    assert 'id="cnt_incomplete"' in src
    assert 'id="siteCount"' in src and 'id="downloadCount"' in src
    assert 'function selectedKey(seed)' in src
    assert 'seed.source==="downloader"' in src or 's.source==="downloader"' in src
    assert 'if(curTier==="incomplete"' in src
    assert 'return s.source==="downloader"?"下载器"' in src


def test_group_delete_has_download_only_source_separation():
    src=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text()
    assert 'seed_id == 0' in src
    assert 'seed_id < 0' in src
    assert 'row.get("source") == "downloader"' in src
    group=src.split('    def _delete_rescue_group(')[1].split('    def _delete_rescue_exact(')[0]
    assert '种子未确认完成，拒绝删除' not in group
    assert 'delete_file=True, ids=list(hashes)' in group

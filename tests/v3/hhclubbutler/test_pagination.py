"""Rescue completed-page pagination guards, without network or downloader access."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins.v3/hhclubbutler/__init__.py"


def _fetch_function():
    source=SOURCE.read_text(encoding="utf-8")
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="HHClubButler")
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                and n.name=="_fetch_completed")
    module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
    fake_time=SimpleNamespace(sleep=lambda seconds: None)
    globs={
        "time":fake_time,
        "HHClubButler":SimpleNamespace(_norm_title=lambda name: name.casefold().replace(".",""), _safe_error=str),
        "logger":SimpleNamespace(info=Mock(),error=Mock(),warning=Mock()),
    }
    exec(compile(module,"<no-network-pagination>","exec"),globs)
    return globs["_fetch_completed"]


def _instance(pages):
    calls=[]
    def get(_,url,**kwargs):
        calls.append(url)
        key="0"
        if "&page=" in url:key=url.split("&page=")[-1]
        if key not in pages: raise RuntimeError("missing page")
        return SimpleNamespace(text=key)
    def parse(value):
        page=pages[value]
        if isinstance(page,Exception):raise page
        return page
    obj=SimpleNamespace(
        _get_site_uid=lambda:"24285",
        _get_site_url=lambda:"https://hhanclub.net",
        _session=lambda:object(),
        _get_with_retry=get,
        _parse_completed_page=parse,
    )
    return obj,calls


def test_paginated_inventory_aggregates_all_pages_without_duplicates():
    a={"title":"One.Movie","seed_id":101,"size":4.1}
    b={"title":"Two.Movie","seed_id":102,"size":5.1}
    c={"title":"Three.Movie","seed_id":103,"size":6.1}
    site,calls=_instance({
        "0":([a],2),
        "1":([a,b],2),
        "2":([c],2),
    })
    logs=[]
    rows=_fetch_function()(site,logs)
    assert [r["seed_id"] for r in rows]==[101,102,103]
    assert len(calls)==3
    assert any("去重后可保种记录 3" in v for v in logs)


def test_failed_later_page_discards_complete_snapshot():
    site,calls=_instance({
        "0":([{"title":"Page0","seed_id":1}],3),
        "1":([{"title":"Page1","seed_id":2}],3),
        "2":RuntimeError("timed out"),
        "3":([{"title":"Page3","seed_id":4}],3),
    })
    logs=[]
    rows=_fetch_function()(site,logs)
    assert rows==[]
    assert any("数据不完整" in msg for msg in logs)
    assert len(calls)==3


def test_missing_site_uid_does_not_return_partial_rows():
    site,_=_instance({})
    site._get_site_uid=lambda:None
    logs=[]
    assert _fetch_function()(site,logs)==[]
    assert "未获取到站点UID" in logs


def test_parser_checks_maxpage_and_pagination_links():
    text=SOURCE.read_text(encoding="utf-8")
    assert 'a[href*="page="]' in text
    assert "max_page > 500" in text
    assert "未找到站点保种完成页表格" in text

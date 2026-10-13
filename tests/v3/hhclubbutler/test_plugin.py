"""HHClubButler V3.0.6 contracts and deletion safety without a real downloader."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
CODE = ROOT / "plugins.v3" / "hhclubbutler" / "__init__.py"


def _source() -> str:
    return CODE.read_text(encoding="utf-8")


def _plugin_class() -> ast.ClassDef:
    return next(
        n for n in ast.parse(_source()).body
        if isinstance(n, ast.ClassDef) and n.name == "HHClubButler"
    )


def _method(name: str) -> ast.FunctionDef:
    return next(
        n for n in _plugin_class().body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )


def test_v3_metadata_and_v2_fallback_disabled():
    cls = _plugin_class()
    attrs = {
        target.id: item.value.value
        for item in cls.body
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
        for target in item.targets if isinstance(target, ast.Name)
    }
    market_v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    market_v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    assert attrs["plugin_version"] == "3.0.6"
    assert market_v3["HHClubButler"]["version"] == attrs["plugin_version"]
    assert market_v3["HHClubButler"]["system_version"] == ">=3.0.0"
    assert market_v3["HHClubButler"]["release"] is False
    assert "plugins.v3/hhclubbutler/" in attrs["plugin_icon"]
    assert market_v2["HHClubButler"]["version"] == "2.5"
    assert market_v2["HHClubButler"]["v3"] is False


def test_page_endpoints_require_cookie_admin():
    source = _source()
    assert "verify_resource_token" in source
    assert "identity=Depends(verify_resource_token)" in source
    assert 'getattr(identity, "super_user", False)' in source
    assert 'request.headers.get("X-HHClub-Request") != "1"' in source
    api = _method("get_api")
    api_src = ast.get_source_segment(source, api)
    assert 'page_deps = [Depends(_require_resource_admin)]' in api_src
    assert 'allow_anonymous": True, "dependencies": page_deps' in api_src
    assert api_src.count('"allow_anonymous": True, "dependencies": page_deps') == 6
    assert '"auth": "bear"' in api_src
    assert '"/refresh_overview"' in api_src
    assert '"methods": ["POST"]' in api_src


def test_html_pages_never_embed_server_api_token():
    src = _source()
    assert "settings.API_TOKEN" not in src
    assert "?apikey=" not in src
    assert "__APIKEY__" not in src
    assert "var APIKEY" not in src
    assert "/api/v1/plugin/HHClubButler/rescue_panel" in src
    assert "/api/v1/plugin/HHClubButler/monthly_stats" in src
    assert '"X-HHClub-Request":"1"' in src
    assert 'credentials:"same-origin"' in src
    assert "_build_rescue_panel_html(self)" in src
    assert "_build_monthly_stats_html(self)" in src


def _deletion_method():
    # Compile only the deletion method: no MoviePilot runtime, network or filesystem.
    node = _method("_delete_rescue_exact")
    namespace = {"logger": SimpleNamespace(info=Mock(), error=Mock())}
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, "<isolated-delete-method>", "exec"), namespace)
    return namespace["_delete_rescue_exact"]


def _fixture(*, hash_value="HASH123", tracker="https://hhanclub.example/announce",
             torrent_name="Sample.Movie"):
    delete_mock = Mock(return_value=True)
    record = {"name": torrent_name, "hash": hash_value, "tracker": tracker}
    client = SimpleNamespace(
        get_torrents=lambda: ([] if delete_mock.called else [record], None),
        delete_torrents=delete_mock,
    )
    host = SimpleNamespace(
        _enabled=True, _stopped=False, _delete_generation=0,
        _downloaders=["QB"],
        _norm_title=lambda name: (name or "").casefold().replace(".", ""),
        _extract_tracker_text=lambda torrent: torrent.get("tracker", ""),
        _get_current_seeding=lambda logs: {"seeds": [{"title": "Sample.Movie"}]},
        _get_manage_services=lambda: {"QB": SimpleNamespace(instance=client)},
    )
    return host, delete_mock


def test_deletion_rejects_unconfirmed_and_inexact_requests():
    method = _deletion_method()
    instance, deleted = _fixture()
    for kwargs in (
        {"title": "Sample.Movie", "downloader": "QB", "torrent_hash": "HASH123"},
        {"title": "Sample.Movie", "downloader": "UNKNOWN",
         "torrent_hash": "HASH123", "confirm": True},
        {"title": "Sample.Movie", "downloader": "QB",
         "torrent_hash": "otherhash", "confirm": True},
        {"title": "Similar.Movie", "downloader": "QB",
         "torrent_hash": "HASH123", "confirm": True},
    ):
        assert method(instance, **kwargs)["success"] is False
    deleted.assert_not_called()


def test_deletion_requires_matching_site_tracker_and_unique_hash():
    method = _deletion_method()
    instance, deleted = _fixture(tracker="https://other.example/announce")
    assert method(instance, "Sample.Movie", "QB", "HASH123", True)["success"] is False
    deleted.assert_not_called()

    instance, deleted = _fixture()
    result = method(instance, "Sample.Movie", "QB", "HASH123", True)
    assert result["success"] is True
    deleted.assert_called_once_with(delete_file=True, ids=["HASH123"])


def test_no_filename_only_deletion_in_automatic_cleanup():
    source = _source()
    cleaner = ast.get_source_segment(source, _method("_clean_stale_downloads"))
    assert "if not is_site:" in cleaner
    assert "if not is_site and site_titles:" not in cleaner
    washer = ast.get_source_segment(source, _method("_delete_seeds"))
    assert "拒绝跨下载器猜测删除" in washer

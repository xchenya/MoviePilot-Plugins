"""Tracker fields are best effort; they are NOT a required delete gate."""
import ast
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]

def extract():
    source=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text(encoding="utf-8")
    tree=ast.parse(source)
    cls=next(c for c in tree.body if isinstance(c,ast.ClassDef) and c.name=="HHClubButler")
    fn=next(f for f in cls.body if isinstance(f,ast.FunctionDef)
            and f.name=="_extract_tracker_text")
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    scope={}
    exec(compile(module,"<tracker-extract>","exec"),scope)
    return scope["_extract_tracker_text"]

def test_transmission_fields_mapping_contains_tracker_stats():
    tr=SimpleNamespace(fields={"trackerStats":[
        {"announce":"https://tracker.hhanclub.net/announce"},
        {"announce":"udp://other.example:6969/announce"}]})
    s=extract()(tr)
    assert "tracker.hhanclub.net" in s
    assert "other.example" in s

def test_transmission_snake_case_and_nested_object_supported():
    tr=SimpleNamespace(tracker_stats=[SimpleNamespace(announce="https://tracker.hhanclub.net/announce")])
    assert "tracker.hhanclub.net" in extract()(tr)

def test_transmission_camelcase_tracker_list_string_supported():
    tr=SimpleNamespace(trackerList="https://tracker.hhanclub.net/announce\nhttps://other.example")
    result=extract()(tr)
    assert "tracker.hhanclub.net" in result

def test_missing_or_throwing_attribute_does_not_hide_other_tracker_data():
    class TrObject:
        def __getattr__(self,name):
            if name=="tracker":raise RuntimeError("unsupported attribute")
            if name=="trackers":return ["https://tracker.hhanclub.net/announce"]
            raise AttributeError(name)
    result=extract()(TrObject())
    assert "tracker.hhanclub.net" in result

def test_qbittorrent_simple_tracker_string():
    assert "tracker.hhanclub.net" in extract()({"tracker":"https://tracker.hhanclub.net/announce"})

def test_invalid_tracker_is_optional_not_reported_as_hh():
    obj={"tracker":"** [DHT] **"}
    assert extract()(obj)==""
    src=(ROOT/"plugins.v3/hhclubbutler/__init__.py").read_text()
    assert "can_delete_group" in src
    # Tracker restrictions apply only to automatic operations.
    block=src.split("    def _delete_rescue_group(")[1].split("    def _delete_rescue_exact(")[0]
    assert "if auto_mode:" in block

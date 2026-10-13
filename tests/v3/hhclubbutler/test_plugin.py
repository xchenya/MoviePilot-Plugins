"""HHClubButler V3 source contract smoke checks without downloader operations."""
from __future__ import annotations
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CODE = ROOT / "plugins.v3" / "hhclubbutler" / "__init__.py"

def test_v3_plugin_metadata():
    module = ast.parse(CODE.read_text(encoding="utf-8"))
    classes = {item.name: item for item in module.body if isinstance(item, ast.ClassDef)}
    assert "HHClubButler" in classes
    attrs = {target.id: value.value for item in classes["HHClubButler"].body
             if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
             for target in item.targets if isinstance(target, ast.Name)
             for value in [item.value]}
    assert attrs["plugin_version"] == "3.0.0"
    assert "plugins.v3" in attrs["plugin_icon"]
    idx = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert idx["HHClubButler"]["version"] == attrs["plugin_version"]
    assert idx["HHClubButler"]["system_version"] == ">=3.0.0"
    old = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    assert old["HHClubButler"]["v3"] is False

def test_api_auth_does_not_use_legacy_apikey():
    tree = ast.parse(CODE.read_text(encoding="utf-8"))
    api = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "HHClubButler")
    fn = next(node for node in api.body if isinstance(node, ast.FunctionDef)
              and node.name == "get_api")
    auths = [value.value for node in ast.walk(fn) if isinstance(node, ast.Dict)
             for key, value in zip(node.keys, node.values)
             if isinstance(key, ast.Constant) and key.value == "auth" and isinstance(value, ast.Constant)]
    assert auths and all(auth == "bear" for auth in auths)

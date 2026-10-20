"""Download options use inert MP-shaped clients; no live RPC, HTTP or host writes."""
from pathlib import Path
import runpy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

Subject = runpy.run_path(str(Path(__file__).with_name("support.py")))["Subject"]
A, B = "a" * 40, "b" * 40
SEEDS = [{"title": "Fixture Release 2026 1080p", "href": "/download.php?id=1"}]


def configured(config=None):
    obj = Subject()
    obj._apply_hosts = Mock()
    obj._start_overview_thread = Mock()
    obj.update_config = Mock()
    obj.init_plugin(config or {})
    return obj


@pytest.mark.parametrize("value, expected", [(None, 0), ("", 0), (0, 0), ("128", 128), (512.0, 512), ("1024.0", 1024)])
def test_nonnegative_integer_rate_settings(value, expected):
    assert Subject._parse_speed_limit(value) == expected


@pytest.mark.parametrize("value", [-1, "nan", "inf", "12.5", True, 2147483648, {}, []])
def test_invalid_rate_cannot_silently_become_unlimited(value):
    obj = configured({"enabled": True, "upload_limit": value})
    obj._get_site_cookie = Mock()
    obj._do_run = Mock()
    obj.run()
    obj._get_site_cookie.assert_not_called()
    obj._do_run.assert_not_called()
    assert "限速" in obj._last_result
    assert obj._push_seeds(SEEDS, [])[0:2] == (0, 1)


def test_default_and_existing_custom_or_empty_tags():
    assert configured()._tag == "hh"
    assert configured({"tag": "保种专用"})._tag == "保种专用"
    assert configured({"tag": ""})._tag == ""
    obj = configured()
    form, defaults = obj.get_form()
    assert defaults["tag"] == "hh"
    assert defaults["upload_limit"] == defaults["download_limit"] == 0
    assert defaults["use_proxy"] is False
    def fields(nodes):
        for node in nodes:
            yield node.get("props", {})
            yield from fields(node.get("content", []))
    models = [props["model"] for props in fields(form) if "model" in props]
    for model in ("tag", "upload_limit", "download_limit", "use_proxy"):
        assert models.count(model) == 1


def test_run_once_preserves_all_options_and_legacy_config(monkeypatch):
    scope = Subject.init_plugin.__globals__
    scheduler = Mock()
    monkeypatch.setitem(scope, "BackgroundScheduler", Mock(return_value=scheduler))
    cfg = {"enabled": True, "onlyonce": True, "tag": "保种", "upload_limit": "512",
           "download_limit": "1024", "use_proxy": True,
           "hosts_enabled": True, "hosts_config": "127.0.0.2 fixture.invalid", "future_option": "keep"}
    obj = configured(cfg)
    saved = obj.update_config.call_args.args[0]
    assert all(saved[key] == value for key, value in dict(cfg, onlyonce=False).items())
    assert obj._upload_limit == 512 and obj._download_limit == 1024 and obj._use_proxy
    scheduler.add_job.assert_called_once()
    scheduler.start.assert_called_once()  # Mock scheduler never executes the job.


def test_invalid_run_once_rate_remains_invalid_after_save_and_reload(monkeypatch):
    monkeypatch.setitem(Subject.init_plugin.__globals__, "BackgroundScheduler", Mock())
    obj = configured({"onlyonce": True, "upload_limit": "invalid"})
    saved = obj.update_config.call_args.args[0]
    assert saved["upload_limit"] == "invalid" and saved["onlyonce"] is False
    assert configured(saved)._download_options_error


class Session:
    def __init__(self):
        self.headers, self.proxies = {}, {}
        self.trust_env = True


@pytest.mark.parametrize("use_proxy", [False, True])
def test_session_proxy_switch_uses_mp_mapping_only(monkeypatch, use_proxy):
    obj = configured({"use_proxy": use_proxy})
    obj._get_mp_site = lambda: NS(ua="fixture-agent")
    obj._get_site_cookie = lambda: "fixture=not-a-live-cookie"
    proxies = {"http": "http://fixture-proxy.invalid:8080", "https": "http://fixture-proxy.invalid:8080"}
    scope = Subject._session.__globals__
    monkeypatch.setitem(scope, "settings", NS(PROXY=proxies))
    monkeypatch.setitem(scope, "requests", NS(Session=Session))
    monkeypatch.setenv("HTTPS_PROXY", "http://unwanted-environment.invalid:8080")
    session = obj._session()
    assert session.trust_env is False
    assert session.proxies == (proxies if use_proxy else {})
    assert session.headers["User-Agent"] == "fixture-agent"
    assert session.headers["Cookie"] == "fixture=not-a-live-cookie"


def test_enabled_proxy_without_mp_config_does_not_fall_back_to_direct(monkeypatch):
    obj = configured({"use_proxy": True})
    factory = Mock()
    scope = Subject._session.__globals__
    monkeypatch.setitem(scope, "settings", NS(PROXY=None))
    monkeypatch.setitem(scope, "requests", NS(Session=factory))
    with pytest.raises(RuntimeError, match="MP 未配置"):
        obj._session()
    factory.assert_not_called()


class QB:
    def __init__(self):
        self.added = []
        self.set_speed_limit = Mock(side_effect=AssertionError("Never change global speed limits"))

    def add_torrent(self, content, download_dir=None, cookie=None, tag=None,
                    ignore_category_check=True, upload_limit=None, download_limit=None):
        self.added.append(dict(content=content, download_dir=download_dir, cookie=cookie, tag=tag,
                               ignore_category_check=ignore_category_check,
                               upload_limit=upload_limit, download_limit=download_limit))
        return True, [A]


class TR:
    def __init__(self):
        self.events, self.existing = [], []
        self.result = NS(hashString=A)
        self.change_result, self.start_result = True, True
        self.get_error = False
        self.set_speed_limit = Mock(side_effect=AssertionError("Never change global speed limits"))

    def get_torrents(self):
        self.events.append(("read",))
        return self.existing, self.get_error

    def add_torrent(self, content, is_paused=False, download_dir=None, labels=None, cookie=None):
        self.events.append(("add", is_paused, labels, download_dir))
        return self.result

    def change_torrent(self, hash_string, upload_limit=None, download_limit=None):
        self.events.append(("limit", hash_string, upload_limit, download_limit))
        return self.change_result

    def start_torrents(self, ids):
        self.events.append(("start", ids))
        return self.start_result


def push_host(monkeypatch, kind, client, **config):
    obj = configured(dict(config, enabled=True, save_path="/fixture/new-tasks"))
    obj._session = lambda: object()
    obj._get_site_cookie = lambda: "fixture-only"
    obj._get_site_url = lambda: "https://hhanclub.net"
    obj._get_downloader_obj = lambda: NS(instance=client, config=NS(type=kind))
    obj._download_response = Mock(return_value=NS(status_code=200, content=b"inert fixture torrent"))
    monkeypatch.setattr(Subject._push_seeds.__globals__["time"], "sleep", lambda _: None)
    return obj


@pytest.mark.parametrize("up, down", [(0, 0), (128, 0), (0, 512), (128, 512)])
def test_qb_limits_are_atomic_and_converted_to_bytes(monkeypatch, up, down):
    client = QB()
    obj = push_host(monkeypatch, "qbittorrent", client, upload_limit=up, download_limit=down, tag="custom")
    assert obj._push_seeds(SEEDS, [])[0:2] == (1, 0)
    args = client.added[0]
    assert args["upload_limit"] == (up * 1024 if up else None)
    assert args["download_limit"] == (down * 1024 if down else None)
    assert args["tag"] == "custom" and args["download_dir"] == "/fixture/new-tasks"
    assert args["ignore_category_check"] is False
    client.set_speed_limit.assert_not_called()


@pytest.mark.parametrize("tag, expected", [(None, "hh"), ("custom", "custom"), ("", None)])
def test_qb_default_custom_and_disabled_tags(monkeypatch, tag, expected):
    client = QB()
    obj = push_host(monkeypatch, "qbittorrent", client, **({"tag": tag} if tag is not None else {}))
    obj._push_seeds(SEEDS, [])
    assert client.added[0]["tag"] == expected


@pytest.mark.parametrize("up, down", [(128, 0), (0, 512), (128, 512)])
def test_tr_adds_paused_sets_per_torrent_limits_then_starts(monkeypatch, up, down):
    client = TR()
    client.existing = [NS(hashString=B)]
    obj = push_host(monkeypatch, "transmission", client, upload_limit=up, download_limit=down)
    assert obj._push_seeds(SEEDS, [])[0:2] == (1, 0)
    assert client.events == [("read",), ("add", True, ["hh"], "/fixture/new-tasks"),
                             ("limit", A, up, down), ("start", [A])]
    client.set_speed_limit.assert_not_called()


def test_tr_zero_limits_keep_existing_add_flow(monkeypatch):
    client = TR()
    obj = push_host(monkeypatch, "transmission", client, tag="custom")
    assert obj._push_seeds(SEEDS, [])[0:2] == (1, 0)
    assert client.events == [("add", False, ["custom"], "/fixture/new-tasks")]


@pytest.mark.parametrize("cause", ["add-false", "limit-false", "limit-none", "limit-exception", "missing-hash", "duplicate", "read-error", "start-false"])
def test_tr_failures_never_modify_global_limits_or_retry_addition(monkeypatch, cause):
    client = TR()
    if cause == "add-false":
        client.result = None
    elif cause == "limit-false":
        client.change_result = False
    elif cause == "limit-none":
        client.change_result = None
    elif cause == "limit-exception":
        client.change_torrent = Mock(side_effect=TimeoutError("https://proxy.invalid/a?token=FAKE_SECRET"))
    elif cause == "missing-hash":
        client.result = NS(id=1)
    elif cause == "duplicate":
        client.existing = [NS(hashString=A)]
    elif cause == "read-error":
        client.get_error = True
    elif cause == "start-false":
        client.start_result = False
    obj = push_host(monkeypatch, "transmission", client, upload_limit=128)
    result = obj._push_seeds(SEEDS, [])
    assert result[0:2] == (0, 1) and len(result[2]) == 1
    assert "FAKE_SECRET" not in result[2][0]["reason"]
    assert sum(event[0] == "add" for event in client.events) <= 1
    if cause != "start-false":
        assert not any(event[0] == "start" for event in client.events)
    if cause in {"duplicate", "missing-hash", "read-error"}:
        assert not any(event[0] == "limit" for event in client.events)


@pytest.mark.parametrize("stop_at", ["read", "add", "limit"])
def test_disable_during_tr_io_prevents_later_writes(monkeypatch, stop_at):
    client = TR()
    obj = push_host(monkeypatch, "transmission", client, download_limit=512)
    method_name = {"read": "get_torrents", "add": "add_torrent", "limit": "change_torrent"}[stop_at]
    original = getattr(client, method_name)
    def stopped(*args, **kwargs):
        result = original(*args, **kwargs)
        obj.stop_service()
        return result
    setattr(client, method_name, stopped)
    assert obj._push_seeds(SEEDS, [])[0:2] == (0, 1)
    assert not any(event[0] == "start" for event in client.events)
    if stop_at == "read":
        assert not any(event[0] == "add" for event in client.events)


def test_unknown_downloader_with_limits_is_rejected_before_http_or_rpc(monkeypatch):
    client = QB()
    obj = push_host(monkeypatch, "unknown", client, upload_limit=128)
    assert obj._push_seeds(SEEDS, [])[0:2] == (0, 1)
    assert client.added == []
    obj._download_response.assert_not_called()

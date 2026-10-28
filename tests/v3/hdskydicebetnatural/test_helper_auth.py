"""Full plugin import with SDK/HTTP doubles: no main-site, betting or live auth writes."""
import base64
import copy
import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3/hdskydicebetnatural"


def jwt(uid="123", expires=None):
    data = {"userId": uid, "exp": expires or int(time.time()) + 900}
    return "fixture." + base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=") + ".signature"


class Response:
    def __init__(self, payload=None, status=200, headers=None):
        self.status_code = status
        self.payload = {"success": True} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Base:
    def __init__(self):
        self.data, self.saved_config = {}, {}

    def get_data(self, key):
        return copy.deepcopy(self.data.get(key))

    def save_data(self, key, value):
        self.data[key] = copy.deepcopy(value)

    def update_config(self, config):
        self.saved_config = copy.deepcopy(config)


@pytest.fixture
def host(monkeypatch):
    for name in ("app", "app.sdk", "app.sdk.plugin", "app.sdk.logging", "app.sdk.config",
                 "app.sdk.network", "app.schemas", "app.schemas.types",
                 "app.db", "app.db.oper", "app.db.oper.site"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["app.sdk.plugin"]._PluginBase = Base
    sys.modules["app.sdk.config"].settings = types.SimpleNamespace(TZ="Asia/Shanghai", PROXY={"https": "http://proxy.test:7890"})
    sys.modules["app.sdk.logging"].logger = types.SimpleNamespace(info=Mock(), warning=Mock(), error=Mock(), debug=Mock())
    sys.modules["app.db.oper.site"].SiteOper = Mock()
    sys.modules["app.sdk.network"].SitesHelper = Mock()
    sys.modules["app.sdk.network"].RequestUtils = Mock(side_effect=AssertionError("unexpected network"))
    sys.modules["app.schemas.types"].NotificationType = types.SimpleNamespace(Plugin="plugin")
    name = "_hdsky_dice_login_integration"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    for child in ("helper_auth", "ticket_inbox"):
        monkeypatch.delitem(sys.modules, name + "." + child, raising=False)
    spec.loader.exec_module(module)
    p = module.HdskyDiceBetNatural()
    p._list_hdsky_sites = lambda: [{"id": 49, "name": "天空", "domain": "hdsky.me",
                                  "url": "https://hdsky.me", "cookie": "main-cookie-private",
                                  "proxy": True, "ua": "test-agent"}]
    p.init_plugin({"enabled": False, "site_id": 49, "bet_amount": 500, "cron": "*/5 * * * *"})
    p._run_internal = Mock(side_effect=AssertionError("must not bet"))
    p.run_once = Mock(side_effect=AssertionError("must not bet"))
    return p, module


def action(p, m, name, **kwargs):
    return p.helper_login_action(m.HelperAuthRequest(
        action=name, uid="123", email="user@example.test", **kwargs))


def send(p, m):
    p._helper_login_post = Mock(return_value=Response())
    result = action(p, m, "send")
    assert result.success
    return result


def login(p, m):
    send(p, m)
    p._helper_login_post.return_value = Response({"success": True, "data": {
        "accessToken": jwt(), "refreshToken": "refresh-private",
        "user": {"userId": "123"},
    }})
    result = action(p, m, "login", code="012345")
    assert result.success
    return result


def test_login_completes_without_saving_or_reloading_config(host):
    p, m = host
    settings_before = copy.deepcopy(p._config)
    r = login(p, m)
    assert r.state.configured and r.state.uid == "123"
    p._helper_login_post.assert_called_with("login", {
        "userId": "123", "email": "user@example.test", "code": "012345"}, None)
    assert p._helper_cookie == jwt()
    assert p._helper_refresh_token == "refresh-private"
    assert p.data["helper_credentials"]["refresh_token"] == "refresh-private"
    assert "012345" not in json.dumps(p.data)
    assert p._config["bet_amount"] == settings_before["bet_amount"]
    p.run_once.assert_not_called()
    p._run_internal.assert_not_called()
    assert not r.state.pending_uid


def test_no_token_or_code_is_returned_in_public_state_or_form(host):
    p, m = host
    login(p, m)
    form, defaults = p.get_form()
    assert defaults["helper_cookie"] == defaults["helper_refresh_token"] == defaults["helper_code"] == ""
    text = json.dumps([p._helper_auth.state().model_dump(), form, defaults, p.saved_config])
    assert "refresh-private" not in text
    assert jwt() not in text
    assert "012345" not in text


def test_save_other_settings_after_login_and_restart_preserves_tokens(host):
    p, m = host
    form, defaults_before = p.get_form()
    login(p, m)
    config = {**p._config, **defaults_before, "site_id": 49, "bet_amount": 700}
    p.init_plugin(config)  # This open form still contains blank credential inputs.
    assert p._helper_refresh_token == "refresh-private"
    assert p._helper_cookie == jwt()
    assert p._config["bet_amount"] == 700
    restarted = m.HdskyDiceBetNatural()
    restarted.data = copy.deepcopy(p.data)
    restarted._list_hdsky_sites = p._list_hdsky_sites
    restarted.init_plugin(p.saved_config)
    assert restarted._helper_refresh_token == "refresh-private"
    assert restarted._helper_cookie == jwt()


def test_legacy_config_migrates_without_credentials_in_saved_config(host):
    p, _ = host
    p.init_plugin({**p._config, "helper_cookie": jwt(), "helper_refresh_token": "legacy-private"})
    assert p._helper_cookie == jwt()
    assert p.data["helper_credentials"]["refresh_token"] == "legacy-private"
    assert not p.saved_config.get("helper_cookie")
    assert not p.saved_config.get("helper_refresh_token")


def test_saving_native_form_never_persists_temporary_login_fields(host):
    p, _ = host
    p.init_plugin({**p._config, "helper_uid": "123", "helper_email": "user@example.test",
                   "helper_code": "654321", "helper_busy": True, "helper_plugin_id": "bad"})
    assert all(k not in p.saved_config for k in (
        "helper_uid", "helper_email", "helper_code", "helper_busy", "helper_plugin_id"))
    assert not p._helper_cookie


def test_send_cooldown_survives_reload_and_uid_changes(host):
    p, m = host
    send(p, m)
    p.init_plugin(p._config)
    result = action(p, m, "send")
    assert not result.success and "60" in result.message
    result = p.helper_login_action(m.HelperAuthRequest(action="send", uid="456", email="next@example.test"))
    assert not result.success
    assert p._helper_login_post.call_count == 1


@pytest.mark.parametrize("uid,email", [("0", "u@example.test"), ("123", "not-email"), ("1\n", "bad"), ("<123>", "u@example.test")])
def test_invalid_identity_never_sends_network(host, uid, email):
    p, m = host
    p._helper_login_post = Mock(side_effect=AssertionError("network"))
    result = p.helper_login_action(m.HelperAuthRequest(action="send", uid=uid, email=email))
    assert not result.success
    p._helper_login_post.assert_not_called()


def test_login_requires_pending_identity_and_six_digits(host):
    p, m = host
    p._helper_login_post = Mock(side_effect=AssertionError("network"))
    assert not action(p, m, "login", code="012345").success
    p._helper_login_post.assert_not_called()
    send(p, m)
    assert not action(p, m, "login", code="123").success
    assert not p.helper_login_action(m.HelperAuthRequest(action="login", uid="123", email="other@example.test", code="012345")).success
    assert p._helper_login_post.call_count == 1


def test_send_timeout_keeps_pending_but_does_not_automatically_retry(host):
    p, m = host
    p._helper_login_post = Mock(side_effect=TimeoutError("code-secret"))
    r = action(p, m, "send")
    assert not r.success and r.state.pending_uid == "123"
    assert not action(p, m, "send").success
    assert p._helper_login_post.call_count == 1
    assert "code-secret" not in r.message


@pytest.mark.parametrize("response", [
    Response({"success": False, "message": "private-token-value"}),
    Response(ValueError("raw-secret")),
    Response(status=403), Response(status=302), Response(status=500),
    Response({"success": True, "data": {}}),
    Response({"success": True, "data": {"accessToken": "access-private"}}),
    Response({"success": True, "data": {"accessToken": jwt("456"), "refreshToken": "refresh-private"}}),
    Response({"success": True, "data": {"accessToken": jwt(), "refreshToken": "refresh-private", "user": {"userId": "456"}}}),
])
def test_login_failure_preserves_old_pair_without_echoing_remote_content(host, response):
    p, m = host
    p._helper_auth.save_tokens("old-access-private", "old-refresh-private", "old", "old@example.test")
    send(p, m)
    p._helper_login_post.return_value = response
    r = action(p, m, "login", code="012345")
    assert not r.success
    assert p._helper_cookie == "old-access-private" and p._helper_refresh_token == "old-refresh-private"
    assert "private" not in r.message and "raw-secret" not in r.message


def test_login_attempts_are_throttled(host):
    p, m = host
    send(p, m)
    p._helper_login_post.return_value = Response({"success": False})
    assert not action(p, m, "login", code="012345").success
    assert not action(p, m, "login", code="012345").success
    assert p._helper_login_post.call_count == 2


def test_429_honors_retry_after_without_replay(host):
    p, m = host
    p._helper_login_post = Mock(return_value=Response(status=429, headers={"Retry-After": "120"}))
    r = action(p, m, "send")
    assert not r.success and r.state.retry_after > time.time() + 100
    p.init_plugin(p._config)
    r = action(p, m, "send")
    assert "冷却" in r.message and p._helper_login_post.call_count == 1


def test_rotated_tokens_not_overwritten_by_form_save(host):
    p, m = host
    login(p, m)
    p._persist_helper_tokens(jwt(expires=int(time.time()) + 1800), "rotated-private")
    p.init_plugin({**p._config, "helper_cookie": "", "helper_refresh_token": "", "notify": False})
    assert p._helper_refresh_token == "rotated-private"
    assert not p._config.get("helper_cookie") and not p._config.get("helper_refresh_token")


def test_credential_persistence_failure_does_not_activate_pair(host):
    p, m = host
    send(p, m)
    original = p.save_data
    p.save_data = lambda key, value: False if key == "helper_credentials" else original(key, value)
    p._helper_login_post.return_value = Response({"success": True, "data": {
        "accessToken": jwt(), "refreshToken": "refresh-private"}})
    r = action(p, m, "login", code="012345")
    assert not r.success and not r.state.configured
    assert not p._helper_cookie


def test_login_is_not_reentered_by_parallel_request(host):
    p, m = host
    started, release = threading.Event(), threading.Event()
    def transport(*args):
        started.set()
        assert release.wait(3)
        return Response()
    p._helper_login_post = Mock(side_effect=transport)
    thread = threading.Thread(target=lambda: action(p, m, "send"))
    thread.start()
    try:
        assert started.wait(3)
        r = action(p, m, "send")
        assert not r.success and "正在处理" in r.message
        assert p._helper_login_post.call_count == 1
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()


def test_endpoint_auth_models_and_instance_scope(host):
    p, m = host
    endpoint = p.get_api()[0]
    assert endpoint["auth"] == "bear" and endpoint["methods"] == ["POST"]
    assert endpoint["response_model"] is m.HelperAuthResult
    assert endpoint["path"] == "/helper/auth"
    with pytest.raises(ValueError):
        m.HelperAuthRequest(action="send", url="https://other.test")
    p.__class__ = type("HdskyDiceBetNatural_custom", (m.HdskyDiceBetNatural,), {})
    form, defaults = p.get_form()
    assert defaults["helper_plugin_id"] == "HdskyDiceBetNatural_custom"
    assert "helper_code" not in p._config


def test_network_uses_only_auth_paths_selected_site_connection_and_no_old_credentials(host, monkeypatch):
    p, m = host
    network = Mock()
    network.return_value.post_res.return_value = Response()
    monkeypatch.setattr(m, "RequestUtils", network)
    result = p._helper_login_post("send", {"userId": "123", "email": "user@example.test", "code": ""}, 49)
    args = network.call_args.kwargs
    assert args["proxies"] == m.settings.PROXY
    assert args["headers"]["User-Agent"] == "test-agent"
    assert "Cookie" not in args["headers"] and "Authorization" not in args["headers"]
    request = network.return_value.post_res.call_args.kwargs
    assert request["url"] == "https://helper.hdsky.me/api/user/send-code"
    assert request["allow_redirects"] is False
    p._helper_login_post("login", {"userId": "123", "email": "user@example.test", "code": "012345"}, 49)
    assert network.return_value.post_res.call_args.kwargs["url"].endswith("/api/user/login")


def test_manual_import_is_saved_immediately_and_status_is_readonly(host):
    p, m = host
    p._helper_login_post = Mock(side_effect=AssertionError("no HTTP"))
    r = action(p, m, "import", access_token="access-private", refresh_token="refresh-private")
    assert r.success and r.state.configured and p._helper_cookie == "access-private"
    assert action(p, m, "status").success
    p._helper_login_post.assert_not_called()

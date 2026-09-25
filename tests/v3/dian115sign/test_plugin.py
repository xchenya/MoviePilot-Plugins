"""Unit and lifecycle regressions: no network or real MoviePilot database."""
import json
from threading import Event
from types import SimpleNamespace

import pytest
from app.plugins.dian115sign import Dian115Sign
from app.plugins.dian115sign.browser import (
    API, ORIGIN, BrowserRunner, Options, Outcome, PortalError, SubmissionGuard,
    Trace, initial_cookies, number, safe_code, same_origin, seed_cookies,
)

@pytest.mark.parametrize("raw", ["abc.def.ghi", "Bearer abc.def.ghi", "Authorization: Bearer abc.def.ghi"])
def test_bare_token(raw):
    cookies = seed_cookies(raw)
    assert cookies[0]["name"] == "__Host-portal_token"
    assert cookies[0]["value"] == "abc.def.ghi"
    assert cookies[0]["url"] == ORIGIN + "/"
    assert cookies[0]["secure"]

def test_complete_cookie_not_discarded():
    result = seed_cookies("__Host-portal_token=abc.def.ghi; cf_clearance=clear; pref=one")
    assert {c["name"] for c in result} == {"__Host-portal_token", "cf_clearance", "pref"}


def test_portal_token_field_accepts_complete_cookie():
    result = seed_cookies("portal_token=abc.def.ghi; __Host-portal_browser=browser-session")
    assert {c["name"] for c in result} == {"portal_token", "__Host-portal_browser"}

def test_cookie_attributes_are_not_cookies():
    result = seed_cookies(cookie="a=one; Path=/; Secure; HttpOnly; SameSite=Lax")
    assert [c["name"] for c in result] == ["a"]

def test_bad_cookie_rejected():
    with pytest.raises(PortalError):
        seed_cookies(cookie="token=secret\r\nInjected: x")


def test_password_login_ignores_stale_invalid_seed():
    cookies, ignored = initial_cookies(Options(
        email="user@example.com", password="secret", token="stale-invalid-token"
    ))
    assert cookies == [] and ignored is True


def test_invalid_seed_without_password_still_fails():
    with pytest.raises(PortalError) as error:
        initial_cookies(Options(token="stale-invalid-token"))
    assert error.value.code == "cookie_invalid"

@pytest.mark.parametrize("url", ["https://www.baidu.com", "https://m.dian115.com.evil.test/", "http://m.dian115.com", "https://user:pass@m.dian115.com", "https://m.dian115.com:8443/"])
def test_off_origin_rejected(url):
    assert not same_origin(url)

def test_identity_tracks_credentials_and_proxy():
    opt = Options(email="x", password="y")
    assert opt.identity() == opt.identity()
    assert opt.identity() != Options(email="x", password="z").identity()
    assert opt.identity() != opt.identity("http://proxy:1")
    assert "x" not in opt.identity()

@pytest.mark.parametrize("value", [True, "nan", "inf", None, {}, "bad"])
def test_numeric_sanity(value):
    assert number(value) is None

class FakeResponse:
    def __init__(self, path, status=200, body=None, method="GET", url=None):
        self.url = url or ORIGIN + path
        self.status = status
        self.body = body or {}
        self.request = SimpleNamespace(method=method)
        self.headers = {"content-type": "application/json; charset=utf-8"}
    def json(self):
        return self.body

def test_403_is_not_token_expiry_and_no_secrets():
    trace = Trace()
    trace.response(FakeResponse(f"{API}/auth/browser-challenge", 403,
                               {"code": "access_denied", "msg": "SECRET_PASSWORD", "token": "secret"}))
    assert trace.gate_error().code == "access_denied"
    assert not trace.auth_failed
    assert "secret" not in json.dumps(trace.rows).lower()

def test_only_explicit_auth_code_indicates_auth_failure():
    trace = Trace()
    trace.response(FakeResponse(f"{API}/me", 401, {"code": "invalid_token"}))
    assert trace.auth_failed
    assert trace.gate_error() is None

def test_wrong_origin_and_unrelated_paths_ignored():
    trace = Trace()
    trace.response(FakeResponse(f"{API}/me", url="https://evil.test/api/portal/me"))
    trace.response(FakeResponse("/unrelated", body={"secret": "x"}))
    assert trace.rows == []

class FakeRoute:
    def __init__(self, mode="normal", path=None):
        self.request = SimpleNamespace(url=ORIGIN + (path or f"{API}/signin"),
                                       method="POST", post_data_json={"mode": mode})
        self.sent = self.aborted = False
    def continue_(self): self.sent = True
    def abort(self): self.aborted = True

@pytest.mark.parametrize("diagnose,mode,expected", [(True,"normal","diagnostic_write_blocked"), (False,"lucky","mode_mismatch")])
def test_write_guard(diagnose, mode, expected):
    guard = SubmissionGuard("normal", diagnose, Event(), lambda: True)
    route = FakeRoute(mode)
    guard.route(route)
    assert route.aborted and not route.sent and guard.error.code == expected

def test_only_one_signin():
    guard = SubmissionGuard("normal", False, Event(), lambda: True)
    first, second = FakeRoute(), FakeRoute()
    guard.route(first); guard.route(second)
    assert first.sent and second.aborted and guard.sent == 1

def test_persistence_failure_blocks_write():
    guard = SubmissionGuard("normal", False, Event(), lambda: False)
    route = FakeRoute(); guard.route(route)
    assert route.aborted and not route.sent

def test_cancel_blocks_write():
    cancel = Event(); cancel.set()
    guard = SubmissionGuard("normal", False, cancel, lambda: True)
    route = FakeRoute(); guard.route(route)
    assert route.aborted

def test_init_does_not_launch_network_and_once_uses_host_scheduler():
    p = Dian115Sign(); p.init_plugin({"onlyonce": True, "enabled": False})
    assert p.get_state()
    assert p.saved_config["onlyonce"] is False
    assert p.get_service()[0]["id"] == "Dian115Sign.Once"
    p.stop_service(); assert not p.get_service()

def test_reload_cancels_previous_generation():
    p = Dian115Sign(); p.init_plugin({"enabled": True})
    old = p._cancel
    p.init_plugin({"enabled": True})
    assert old.is_set() and p._cancel is not old and not p._cancel.is_set()
    assert len(p.get_service()) == 1

def test_cache_page_never_runs_network(monkeypatch):
    p = Dian115Sign(); p.init_plugin({})
    monkeypatch.setattr(p, "_run", lambda **kw: pytest.fail("page started network"))
    assert p.get_page()
    assert p.api_status().data.code == "not_started"

def test_post_actions_and_get_status_contract():
    api = {item["path"]: item for item in Dian115Sign().get_api()}
    assert api["/signin"]["methods"] == ["POST"]
    assert api["/status"]["methods"] == ["GET"]
    assert all(item["auth"] == "bear" and item["response_model"] for item in api.values())

def test_instance_specific_ids():
    class Dian115SignSecond(Dian115Sign):
        pass
    p = Dian115SignSecond(); p.init_plugin({"enabled": True})
    assert p.get_service()[0]["id"].startswith("Dian115SignSecond.")
    assert p.get_command()[0]["data"]["action"] == "Dian115SignSecond.run"

def test_parallel_run_rejected():
    p = Dian115Sign(); p.init_plugin({"enabled": True})
    with p._run_lock:
        assert p._run(manual=True)["code"] == "busy"

def test_bad_cron_does_not_raise_during_registration():
    p = Dian115Sign(); p.init_plugin({"enabled": True, "cron": "bad"})
    assert not p.get_state() and not p.get_service()

def test_defaults_are_diagnostic_and_normal():
    d = Dian115Sign._defaults()
    assert d["diagnose_only"] and not d["lucky_mode"]


def test_visible_token_takes_precedence_over_hidden_legacy_cookie():
    p = Dian115Sign()
    p.init_plugin({"token": "abc.def.ghi", "cookie": "portal_token=old.value.token"})
    assert p._options.token == "abc.def.ghi"
    assert p._options.cookie == ""


@pytest.mark.parametrize("text,expected", [
    ("net::ERR_PROXY_CONNECTION_FAILED PRIVATE_PASSWORD", "proxy_failed"),
    ("net::ERR_NAME_NOT_RESOLVED", "dns_failed"),
    ("net::ERR_CERT_DATE_INVALID", "tls_failed"),
    ("Executable doesn't exist at /private/path", "browser_missing"),
    ("net::ERR_BLOCKED_BY_ADMINISTRATOR", "browser_policy_block"),
    ("PRIVATE_PASSWORD unknown error", "browser_error"),
])
def test_browser_error_classification_redacts_details(text, expected):
    from app.plugins.dian115sign.browser import browser_failure
    failure = browser_failure(RuntimeError(text))
    assert failure.code == expected
    assert "PRIVATE_PASSWORD" not in str(failure)
    assert "/private/path" not in str(failure)

"""Real Chromium + in-memory mock site. No public website or account is accessed.

The wrapper changes the guard's network continuation into route.fallback(), so
all requests end in fixture responses instead of the Internet. DOM, cookies,
clicks, page navigation and response events use the real Playwright browser.
"""
import json
import os
from threading import Event
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from app.plugins.dian115sign.browser import API, ORIGIN, BrowserRunner, Options

HTML = r'''<!doctype html><html><body><div id="app">Loading</div>
<script>
const app = document.querySelector('#app');
async function boot() {
 const gate = await fetch('/api/portal/auth/browser-challenge');
 if (!gate.ok) { app.innerText='Access denied'; return; }
 const me = await fetch('/api/portal/me');
 if (!me.ok) {
  app.innerHTML='<form><input type="email" name="email"><input type="password"><button type="submit">登录</button></form>';
  app.querySelector('form').onsubmit = async e => {
   e.preventDefault();
   const email = app.querySelector('input[type=email]').value;
   const password = app.querySelector('input[type=password]').value;
   await fetch('/api/portal/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
  };
  return;
 }
 const user = await me.json();
 let mode='normal';
 app.innerHTML='<button id="normal">普通签</button><button id="lucky">运气签</button>';
 const submit = async m => {
  try { await fetch('/api/portal/signin', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:m})}); }
  catch(e) { }
 };
 if (STYLE === 'toggle') {
  app.innerHTML += '<button id="submit">立即签到</button>';
  app.querySelector('#normal').onclick=()=>{mode='normal';};
  app.querySelector('#lucky').onclick=()=>{mode='lucky';};
  app.querySelector('#submit').onclick=()=>submit(mode);
 } else if (STYLE === 'wrong') {
  app.querySelector('#normal').onclick=()=>submit('lucky');
  app.querySelector('#lucky').onclick=()=>submit('normal');
 } else {
  app.querySelector('#normal').onclick=()=>submit('normal');
  app.querySelector('#lucky').onclick=()=>submit('lucky');
 }
 if (AUTO_SIGN) submit('normal');
}
boot();
</script></body></html>'''

@pytest.fixture(scope="module")
def chromium():
    executable = os.environ.get("DIAN115_CHROMIUM", "/usr/bin/chromium")
    if not os.path.isfile(executable):
        pytest.skip("Offline real-browser tests require DIAN115_CHROMIUM executable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True,
                                     args=["--no-sandbox", "--disable-dev-shm-usage"])
        probe = browser.new_context()
        probe.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<html></html>"))
        try:
            probe.new_page().goto(ORIGIN + "/", timeout=3000)
        except Exception as error:
            if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(error):
                probe.close()
                browser.close()
                pytest.skip("Chromium managed URL policy blocks navigation even for intercepted offline fixtures")
            raise
        probe.close()
        yield browser
        browser.close()

class FallbackRoute:
    def __init__(self, route): self._route = route
    @property
    def request(self): return self._route.request
    def continue_(self): self._route.fallback()
    def abort(self): self._route.abort()

class Context:
    def __init__(self, real, state): self.real, self.state = real, state
    def __getattr__(self, name): return getattr(self.real, name)
    def route(self, pattern, handler):
        self.real.route(pattern, lambda route: handler(FallbackRoute(route)))
    def close(self):
        self.real.close()
        self.state["closed"] += 1


def exercise(chromium, *, diagnose=False, lucky=False, style="direct", gate_status=200,
             authenticated=True, already=False, sign_status=200, sign_code="ok",
             lost_response=False, pending=False, redirect=False, auto_sign=False,
             save_fails=False, seed=False, conflict_marks_signed=False):
    state = {"sign_calls": 0, "login_calls": 0, "closed": 0, "saved": 0,
             "pending": pending, "auth": authenticated, "gate_calls": 0,
             "cookies_seen": "", "signed": already, "points": 100, "streak": 3}
    options = Options(email="example@example.invalid", password="PRIVATE_PASSWORD",
                      token="header.payload.signature" if seed else "",
                      lucky_mode=lucky, timeout=2)

    def serve(route):
        req = route.request
        path = urlsplit(req.url).path
        if path == "/me/signin" and redirect:
            route.fulfill(status=302, headers={"Location": "https://www.baidu.com/"}, body="")
            return
        if path == f"{API}/auth/browser-challenge":
            state["gate_calls"] += 1
            state["cookies_seen"] = req.headers.get("cookie", "")
            route.fulfill(status=gate_status, content_type="application/json",
                          body=json.dumps({"code": "ok" if gate_status == 200 else "access_denied", "msg": "PRIVATE_PASSWORD"}))
        elif path == f"{API}/me":
            data = {"code": "ok", "user": {"points": state["points"],
                    "consecutive_signin": state["streak"],
                    "last_signin_date": options.today() if state["signed"] else "2020-01-01"}}
            if not state["auth"]: data = {"code": "invalid_token"}
            route.fulfill(status=200 if state["auth"] else 401, content_type="application/json", body=json.dumps(data))
        elif path == f"{API}/auth/login":
            state["login_calls"] += 1
            state["auth"] = True
            route.fulfill(status=200, content_type="application/json", body='{"code":"ok"}',
                          headers={"set-cookie": "__Host-portal_token=renewed; Secure; HttpOnly; Path=/"})
        elif path == f"{API}/signin":
            state["sign_calls"] += 1
            if sign_code in {"ok", "already_signed"} or conflict_marks_signed:
                state["signed"] = True
            if sign_code == "ok" and 200 <= sign_status < 300:
                state["points"] = 105
                state["streak"] = 4
            if lost_response:
                route.abort("failed")
            else:
                route.fulfill(status=sign_status, content_type="application/json", body=json.dumps(
                    {"code": sign_code, "award": 5, "new_balance": 105,
                     "mode": req.post_data_json.get("mode")}))
        else:
            html = HTML.replace("STYLE", json.dumps(style)).replace("AUTO_SIGN", json.dumps(auto_sign))
            route.fulfill(status=200, content_type="text/html", body=html)

    def launch(**kwargs):
        kwargs.pop("headless", None)
        ctx = chromium.new_context(**kwargs)
        ctx.route("**/*", serve)
        return Context(ctx, state)

    def save(value):
        if save_fails:
            raise OSError("PRIVATE_PASSWORD must not leak")
        state["saved"] += 1
        state["saved_state"] = value

    def mark_pending():
        state["pending"] = True
        return True

    runner = BrowserRunner(options, launch, Event(), lambda: None, save,
                           lambda: state["pending"], mark_pending)
    result = runner.run(diagnose=diagnose)
    assert state["closed"] == 1
    assert "PRIVATE_PASSWORD" not in json.dumps(result.to_dict())
    return result, state


def test_real_browser_diagnosis_never_signs(chromium):
    result, state = exercise(chromium, diagnose=True, seed=True)
    assert result.ok and result.code == "diagnostic_ok"
    assert state["sign_calls"] == 0 and state["saved"] == 1
    assert "__Host-portal_token=header.payload.signature" in state["cookies_seen"]

@pytest.mark.parametrize("style", ["direct", "toggle"])
@pytest.mark.parametrize("lucky", [False, True])
def test_real_browser_modes(chromium, style, lucky):
    result, state = exercise(chromium, style=style, lucky=lucky)
    assert result.ok, result.to_dict()
    assert result.code == "signed" and state["sign_calls"] == 1
    assert result.mode == ("lucky" if lucky else "normal")
    assert result.balance == 105 and result.streak == 4


def test_real_browser_403_no_login_and_no_retries(chromium):
    result, state = exercise(chromium, gate_status=403, authenticated=False)
    assert not result.ok and result.code == "access_denied"
    assert state["gate_calls"] == 1 and state["login_calls"] == 0 and state["sign_calls"] == 0


def test_real_browser_password_login(chromium):
    result, state = exercise(chromium, authenticated=False, diagnose=True)
    assert result.ok, result.to_dict()
    assert state["login_calls"] == 1 and state["sign_calls"] == 0
    assert any(c["value"] == "renewed" for c in state["saved_state"]["cookies"])


def test_real_browser_redirect_does_not_send_credentials(chromium):
    result, state = exercise(chromium, redirect=True, authenticated=False)
    assert not result.ok and result.code == "site_redirect"
    assert state["login_calls"] == 0 and state["sign_calls"] == 0


def test_real_browser_already_signed_skips_post(chromium):
    result, state = exercise(chromium, already=True, pending=True)
    assert result.ok and result.already and state["sign_calls"] == 0


def test_real_browser_409_is_not_always_success(chromium):
    result, state = exercise(chromium, sign_status=409, sign_code="conflict_other")
    assert not result.ok and result.code == "signin_rejected"
    assert not result.uncertain and state["sign_calls"] == 1


def test_real_browser_explicit_already_signed(chromium):
    result, state = exercise(chromium, sign_status=409, sign_code="already_signed")
    assert result.ok and result.already and state["sign_calls"] == 1
    assert result.streak == 3


def test_real_browser_unknown_conflict_not_misclassified(chromium):
    result, state = exercise(chromium, sign_status=409, sign_code="conflict_other")
    assert not result.ok and result.code == "signin_rejected"


def test_real_browser_unknown_conflict_rechecked_by_account(chromium):
    result, state = exercise(
        chromium, sign_status=409, sign_code="conflict_other",
        conflict_marks_signed=True,
    )
    assert result.ok and result.already
    assert result.code == "already_signed"
    assert state["sign_calls"] == 1


def test_real_browser_uncertain_post_never_retries(chromium):
    result, state = exercise(chromium, lost_response=True)
    assert not result.ok and result.uncertain and state["sign_calls"] == 1
    assert state["pending"]


def test_real_browser_previous_uncertainty_blocks_next_post(chromium):
    result, state = exercise(chromium, pending=True)
    assert not result.ok and result.code == "previous_outcome_unknown"
    assert state["sign_calls"] == 0


def test_real_browser_mismatched_mode_is_blocked(chromium):
    result, state = exercise(chromium, style="wrong")
    assert not result.ok and result.code == "mode_mismatch"
    assert state["sign_calls"] == 0


def test_real_browser_diagnostic_guards_against_page_autosubmit(chromium):
    result, state = exercise(chromium, diagnose=True, auto_sign=True)
    assert not result.ok and result.code == "diagnostic_write_blocked"
    assert state["sign_calls"] == 0


def test_real_browser_cache_failure_preserves_confirmed_success(chromium):
    result, state = exercise(chromium, save_fails=True)
    assert result.ok and result.code == "signed"
    assert state["sign_calls"] == 1
    assert any(row["code"] == "state_save_failed" for row in result.diagnostics)

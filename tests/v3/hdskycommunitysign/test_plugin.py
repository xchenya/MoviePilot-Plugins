"""离线协议回归：真实 CookieJar / CronTrigger；宿主与 HTTP 传输使用替身。"""
import copy
import importlib.util
import io
import json
import logging
import sys
import time
import types
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.response import addinfourl

# 独立测试进程中的最小宿主合同；不冒充真实 MP 加载测试。
class PluginBase:
    def __init__(self):
        self.storage = {}
        self.config = {}
        self.messages = []

    def get_data(self, key):
        return copy.deepcopy(self.storage.get(key))

    def save_data(self, key, value):
        self.storage[key] = copy.deepcopy(value)

    def update_config(self, config):
        self.config = copy.deepcopy(config)

    def post_message(self, **message):
        self.messages.append(message)


for name in ("app", "app.sdk", "app.sdk.plugin", "app.sdk.config", "app.sdk.logging", "app.sdk.scheduler", "app.schemas", "app.schemas.types"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["app.sdk.plugin"]._PluginBase = PluginBase
sys.modules["app.sdk.config"].settings = types.SimpleNamespace(PROXY={}, TZ="Asia/Shanghai")
sys.modules["app.sdk.logging"].logger = logging.getLogger("hdsky-test")
sys.modules["app.sdk.scheduler"].update_plugin_job = lambda plugin_id: None
sys.modules["app.schemas.types"].MessageType = types.SimpleNamespace(Plugin="plugin")
source = Path(__file__).resolve().parents[3] / "plugins.v3/hdskycommunitysign/__init__.py"
spec = importlib.util.spec_from_file_location("hdskycommunitysign_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

GOOD = {
    "ok": True, "csrfToken": "test-csrf-private",
    "profile": {"account": {"hdskyUid": 123, "displayName": "Test account"}},
}


class Network:
    """用标准 CookieJar 真实解析 Set-Cookie，仅替换网络传输。"""
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        self.handlers = []

    def build(self, *handlers):
        self.handlers.append(handlers)
        jar = next(h.cookiejar for h in handlers if isinstance(h, module.HTTPCookieProcessor))
        network = self

        class Opener:
            def open(self, request, timeout):
                jar.add_cookie_header(request)
                network.requests.append(request)
                if not network.steps:
                    raise AssertionError("发生非预期额外请求")
                step = network.steps.pop(0)
                if isinstance(step, Exception):
                    raise step
                body, cookies = step
                headers = Message()
                headers["Content-Type"] = "application/json"
                for cookie in cookies:
                    headers.add_header("Set-Cookie", cookie)
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                response = addinfourl(io.BytesIO(raw), headers, request.full_url, 200)
                jar.extract_cookies(response, request)
                return response
        return Opener()


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = module.HdskyCommunitySign()
        self.plugin.init_plugin({"enabled": True, "uid": "123"})

    def run_action(self, action="none", **extra):
        self.plugin.init_plugin({**self.plugin.config, "action": action, **extra})

    def seed_active(self):
        jar = module.HdskyCommunitySign._parse_cookie("session=old-private")
        self.plugin._accept(jar, GOOD, "123")

    def test_startup_and_restart_do_not_request(self):
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.run_action()
            self.plugin.init_plugin(self.plugin.config)
        self.assertEqual([job["id"] for job in self.plugin.get_service()], ["HdskyCommunitySign.retry"])
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.assertIsNone(self.plugin.get_service()[0]["func"]())

    def test_send_login_capture_httponly_and_check_after_restart(self):
        net = Network(
            ({"ok": True, "displayName": "Test account"},
             ["challenge=pre-private; Path=/api/portal; Secure; HttpOnly; SameSite=Lax"]),
            (GOOD, ["session=login-private; Path=/; Secure; HttpOnly; Max-Age=3600"]),
            (GOOD, ["session=rotated-private; Path=/; Secure; HttpOnly; Max-Age=3600"]),
        )
        with patch.object(module, "build_opener", side_effect=net.build):
            self.run_action("send")
            pending = self.plugin.storage["auth"]["pending"]
            self.assertEqual(pending["uid"], "123")
            self.assertEqual(self.plugin.config["action"], "none")
            self.run_action("login", verify_code="012345")
            self.assertTrue(self.plugin.storage["auth"]["verified"])
            self.assertEqual(self.plugin.config["verify_code"], "")
            saved = self.plugin.storage["auth"]
            self.assertTrue(any("HttpOnly" in c["rest"] for c in saved["cookies"]))
            restarted = module.HdskyCommunitySign()
            restarted.storage = copy.deepcopy(self.plugin.storage)
            restarted.init_plugin(self.plugin.config)
            self.plugin = restarted
            self.run_action("check")
        self.assertEqual([r.full_url for r in net.requests], [
            module.ORIGIN + "/api/portal/auth/start",
            module.ORIGIN + "/api/portal/auth/verify",
            module.ORIGIN + "/api/portal/session",
        ])
        self.assertEqual(json.loads(net.requests[1].data)["code"], "012345")
        self.assertIn("challenge=pre-private", net.requests[1].get_header("Cookie"))
        self.assertIn("session=login-private", net.requests[2].get_header("Cookie"))
        self.assertEqual(self.plugin.storage["auth"]["csrf_token"], "test-csrf-private")
        self.assertIn("rotated-private", str(self.plugin.storage["auth"]["cookies"]))

    def test_manual_cookie_blank_uid_and_equals_in_value(self):
        net = Network((GOOD, []))
        with patch.object(module, "build_opener", side_effect=net.build):
            self.run_action(cookie_input="Cookie: session=abc==; second=two", uid="")
        self.assertTrue(self.plugin.storage["auth"]["verified"])
        self.assertEqual(self.plugin.storage["auth"]["account"]["uid"], "123")
        self.assertEqual(self.plugin.config["cookie_input"], "")
        self.assertIn("session=abc==", net.requests[0].get_header("Cookie"))

    def test_invalid_manual_cookie_preserves_previous_session(self):
        self.seed_active()
        old = copy.deepcopy(self.plugin.storage["auth"])
        error = HTTPError(module.ORIGIN, 401, "unauthorized", Message(), io.BytesIO())
        with patch.object(module, "build_opener", side_effect=Network(error).build):
            self.run_action(cookie_input="session=bad-private")
        self.assertEqual(self.plugin.storage["auth"], old)
        self.assertFalse(self.plugin.storage["status"]["success"])

    def test_failed_login_preserves_previous_session(self):
        self.seed_active()
        net = Network(({"ok": True}, []), ({"ok": False, "error": "012345 private"}, []))
        with patch.object(module, "build_opener", side_effect=net.build):
            self.run_action("send")
            self.run_action("login", verify_code="012345")
        self.assertTrue(self.plugin.storage["auth"]["verified"])
        self.assertIn("old-private", str(self.plugin.storage["auth"]["cookies"]))
        self.assertNotIn("012345", str(self.plugin.storage["status"]))

    def test_saved_cookie_401_marks_invalid(self):
        self.seed_active()
        error = HTTPError(module.ORIGIN, 401, "unauthorized", Message(), io.BytesIO())
        with patch.object(module, "build_opener", side_effect=Network(error).build):
            self.run_action("check")
        self.assertFalse(self.plugin.storage["auth"]["verified"])
        self.assertIn("失效", self.plugin.storage["status"]["message"])

    def test_uid_mismatch_does_not_replace_cookie(self):
        self.seed_active()
        old = copy.deepcopy(self.plugin.storage["auth"])
        with patch.object(module, "build_opener", side_effect=Network((GOOD, [])).build):
            self.run_action(cookie_input="session=candidate", uid="456")
        self.assertEqual(self.plugin.storage["auth"], old)
        self.assertIn("UID", self.plugin.storage["status"]["message"])

    def test_send_rate_limit_survives_reinit(self):
        net = Network(({"ok": True}, []))
        with patch.object(module, "build_opener", side_effect=net.build):
            self.run_action("send")
            self.run_action("send")
        self.assertEqual(len(net.requests), 1)
        self.assertIn("60", self.plugin.storage["status"]["message"])

    def test_uncertain_send_keeps_pending_and_never_retries(self):
        net = Network(URLError("private network detail"))
        with patch.object(module, "build_opener", side_effect=net.build):
            self.run_action("send")
            self.run_action("send")
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(self.plugin.storage["auth"]["pending"]["uid"], "123")
        self.assertNotIn("private network", str(self.plugin.storage))

    def test_disabled_or_conflicting_inputs_send_nothing(self):
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.run_action("send", enabled=False)
            self.run_action("send", enabled=True, cookie_input="a=b")
            self.run_action("none", verify_code="012345")
        self.assertEqual(self.plugin.config["verify_code"], "")
        self.assertEqual(self.plugin.config["cookie_input"], "")

    def test_malformed_cookie_inputs(self):
        for cookie in ("", "a=b\r\nOther: value", "session", "a=b; a=c",
                       "session=a; Path=/", "名字=123"):
            with self.subTest(cookie=cookie):
                with self.assertRaises(module.AuthError):
                    module.HdskyCommunitySign._parse_cookie(cookie)

    def test_login_requires_current_uid_challenge_and_six_digits(self):
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.run_action("login", verify_code="012345")
            self.assertIn("先", self.plugin.storage["status"]["message"])
            self.run_action("login", verify_code="123")
            self.assertIn("六位", self.plugin.storage["status"]["message"])

    def test_missing_profile_csrf_or_cookie_never_authenticates(self):
        for result, cookies in (
            ({"ok": True}, ["session=one; Path=/; Secure"]),
            ({**GOOD, "csrfToken": ""}, ["session=two; Path=/; Secure"]),
            (GOOD, []),
        ):
            with self.subTest(result=result, cookies=cookies):
                p = module.HdskyCommunitySign()
                p.init_plugin({"enabled": True, "uid": "123"})
                net = Network(({"ok": True}, []), (result, cookies))
                with patch.object(module, "build_opener", side_effect=net.build):
                    p.init_plugin({**p.config, "action": "send"})
                    p.init_plugin({**p.config, "action": "login", "verify_code": "012345"})
                self.assertFalse(p.storage["auth"].get("verified", False))

    def test_expired_cookies_not_sent(self):
        self.seed_active()
        for cookie in self.plugin.storage["auth"]["cookies"]:
            cookie["expires"] = int(time.time()) - 1
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.run_action("check")
        self.assertFalse(self.plugin.storage["auth"]["verified"])

    def test_redirect_non_json_rate_limit_and_network_failures(self):
        for step in (
            HTTPError(module.ORIGIN, 302, "redirect", Message(), io.BytesIO()),
            HTTPError(module.ORIGIN, 429, "limit", Message(), io.BytesIO()),
            HTTPError(module.ORIGIN, 500, "error", Message(), io.BytesIO()),
            URLError("secret-url-and-password"),
            module.HTTPException("private incomplete response"),
            (b"<html>challenge</html>", []),
            ({"ok": True, "profile": {}}, []),
        ):
            with self.subTest(step=type(step).__name__):
                self.plugin._runtime.pop("retry_after", None)
                self.plugin._save_runtime()
                net = Network(step)
                with patch.object(module, "build_opener", side_effect=net.build):
                    self.run_action(cookie_input="session=secret-cookie")
                self.assertFalse(self.plugin.storage["status"]["success"])
                self.assertEqual(len(net.requests), 1)
                self.assertNotIn("secret-cookie", str(self.plugin.storage["status"]))
                self.assertNotIn("secret-url", str(self.plugin.storage["status"]))
        handler = module.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_rendered_ui_and_config_never_contain_secrets(self):
        self.seed_active()
        rendered = json.dumps([self.plugin.get_form(), self.plugin.get_page(), self.plugin.config])
        self.assertNotIn("old-private", rendered)
        self.assertNotIn("test-csrf-private", rendered)

    def test_check_keeps_pending_login(self):
        self.seed_active()
        self.plugin._auth["pending"] = {"uid": "123", "at": time.time(), "cookies": []}
        self.plugin._save_auth()
        with patch.object(module, "build_opener", side_effect=Network((GOOD, [])).build):
            self.run_action("check")
        self.assertIn("pending", self.plugin.storage["auth"])

    def test_authenticated_ui_endpoints_and_no_scheduled_login(self):
        apis = self.plugin.get_api()
        self.assertEqual({api["path"] for api in apis}, {"/state", "/config", "/auth", "/sign"})
        self.assertTrue(all(api["auth"] == "bear" and api["response_model"] for api in apis))
        self.assertTrue(all(api["methods"] == ["POST"] for api in apis if api["path"] != "/state"))
        self.assertTrue(all(job["id"].endswith(".retry") for job in self.plugin.get_service()))
        self.assertEqual(self.plugin.get_command(), [])
        self.assertEqual(set(module.PATHS), {"send", "login", "check", "sign"})
        self.plugin.stop_service()
        self.assertFalse(self.plugin.get_state())


def daily(checked=False, uid=123, csrf="test-csrf-private"):
    result = copy.deepcopy(GOOD)
    result["csrfToken"] = csrf
    result["profile"]["account"]["hdskyUid"] = uid
    result["profile"]["dailyCheckin"] = {"checkedIn": checked, "amount": 20 if checked else 0}
    result["profile"]["wallet"] = {"balance": 100.5}
    return result


def http_error(status, error="", **headers):
    values = Message()
    for key, value in headers.items():
        values[key] = value
    return HTTPError(module.ORIGIN, status, "test", values,
                     io.BytesIO(json.dumps({"ok": False, "error": error}).encode()))


class SignTests(unittest.TestCase):
    def setUp(self):
        self.plugin = module.HdskyCommunitySign()
        self.plugin.init_plugin({"enabled": True, "notify": True})
        jar = self.plugin._parse_cookie("hdsky_portal_session=private-cookie")
        self.plugin._accept(jar, GOOD, "123")

    def invoke(self, *steps):
        net = Network(*steps)
        with patch.object(module, "build_opener", side_effect=net.build):
            row = self.plugin.sign_in()
        self.assertEqual(net.steps, [], "预期请求未发生")
        return row, net

    def restart(self):
        old = self.plugin
        self.plugin = module.HdskyCommunitySign()
        self.plugin.storage = copy.deepcopy(old.storage)
        self.plugin.init_plugin(old.config)

    def test_success_matches_client_protocol_and_rotates_cookie(self):
        reply = daily(True)
        reply.pop("csrfToken")  # 客户端签到响应不要求再次返回 Token。
        row, net = self.invoke(
            (daily(), []),
            (reply, ["hdsky_portal_session=rotated-private; Path=/; Secure; HttpOnly"]))
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["amount"], 20)
        self.assertEqual(row["balance"], 100.5)
        request = net.requests[-1]
        self.assertEqual(request.full_url, "https://hdsky.supertimi.de:8443/api/portal/daily-checkin")
        self.assertEqual(request.method, "POST")
        body = json.loads(request.data)
        self.assertEqual(set(body), {"requestKey"})
        self.assertRegex(body["requestKey"], r"^[a-f0-9]{32}$")
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers["x-csrf-token"], "test-csrf-private")
        self.assertEqual(headers["x-hdsky-client"], "app")
        self.assertEqual(headers["x-hdsky-platform"], "windows")
        self.assertEqual(headers["origin"], module.ORIGIN)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertIn("private-cookie", headers["cookie"])
        self.assertIn("rotated-private", str(self.plugin.storage["auth"]["cookies"]))
        self.assertIn("20", self.plugin.messages[-1]["text"])

    def test_already_signed_skips_post_and_deduplicates_notification(self):
        self.invoke((daily(), []), (daily(True), []))
        row, net = self.invoke((daily(True), []))
        self.assertEqual(row["status"], "already")
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(len(self.plugin.messages), 1)
        self.assertEqual(len(self.plugin.storage["checkins"]["history"]), 1)

    def test_client_signed_before_plugin(self):
        row, net = self.invoke((daily(True), []))
        self.assertEqual(row["status"], "already")
        self.assertEqual(len(net.requests), 1)

    def test_csrf_refresh_retries_once_with_same_request_key(self):
        row, net = self.invoke(
            (daily(), []),
            http_error(403, "页面安全校验已失效，请刷新后重试"),
            (daily(csrf="new-csrf-private"), []),
            (daily(True), []))
        self.assertEqual(row["status"], "success")
        self.assertEqual(net.requests[1].data, net.requests[3].data)
        self.assertEqual(net.requests[3].get_header("X-csrf-token"), "new-csrf-private")

    def test_second_csrf_rejection_stops(self):
        row, net = self.invoke(
            (daily(), []), http_error(403, "页面安全校验已失效，请刷新后重试"),
            (daily(), []), http_error(403, "页面安全校验已失效，请刷新后重试"))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(net.requests), 4)

    def test_csrf_refresh_finds_signed_and_skips_retry(self):
        row, net = self.invoke(
            (daily(), []), http_error(403, "页面安全校验已失效，请刷新后重试"),
            (daily(True), []))
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(len([r for r in net.requests if r.method == "POST"]), 1)

    def test_generic_403_is_never_retried(self):
        row, net = self.invoke((daily(), []), http_error(403, "denied private-cookie"))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(net.requests), 2)
        self.assertNotIn("private-cookie", str(row))

    def test_post_timeout_readback_confirms_success(self):
        row, net = self.invoke((daily(), []), TimeoutError("private"), (daily(True), []))
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(len([r for r in net.requests if r.method == "POST"]), 1)

    def test_uncertain_post_never_replays_across_restart(self):
        row, _ = self.invoke((daily(), []), URLError("private"), (daily(), []))
        self.assertEqual(row["status"], "uncertain")
        self.restart()
        row, net = self.invoke((daily(), []))
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(len(net.requests), 1)
        row, _ = self.invoke((daily(True), []))
        self.assertEqual(row["status"], "already")

    def test_crash_after_intent_only_checks_status(self):
        key = "123:" + self.plugin._day()
        self.plugin._runtime["attempts"] = {key: {"state": "sent", "request_key": "a" * 32}}
        self.plugin._save_runtime()
        self.restart()
        row, net = self.invoke((daily(), []))
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(len(net.requests), 1)

    def test_intent_saved_before_post(self):
        network = Network((daily(), []), (daily(True), []))
        original = network.build
        def build(*handlers):
            if len(network.requests) == 1:
                attempts = self.plugin.storage["checkins"]["attempts"]
                self.assertEqual(next(iter(attempts.values()))["state"], "sent")
            return original(*handlers)
        with patch.object(module, "build_opener", side_effect=build):
            self.plugin.sign_in()

    def test_bad_sign_response_uses_readback_without_reposting(self):
        for response in (b"<html>error</html>", {"ok": False},
                         {"ok": True}, daily(False), daily(True, uid=456)):
            with self.subTest(response=response):
                self.setUp()
                row, net = self.invoke((daily(), []), (response, []), (daily(), []))
                self.assertEqual(row["status"], "uncertain")
                self.assertEqual(len(net.requests), 3)

    def test_initial_query_failure_never_posts(self):
        for step in (http_error(401), http_error(500), URLError("private"),
                     (GOOD, []), (daily(uid=456), [])):
            with self.subTest(step=step):
                self.setUp()
                self.plugin._config["uid"] = "123"
                row, net = self.invoke(step)
                self.assertEqual(row["status"], "failed")
                self.assertEqual(len(net.requests), 1)

    def test_cookie_401_invalidates_auth(self):
        self.invoke(http_error(401))
        self.assertFalse(self.plugin.storage["auth"]["verified"])

    def test_rate_limit_persists_cooldown(self):
        row, net = self.invoke((daily(), []), http_error(429, **{"Retry-After": "120"}))
        self.assertEqual(row["status"], "failed")
        self.restart()
        row, net = self.invoke()
        self.assertEqual(len(net.requests), 0)
        self.assertIn("冷却", row["message"])
        self.assertGreater(self.plugin.storage["checkins"]["retry_after"], time.time() + 100)

    def test_disabled_stopped_and_old_generation_do_nothing(self):
        self.plugin.init_plugin({**self.plugin.config, "auto_sign": True})
        stale = self.plugin.get_service()[0]["func"]
        self.plugin.init_plugin(self.plugin.config)
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            self.assertIsNone(stale())
            self.plugin.stop_service()
            self.assertIsNone(self.plugin.sign_in())
            self.assertEqual(self.plugin.get_service(), [])
            self.plugin.init_plugin({**self.plugin.config, "enabled": False})
            self.assertIsNone(self.plugin.sign_in())

    def test_stop_during_session_read_prevents_post(self):
        original = self.plugin._refresh_sign_session
        def refresh(*args, **kwargs):
            result = original(*args, **kwargs)
            self.plugin.stop_service()
            return result
        with patch.object(self.plugin, "_refresh_sign_session", side_effect=refresh):
            row, net = self.invoke((daily(), []))
        self.assertIsNone(row)
        self.assertEqual(len(net.requests), 1)

    def test_service_uses_real_cron_timezone(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.plugin.init_plugin({**self.plugin.config, "auto_sign": True})
        service = self.plugin.get_service()[0]
        next_at = service["trigger"].get_next_fire_time(
            None, datetime(2026, 10, 27, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(next_at.hour, 8)
        self.assertEqual(str(next_at.tzinfo), "Asia/Shanghai")
        self.assertEqual(service["kwargs"]["max_instances"], 1)

    def test_invalid_cron_never_registers_service(self):
        self.plugin.init_plugin({**self.plugin.config, "auto_sign": True, "cron": "invalid"})
        self.assertEqual(self.plugin.get_service(), [])
        self.assertFalse(self.plugin.storage["status"]["success"])

    def test_one_shot_clears_before_request_and_does_not_replay(self):
        net = Network((daily(), []), (daily(True), []))
        with patch.object(module, "build_opener", side_effect=net.build):
            self.plugin.init_plugin({**self.plugin.config, "action": "sign"})
            self.assertEqual(self.plugin.config["action"], "none")
            self.plugin.init_plugin(self.plugin.config)
        self.assertEqual(len(net.requests), 2)

    def test_notification_disabled_and_rendered_data_redacted(self):
        self.plugin._config["notify"] = False
        self.invoke((daily(), []), (daily(True), []))
        self.assertEqual(self.plugin.messages, [])
        rendered = str([self.plugin.get_form(), self.plugin.get_page(), self.plugin.config])
        self.assertNotIn("private-cookie", rendered)
        self.assertNotIn("test-csrf-private", rendered)

    def test_history_bounded_to_60_and_optional_amounts(self):
        profile = daily(True)
        profile["profile"]["wallet"] = {"balance": float("nan")}
        profile["profile"]["dailyCheckin"]["amount"] = True
        self.plugin._runtime["history"] = [{"status": "failed"} for _ in range(60)]
        row, _ = self.invoke((profile, []))
        self.assertIsNone(row["amount"])
        self.assertIsNone(row["balance"])
        self.assertEqual(len(self.plugin.storage["checkins"]["history"]), 60)

    def test_next_day_allows_new_attempt(self):
        self.invoke((daily(), []), (daily(True), []))
        with patch.object(self.plugin, "_day", return_value="2099-01-02"):
            row, net = self.invoke((daily(), []), (daily(True), []))
        self.assertEqual(row["status"], "success")
        self.assertEqual(len(net.requests), 2)


class InteractiveApiTests(unittest.TestCase):
    setUp = LoginTests.setUp
    seed_active = LoginTests.seed_active

    def test_direct_send_login_without_enabling_or_resaving_form(self):
        self.plugin.init_plugin({"enabled": False, "auto_sign": True, "notify": False})
        net = Network(
            ({"ok": True}, ["challenge=pre-private; Path=/; Secure"]),
            (GOOD, ["session=login-private; Path=/; Secure; HttpOnly"]),
        )
        with patch.object(module, "build_opener", side_effect=net.build):
            sent = self.plugin.api_auth(module.AuthRequest(action="send", uid="123"))
            logged = self.plugin.api_auth(module.AuthRequest(action="login", uid="123", code="012345"))
            rejected_sign = self.plugin.api_sign()
        self.assertTrue(sent.success)
        self.assertTrue(logged.success)
        self.assertFalse(rejected_sign.success)
        self.assertEqual(len(net.requests), 2)
        self.assertEqual(self.plugin.config["uid"], "123")
        self.assertFalse(self.plugin.config["enabled"])
        self.assertTrue(self.plugin.config["auto_sign"])
        self.assertFalse(self.plugin.config["notify"])
        self.assertNotIn("012345", str(self.plugin.config))
        self.assertEqual(logged.state.auth.uid, "123")
        self.assertTrue(logged.state.auth.verified)

    def test_direct_send_cooldown_and_pending_survive_restart(self):
        net = Network(({"ok": True}, ["challenge=pre-private; Path=/; Secure"]))
        with patch.object(module, "build_opener", side_effect=net.build):
            first = self.plugin.api_auth(module.AuthRequest(action="send"))
            replacement = module.HdskyCommunitySign()
            replacement.storage = copy.deepcopy(self.plugin.storage)
            replacement.init_plugin(self.plugin.config)
            second = replacement.api_auth(module.AuthRequest(action="send"))
        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertGreater(second.state.auth.send_after, time.time())
        self.assertEqual(second.state.auth.pending_uid, "123")
        self.assertEqual(len(net.requests), 1)

    def test_public_state_is_local_and_excludes_all_secrets(self):
        self.seed_active()
        self.plugin._auth["pending"] = {"uid": "123", "cookies": [{"value": "private-challenge"}]}
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            state = self.plugin.api_state()
        text = state.model_dump_json() + json.dumps(self.plugin.get_form())
        for secret in ("old-private", "test-csrf-private", "private-challenge", "csrf_token", "cookies"):
            self.assertNotIn(secret, text)
        self.assertTrue(state.auth.cookie_configured)
        self.assertEqual(state.auth.pending_uid, "123")
        self.assertEqual(self.plugin.get_render_mode(), ("vue", f"dist/assets-v{self.plugin.plugin_version}"))

    def test_bad_candidate_cookie_via_api_keeps_active_session(self):
        self.seed_active()
        old = copy.deepcopy(self.plugin.storage["auth"])
        with patch.object(module, "build_opener", side_effect=Network(http_error(401)).build):
            result = self.plugin.api_auth(module.AuthRequest(action="cookie", cookie="session=bad-private"))
        self.assertFalse(result.success)
        self.assertEqual(self.plugin.storage["auth"], old)
        self.assertNotIn("bad-private", result.model_dump_json())

    def test_config_save_updates_instance_schedule_without_network(self):
        self.plugin.init_plugin({"enabled": True, "auto_sign": True, "uid": "123"})
        stale = self.plugin.get_service()[0]["func"]
        with patch.object(module, "build_opener", side_effect=AssertionError("network")), \
                patch.object(module, "update_plugin_job") as update:
            result = self.plugin.api_save_config(module.PublicConfig(cron="0 9 * * *", notify=False))
            self.assertIsNone(stale())
        update.assert_called_once_with(self.plugin.__class__.__name__)
        self.assertTrue(result.success)
        self.assertTrue(result.state.config.auto_sign)
        self.assertEqual(result.state.config.uid, "123")
        self.assertEqual(self.plugin.config["cron"], "0 9 * * *")
        self.assertFalse(self.plugin.config["notify"])

    def test_invalid_config_or_failed_save_preserves_active_schedule(self):
        old = copy.deepcopy(self.plugin.config)
        for payload in (module.PublicConfig(cron="bad"), module.PublicConfig(uid="abc")):
            result = self.plugin.api_save_config(payload)
            self.assertFalse(result.success)
            self.assertEqual(self.plugin.config, old)
        with patch.object(self.plugin, "update_config", return_value=False):
            failed = self.plugin.api_save_config(module.PublicConfig(notify=False))
            auth_failed = self.plugin.api_auth(module.AuthRequest(action="send"))
        self.assertFalse(failed.success)
        self.assertFalse(auth_failed.success)
        self.assertEqual(self.plugin._config, old)

    def test_bad_api_inputs_never_send_or_persist_secrets(self):
        with patch.object(module, "build_opener", side_effect=AssertionError("network")):
            for payload in (
                module.AuthRequest(action="send", uid="bad"),
                module.AuthRequest(action="send", uid=""),
                module.AuthRequest(action="sign"),
                module.AuthRequest(action="send", code="012345"),
                module.AuthRequest(action="send", cookie="session=private-cookie"),
                module.AuthRequest(action="send", user_agent="bad\nheader"),
            ):
                self.assertFalse(self.plugin.api_auth(payload).success)
        self.assertNotIn("012345", str(self.plugin.storage))
        self.assertNotIn("private-cookie", str(self.plugin.storage))

    def test_api_rate_limit_exposes_cooldown_without_retry(self):
        with patch.object(module, "build_opener", side_effect=Network(http_error(429)).build):
            result = self.plugin.api_auth(module.AuthRequest(action="send"))
        self.assertFalse(result.success)
        self.assertGreater(result.state.auth.retry_after, time.time() + 250)


class DailyStatisticsTests(unittest.TestCase):
    setUp = SignTests.setUp
    invoke = SignTests.invoke
    restart = SignTests.restart

    def test_repeated_checks_count_reward_once_and_preserve_known_values(self):
        self.invoke((daily(), []), (daily(True), []))
        missing_amount = daily(True)
        missing_amount["profile"]["dailyCheckin"].pop("amount")
        missing_amount["profile"].pop("wallet")
        for _ in range(3):
            self.invoke((missing_amount, []))
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 1)
        self.assertEqual(stats.reward_total, 20)
        self.assertEqual(stats.today.balance, 100.5)
        self.assertEqual(len(self.plugin.storage["checkins"]["history"]), 1)
        self.assertEqual(len(stats.days), 30)

    def test_success_time_survives_refresh_repeated_sign_and_restart(self):
        with patch.object(module.time, "time", return_value=1000):
            self.invoke((daily(), []), (daily(True), []))
        reply = daily(True)
        reply["profile"]["wallet"]["balance"] = 200
        with patch.object(module.time, "time", return_value=2000), \
                patch.object(module, "build_opener", side_effect=Network((reply, [])).build):
            refreshed = self.plugin.api_auth(module.AuthRequest(action="check"))
        self.assertEqual(refreshed.state.statistics.today.time, 1000)
        self.assertEqual(refreshed.state.auth.balance_at, 2000)
        self.assertEqual(refreshed.state.statistics.today.balance, 200)
        with patch.object(module.time, "time", return_value=3000):
            self.invoke((reply, []))
        self.restart()
        self.restart()
        state = self.plugin.api_state()
        self.assertEqual(state.statistics.today.time, 1000)
        self.assertEqual(state.statistics.today.balance, 200)
        self.assertEqual(state.statistics.completed_days, 1)
        self.assertEqual(state.statistics.reward_total, 20)
        self.assertEqual(state.history[0].time, 1000)
        self.assertEqual(self.plugin._runtime["last"]["time"], 3000)

    def test_readonly_confirmation_time_replaces_unsigned_query_then_stays_fixed(self):
        for at, checked in ((1000, False), (2000, True), (3000, True)):
            with patch.object(module.time, "time", return_value=at), \
                    patch.object(module, "build_opener", side_effect=Network((daily(checked), [])).build):
                state = self.plugin.api_auth(module.AuthRequest(action="check")).state
            self.assertEqual(state.statistics.today.time, 1000 if not checked else 2000)
        self.restart()
        self.assertEqual(self.plugin.api_state().statistics.today.time, 2000)

    def test_failed_and_uncertain_times_do_not_replace_success_time(self):
        for at, status in ((1000, "failed"), (2000, "uncertain"), (3000, "success"),
                           (4000, "already"), (5000, "failed")):
            with patch.object(module.time, "time", return_value=at):
                self.plugin._finish_sign(status, "fixture", "123")
        self.restart()
        self.assertEqual(self.plugin.api_state().statistics.today.time, 3000)

    def test_upgrade_recovers_success_time_without_replaying_old_balance(self):
        today = self.plugin._day()
        success = {"day": today, "uid": "123", "status": "success", "time": 1000,
                   "message": "签到成功。", "amount": 20, "balance": 100}
        latest = {**success, "status": "already", "time": 3000, "balance": 900}
        other = {**success, "uid": "456", "time": 500}
        self.plugin._runtime = {
            "daily_stats": {"123:" + today: latest, "456:" + today: other},
            "history": [{**success, "status": "failed", "time": 100}, success],
            "last": {**success, "status": "already", "time": 2000, "balance": 200},
        }
        self.plugin._save_runtime()
        self.restart()
        saved = copy.deepcopy(self.plugin.storage["checkins"])
        self.restart()
        self.assertEqual(self.plugin.storage["checkins"], saved)
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.today.time, 1000)
        self.assertEqual(stats.today.balance, 900)
        self.assertEqual(stats.reward_total, 20)
        self.assertEqual(saved["daily_stats"]["456:" + today]["time"], 500)

    def test_upgrade_backfills_history_and_last_idempotently_per_account(self):
        from datetime import date, timedelta
        today = self.plugin._day()
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        self.plugin._runtime = {"history": [
            {"day": today, "uid": "123", "status": "already", "amount": None, "time": 3},
            {"day": today, "uid": "123", "status": "success", "amount": 20, "time": 2},
            {"day": yesterday, "uid": "123", "status": "confirmed", "time": 1},
            {"day": today, "uid": "456", "status": "success", "amount": 999, "time": 1},
        ]}
        # v1.0.0 的真实历史行始终包含 message/balance。
        for row in self.plugin._runtime["history"]:
            row.update(message="fixture", balance=None)
        self.plugin._runtime["last"] = {**self.plugin._runtime["history"][0], "time": 4, "balance": 120}
        self.plugin._save_runtime()
        self.restart()
        self.restart()
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 2)
        self.assertEqual(stats.reward_total, 20)
        self.assertEqual(stats.unknown_reward_days, 1)
        self.assertEqual(stats.today.balance, 120)
        self.assertEqual(len(self.plugin.storage["checkins"]["daily_stats"]), 3)
        self.plugin._auth["account"]["uid"] = "456"
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 1)
        self.assertEqual(stats.reward_total, 999)

    def test_confirmed_day_survives_later_errors_history_trim_and_restart(self):
        self.invoke((daily(), []), (daily(True), []))
        for _ in range(65):
            self.plugin._finish_sign("failed", "读取失败", "123")
        self.assertEqual(len(self.plugin.storage["checkins"]["history"]), 60)
        self.restart()
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 1)
        self.assertEqual(stats.reward_total, 20)
        self.assertEqual(stats.today.status, "success")

    def test_uncertain_and_failed_days_do_not_count_as_completed_or_reward(self):
        self.invoke((daily(), []), TimeoutError(), (daily(), []))
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 0)
        self.assertEqual(stats.reward_total, 0)
        self.assertEqual(stats.today.status, "uncertain")
        self.assertEqual(stats.days[1].status, "unrecorded")
        self.invoke((daily(True), []))
        self.assertEqual(self.plugin.api_state().statistics.completed_days, 1)

    def test_query_failure_records_account_without_releasing_old_submission_intent(self):
        key = "123:" + self.plugin._day()
        self.plugin._runtime["attempts"] = {key: {"state": "sent", "request_key": "a" * 32}}
        self.plugin._save_runtime()
        self.invoke(http_error(500))
        state = self.plugin.api_state()
        self.assertEqual(state.statistics.today.status, "failed")
        self.assertEqual(state.statistics.completed_days, 0)
        self.assertEqual(self.plugin._runtime["attempts"][key]["state"], "sent")
        _, net = self.invoke((daily(), []))
        self.assertEqual(len(net.requests), 1)

    def test_thirty_day_window_and_ninety_day_retention(self):
        from datetime import date, timedelta
        today = date.fromisoformat(self.plugin._day())
        for offset in (0, 29, 30, 89, 90):
            day = (today - timedelta(days=offset)).isoformat()
            self.plugin._merge_daily({"uid": "123", "day": day, "status": "success",
                                      "amount": 20, "time": 1, "message": "fixture"})
        self.plugin._prune_daily()
        stats = self.plugin.api_state().statistics
        self.assertEqual(stats.completed_days, 2)
        self.assertEqual(stats.reward_total, 40)
        self.assertEqual(len(self.plugin._runtime["daily_stats"]), 4)
        self.assertEqual(stats.days[0].day, today.isoformat())
        self.assertEqual(stats.days[-1].day, (today - timedelta(days=29)).isoformat())

    def test_sign_api_uses_existing_checkin_protection(self):
        net = Network((daily(), []), (daily(True), []), (daily(True), []))
        with patch.object(module, "build_opener", side_effect=net.build):
            first = self.plugin.api_sign()
            second = self.plugin.api_sign()
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(second.state.statistics.completed_days, 1)
        self.assertEqual(second.state.statistics.reward_total, 20)
        self.assertEqual(len([r for r in net.requests if r.method == "POST"]), 1)


class WalletAndConnectionTests(unittest.TestCase):
    setUp = SignTests.setUp

    def check(self, *steps):
        net = Network(*steps)
        with patch.object(module, "build_opener", side_effect=net.build):
            result = self.plugin.api_auth(module.AuthRequest(action="check"))
        self.assertEqual(net.steps, [])
        self.assertTrue(all(r.method == "GET" for r in net.requests))
        return result, net

    def test_balance_without_signing_even_when_plugin_disabled(self):
        self.plugin.init_plugin({**self.plugin.config, "enabled": False})
        result, net = self.check((daily(False), []))
        self.assertTrue(result.success)
        self.assertEqual(result.state.auth.balance, 100.5)
        self.assertEqual(result.state.auth.connection_status, "ok")
        self.assertEqual(result.state.statistics.completed_days, 0)
        self.assertEqual(result.state.statistics.reward_total, 0)
        self.assertEqual(result.state.statistics.today.status, "not_signed")
        self.assertIsNone(result.state.statistics.today.amount)
        self.assertEqual(len(net.requests), 1)
        self.assertNotIn("attempts", self.plugin._runtime)
        self.assertEqual(self.plugin.messages, [])
        self.assertNotIn("private-cookie", result.model_dump_json())

    def test_zero_balance_and_readonly_signed_statistics(self):
        reply = daily(True)
        reply["profile"]["wallet"]["balance"] = 0
        result, _ = self.check((reply, []))
        self.assertEqual(result.state.auth.balance, 0)
        self.assertEqual(result.state.statistics.completed_days, 1)
        self.assertEqual(result.state.statistics.reward_total, 20)
        self.assertEqual(self.plugin.messages, [])

    def test_missing_wallet_clears_snapshot_without_breaking_cookie_check(self):
        self.check((daily(), []))
        result, _ = self.check((GOOD, []))
        self.assertTrue(result.success)
        self.assertIsNone(result.state.auth.balance)

    def test_connection_failure_differs_from_invalid_cookie(self):
        self.check((daily(), []))
        result, _ = self.check(URLError("private-cookie"))
        self.assertFalse(result.success)
        self.assertEqual(result.state.auth.connection_status, "error")
        self.assertTrue(result.state.auth.verified)
        self.assertEqual(result.state.auth.balance, 100.5)  # 带上次获取时间的缓存值
        self.assertNotIn("private-cookie", result.model_dump_json())
        result, _ = self.check(http_error(401))
        self.assertFalse(result.state.auth.verified)
        self.assertEqual(result.state.auth.connection_status, "invalid")

    def test_new_account_does_not_inherit_previous_balance(self):
        self.check((daily(), []))
        jar = self.plugin._parse_cookie("session=other-private")
        other = copy.deepcopy(GOOD)
        other["profile"]["account"]["hdskyUid"] = 456
        self.plugin._accept(jar, other)
        self.assertEqual(self.plugin.api_state().auth.uid, "456")
        self.assertIsNone(self.plugin.api_state().auth.balance)


class RetryTests(unittest.TestCase):
    setUp = SignTests.setUp
    invoke = SignTests.invoke
    restart = SignTests.restart

    def due(self, *steps):
        self.plugin._runtime["sign_retry"]["next_at"] = time.time() - 1
        net = Network(*steps)
        with patch.object(module, "build_opener", side_effect=net.build):
            result = self.plugin.retry_sign_in()
        self.assertEqual(net.steps, [])
        return result, net

    def test_preflight_failure_retries_and_succeeds(self):
        self.plugin.init_plugin({**self.plugin.config, "retry_count": 2, "retry_interval": 120})
        before = time.time()
        self.invoke(URLError("private"))
        plan = self.plugin.api_state().retry
        self.assertTrue(plan.pending)
        self.assertEqual(plan.used, 0)
        self.assertGreaterEqual(plan.next_at, before + 120)
        with patch.object(module, "build_opener", side_effect=AssertionError("too early")):
            self.assertIsNone(self.plugin.retry_sign_in())
        row, net = self.due((daily(), []), (daily(True), []))
        self.assertEqual(row["status"], "success")
        self.assertEqual(len([r for r in net.requests if r.method == "POST"]), 1)
        self.assertFalse(self.plugin.api_state().retry.pending)
        self.assertNotIn("sign_retry", self.plugin.storage["checkins"])

    def test_retry_limit_and_restart_preserve_consumed_budget(self):
        self.plugin.init_plugin({**self.plugin.config, "retry_count": 2})
        self.invoke(http_error(500))
        self.due(http_error(500))
        self.restart()
        self.assertEqual(self.plugin.api_state().retry.used, 1)
        self.due(http_error(500))
        self.assertFalse(self.plugin.api_state().retry.pending)
        self.assertEqual(self.plugin.api_state().retry.used, 2)
        self.restart()
        self.assertEqual(self.plugin.api_state().retry.used, 2)
        with patch.object(module, "build_opener", side_effect=AssertionError("exhausted")):
            self.assertIsNone(self.plugin.retry_sign_in())

    def test_uncertain_post_only_rechecks_even_after_restart(self):
        self.invoke((daily(), []), TimeoutError(), (daily(), []))
        self.restart()
        row, net = self.due((daily(), []))
        self.assertEqual(row["status"], "uncertain")
        self.assertTrue(all(r.method == "GET" for r in net.requests))
        row, net = self.due((daily(True), []))
        self.assertEqual(row["status"], "already")
        self.assertTrue(all(r.method == "GET" for r in net.requests))
        self.assertFalse(self.plugin.api_state().retry.pending)

    def test_rate_limit_delays_retry_beyond_configured_interval(self):
        self.invoke((daily(), []), http_error(429, **{"Retry-After": "900"}))
        self.assertGreaterEqual(self.plugin.api_state().retry.next_at, self.plugin._runtime["retry_after"])
        self.plugin._runtime["sign_retry"]["next_at"] = time.time() - 1
        with patch.object(module, "build_opener", side_effect=AssertionError("cooldown")):
            self.assertIsNone(self.plugin.retry_sign_in())
        self.assertEqual(self.plugin.api_state().retry.used, 0)

    def test_cookie_invalid_during_uncertain_readback_stops_retries(self):
        row, _ = self.invoke((daily(), []), TimeoutError(), http_error(401))
        self.assertEqual(row["status"], "uncertain")
        self.assertFalse(self.plugin.api_state().auth.verified)
        self.assertFalse(self.plugin.api_state().retry.pending)

    def test_duplicate_retry_callback_cannot_run_before_next_interval(self):
        self.invoke(http_error(500))
        self.due(http_error(500))
        with patch.object(module, "build_opener", side_effect=AssertionError("duplicate callback")):
            self.assertIsNone(self.plugin.retry_sign_in())
        self.assertEqual(self.plugin.api_state().retry.used, 1)

    def test_diagnostics_invalid_cookie_cancels_pending_retry(self):
        self.invoke(http_error(500))
        with patch.object(module, "build_opener", side_effect=Network(http_error(401)).build):
            result = self.plugin.api_auth(module.AuthRequest(action="check"))
        self.assertFalse(result.state.retry.pending)
        self.assertNotIn("sign_retry", self.plugin.storage["checkins"])

    def test_invalid_cookie_and_forbidden_do_not_retry(self):
        for failure in (http_error(401), http_error(403)):
            self.setUp()
            self.invoke(failure)
            self.assertFalse(self.plugin.api_state().retry.pending)

    def test_disabled_retries_register_no_worker_and_make_no_plan(self):
        self.plugin.init_plugin({**self.plugin.config, "retry_count": 0})
        self.assertEqual(self.plugin.get_service(), [])
        self.invoke(http_error(500))
        self.assertFalse(self.plugin.api_state().retry.pending)

    def test_stopped_stale_generation_account_and_date_do_not_retry(self):
        self.invoke(http_error(500))
        stale = self.plugin.get_service()[0]["func"]
        self.plugin.init_plugin(self.plugin.config)
        with patch.object(module, "build_opener", side_effect=AssertionError("stale")):
            self.assertIsNone(stale())
            self.plugin._runtime["sign_retry"]["next_at"] = time.time() - 1
            with patch.object(self.plugin, "_day", return_value="2099-01-01"):
                self.assertIsNone(self.plugin.retry_sign_in())
            self.plugin._auth["account"]["uid"] = "456"
            self.assertIsNone(self.plugin.retry_sign_in())
            self.plugin._auth["account"]["uid"] = "123"
            self.plugin.stop_service()
            self.assertIsNone(self.plugin.retry_sign_in())

    def test_account_change_or_midnight_during_retry_query_never_posts(self):
        for change in ("account", "midnight"):
            self.setUp()
            self.invoke(http_error(500))
            original = self.plugin._refresh_sign_session
            def refresh(*args, **kwargs):
                uid, state = original(*args, **kwargs)
                if change == "account": return "456", state
                self.plugin._day = lambda: "2099-01-01"
                return uid, state
            with patch.object(self.plugin, "_refresh_sign_session", side_effect=refresh):
                row, net = self.due((daily(), []))
            self.assertIsNone(row)
            self.assertTrue(all(r.method == "GET" for r in net.requests))

    def test_disable_and_reenable_does_not_restore_old_retry_plan(self):
        self.invoke(http_error(500))
        self.plugin.init_plugin({**self.plugin.config, "enabled": False})
        self.assertNotIn("sign_retry", self.plugin.storage["checkins"])
        self.plugin.init_plugin({**self.plugin.config, "enabled": True})
        self.assertFalse(self.plugin.api_state().retry.pending)

    def test_switch_account_and_back_does_not_restore_old_retry_plan(self):
        self.invoke(http_error(500))
        jar = self.plugin._parse_cookie("session=other-private")
        other = copy.deepcopy(GOOD)
        other["profile"]["account"]["hdskyUid"] = 456
        self.plugin._accept(jar, other)
        self.plugin._accept(jar, GOOD)
        self.assertFalse(self.plugin.api_state().retry.pending)

    def test_midnight_during_csrf_refresh_stops_second_post(self):
        original = self.plugin._refresh_sign_session
        queries = []
        def refresh(*args, **kwargs):
            result = original(*args, **kwargs)
            queries.append(True)
            if len(queries) == 2: self.plugin._day = lambda: "2099-01-01"
            return result
        with patch.object(self.plugin, "_refresh_sign_session", side_effect=refresh):
            row, net = self.invoke((daily(), []), http_error(403, "页面安全校验已失效，请刷新后重试"),
                                   (daily(), []))
        self.assertIsNone(row)
        self.assertEqual(len([r for r in net.requests if r.method == "POST"]), 1)

    def test_updated_interval_reschedules_pending_retry_without_resetting_count(self):
        self.invoke(http_error(500))
        self.due(http_error(500))
        before = time.time()
        result = self.plugin.api_save_config(module.PublicConfig(retry_interval=900))
        self.assertTrue(result.success)
        self.assertEqual(result.state.retry.used, 1)
        self.assertGreaterEqual(result.state.retry.next_at, before + 900)

    def test_bad_saved_retry_config_keeps_public_state_readable_and_schedules_nothing(self):
        self.plugin.init_plugin({**self.plugin.config, "retry_count": "bad"})
        self.assertEqual(self.plugin.get_service(), [])
        self.assertEqual(self.plugin.api_state().config.retry_count, 3)

    def test_retry_config_limits_and_save_cancels_pending_plan(self):
        for fields in ({"retry_count": -1}, {"retry_count": 11},
                       {"retry_interval": 59}, {"retry_interval": 86401}):
            with self.assertRaises(ValueError): module.PublicConfig(**fields)
        self.invoke(http_error(500))
        self.assertTrue(self.plugin.api_state().retry.pending)
        result = self.plugin.api_save_config(module.PublicConfig(retry_count=0))
        self.assertTrue(result.success)
        self.assertFalse(result.state.retry.pending)
        self.assertEqual(self.plugin.get_service(), [])


if __name__ == "__main__":
    unittest.main()

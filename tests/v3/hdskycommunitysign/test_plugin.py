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


for name in ("app", "app.sdk", "app.sdk.plugin", "app.sdk.config", "app.sdk.logging", "app.schemas", "app.schemas.types"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["app.sdk.plugin"]._PluginBase = PluginBase
sys.modules["app.sdk.config"].settings = types.SimpleNamespace(PROXY={}, TZ="Asia/Shanghai")
sys.modules["app.sdk.logging"].logger = logging.getLogger("hdsky-test")
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
        self.assertEqual(self.plugin.get_service(), [])

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

    def test_no_extra_endpoints_or_scheduled_actions(self):
        self.assertEqual(self.plugin.get_api(), [])
        self.assertEqual(self.plugin.get_service(), [])
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


if __name__ == "__main__":
    unittest.main()

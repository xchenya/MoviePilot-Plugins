"""Offline protocol and state-machine tests. Never send requests to the real site."""
import ast
import copy
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3/siqirestaurant"


def snapshot():
    # Synthetic fixture based on the fields read by the site's frontend.
    return {"success": True, "user": {"magic": 10000},
            "state": {"session_date": "2026-10-19", "session_status": "open", "popularity": 19000,
                      "unlocked": {"stations": 2, "seats": 2, "dishes": ["egg"]},
                      "customers_total": 2, "customers_served": 0,
                      "customer_plan": [{"id": 1, "seat": 1, "dish_key": "egg", "status": "waiting",
                                         "deadline": time.time() + 100, "patience": 100}]},
            "config": {"settings": {"automation_mode": "seat-bound"},
                       "dishes": [{"key": "egg", "name": "炒鸡蛋", "tool": "wok", "cook_time": 4,
                                   "ingredients": [{"key": "egg", "quantity": 2}]}],
                       "tools": [{"key": "wok", "name": "炒锅"}],
                       "ingredients": [{"key": "egg", "name": "鸡蛋", "price": 12}]},
            "inventory": {"ingredients": {"egg": 2}, "tools": {"wok": 1}},
            "staff": {"unlocked": True, "inventory": {"chef": 1, "server": 1},
                      "available": {"chef": 0, "server": 0}, "next_prices": {"chef": 10000},
                      "assignments_map": {"1": {"chef": True, "server": True}}},
            "logs": [], "visits": {"count": 0, "limit": 3}}


@pytest.fixture
def module(monkeypatch):
    class Base:
        def __init__(self):
            self.storage = {}
        def get_data(self, key):
            return copy.deepcopy(self.storage.get(key))
        def save_data(self, key, value):
            self.storage[key] = copy.deepcopy(value)
        def update_config(self, value):
            self.config = value
    tree = ast.parse((PLUGIN / "__init__.py").read_text())
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and n.module.startswith("app."))]
    result = ModuleType("siqirestaurant_test")
    monkeypatch.setitem(sys.modules, result.__name__, result)
    site = SimpleNamespace(url="https://si-qi.xyz", cookie="secret=one", ua="fixture-UA")
    result.__dict__.update(_PluginBase=Base, settings=SimpleNamespace(PROXY=None),
                           update_plugin_job=Mock(), SiteOper=lambda: SimpleNamespace(get_by_domain=lambda _: site))
    exec(compile(tree, str(PLUGIN / "__init__.py"), "exec"), result.__dict__)
    result.site = site
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("unexpected site GET")))
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("unexpected site POST")))
    return result


@pytest.fixture
def plugin(module):
    p = module.SiqiRestaurant()
    p.init_plugin({"enabled": True})
    data = snapshot()
    p._request = Mock(side_effect=lambda action, *args, **kwargs:
                      copy.deepcopy(data) if action == "fetch" else {"success": True, "message": "OK"})
    p.fixture = data
    assert p.api_state()["success"]
    return p


def action(p, name, **args):
    return p.api_action({"action": name, "args": args, "request_id": f"request-{time.time_ns()}"})


def ready(p, index=1):
    assert action(p, "assign_dish", station_index=index, dish_key="egg")["success"]
    assert action(p, "prepare", station_index=index)["success"]
    assert action(p, "cook", station_index=index)["success"]
    p._runtime["kitchen"][index-1]["ready_at"] = time.time() - 1
    p._advance()


def test_market_api_and_federation(plugin, module):
    entry = json.loads((ROOT / "package.v3.json").read_text())["SiqiRestaurant"]
    assert entry["version"] == plugin.plugin_version
    assert entry["release"] is True and entry["system_version"] == ">=3.0.0"
    assert (PLUGIN / plugin.get_render_mode()[1] / "remoteEntry.js").is_file()
    assert plugin.get_service() == []
    assert all(r["auth"] == "bear" and r["response_model"] for r in plugin.get_api())
    api = FastAPI()
    for r in plugin.get_api():
        api.add_api_route(r["path"], r["endpoint"], methods=r["methods"], response_model=r["response_model"])
    c = TestClient(api)
    result = c.get("/state")
    assert result.status_code == 200 and result.json()["restaurant"]["state"]["customers_total"] == 2
    bad = c.post("/action", json={"action": "serve_customer", "request_id": "invalid-operation"})
    assert bad.status_code == 200 and bad.json()["success"] is False
    assert "requestBody" in api.openapi()["paths"]["/action"]["post"]


def test_credentials_never_returned_and_blank_keeps_override(plugin):
    plugin.api_save_config({"cookie": "override=secret"})
    plugin.api_save_config({"cookie": ""})
    assert plugin._config["cookie"] == "override=secret"
    assert "secret" not in json.dumps(plugin.api_config())
    assert "secret" not in json.dumps(plugin.get_form())
    plugin.api_save_config({"clear_cookie": True})
    assert plugin._config["cookie"] == ""


def test_cooking_enforces_time_and_reserved_inventory(plugin):
    assert action(plugin, "assign_dish", station_index=1, dish_key="egg")["success"]
    assert not action(plugin, "cook", station_index=1)["success"]
    assert action(plugin, "prepare", station_index=1)["success"]
    assert action(plugin, "assign_dish", station_index=2, dish_key="egg")["success"]
    assert not action(plugin, "prepare", station_index=2)["success"]
    assert action(plugin, "cook", station_index=1)["success"]
    assert not action(plugin, "serve", station_index=1, customer_id=1)["success"]
    assert not action(plugin, "cancel", station_index=1)["success"]
    assert not action(plugin, "return_stove", station_index=1)["success"]


def test_cook_state_survives_restart(plugin, module):
    ready(plugin)
    q = module.SiqiRestaurant()
    q.storage = copy.deepcopy(plugin.storage)
    q._request = plugin._request
    q.init_plugin({"enabled": True})
    assert q.api_state()["kitchen"][0]["status"] == "ready"


def test_serve_and_cleaning_enforced(plugin):
    ready(plugin)
    result = action(plugin, "serve", station_index=1, customer_id=1)
    assert result["success"] and result["kitchen"][0]["status"] == "idle"
    assert result["cleaning"]["1"] > time.time() + 9
    ready(plugin)
    assert not action(plugin, "serve", station_index=1, customer_id=1)["success"]
    posts = [c for c in plugin._request.call_args_list if c.args[0] == "serve_customer"]
    assert len(posts) == 1 and posts[0].args[1] == {"dish_key": "egg", "customer_id": 1}


def test_return_matches_site_discard_semantics(plugin):
    ready(plugin)
    assert action(plugin, "return_stove", station_index=1)["success"]
    assert any(c.args[:2] == ("discard_dish", {"dish_key": "egg"}) for c in plugin._request.call_args_list)


def test_duplicate_purchase_not_replayed(plugin):
    payload = {"action": "purchase_ingredient", "args": {"ingredient_key": "egg", "quantity": 2, "max_cost": 24},
               "request_id": "repeat-purchase-0001"}
    assert plugin.api_action(payload)["success"]
    assert "重复" in plugin.api_action(payload)["message"]
    assert sum(c.args[0] == "purchase_ingredient" for c in plugin._request.call_args_list) == 1


def test_restart_after_write_before_response_does_not_repeat(plugin, module):
    payload = {"action": "purchase_ingredient", "args": {"ingredient_key": "egg", "quantity": 1, "max_cost": 12},
               "request_id": "completed-before-crash"}
    original = plugin._result
    def crash_after_success(success=True, message="", **extra):
        if message == "OK":
            raise RuntimeError("simulated process interruption after persistence")
        return original(success, message, **extra)
    plugin._result = crash_after_success
    with pytest.raises(RuntimeError):
        plugin.api_action(payload)
    restored = module.SiqiRestaurant()
    restored.storage = copy.deepcopy(plugin.storage)
    restored._request = plugin._request
    restored.init_plugin({"enabled": True})
    assert "重复" in restored.api_action(payload)["message"]
    assert sum(c.args[0] == "purchase_ingredient" for c in plugin._request.call_args_list) == 1


@pytest.mark.parametrize("quantity", [-1, 0, 0.5, 10001, True, "1e5"])
def test_invalid_purchase_never_sent(plugin, quantity):
    assert not action(plugin, "purchase_ingredient", ingredient_key="egg", quantity=quantity, max_cost=1e9)["success"]
    assert not any(c.args[0] == "purchase_ingredient" for c in plugin._request.call_args_list)


def test_price_change_requires_new_confirmation(plugin):
    assert not action(plugin, "purchase_ingredient", ingredient_key="egg", quantity=2, max_cost=20)["success"]
    assert not action(plugin, "hire_staff", role="chef", quantity=1, max_cost=5000)["success"]
    assert not action(plugin, "hire_staff", role="chef", quantity=2, max_cost=20000)["success"]


def test_uncertain_write_persisted_and_explicitly_resolved(plugin, module):
    original = plugin._request
    plugin._request = Mock(side_effect=lambda a, *args, **kwargs: original(a, *args, **kwargs)
                           if a == "fetch" else (_ for _ in ()).throw(module.RestaurantError("结果不明")))
    payload = {"action": "purchase_ingredient", "args": {"ingredient_key": "egg", "quantity": 1, "max_cost": 12},
               "request_id": "uncertain-purchase-0001"}
    assert plugin.api_action(payload)["uncertain"]
    assert plugin.storage["runtime"]["pending"]
    assert plugin.api_refresh()["uncertain"]
    assert not plugin.api_action(payload)["success"]
    assert not plugin.api_resolve({})["success"]
    plugin._request = original
    assert not plugin.api_resolve({"acknowledged": True})["uncertain"]
    before = len(original.call_args_list)
    assert "重复" in plugin.api_action(payload)["message"]
    assert all(c.args[0] == "fetch" for c in original.call_args_list[before:])


def test_staff_off_by_default_and_bound_to_seat(plugin):
    plugin.api_tick({})
    assert plugin._runtime["kitchen"][0]["status"] == "idle"
    plugin.api_tick({"run_staff": True})
    assert plugin._runtime["kitchen"][0]["status"] == "cooking"
    assert plugin._runtime["kitchen"][1]["status"] == "idle"
    plugin._runtime["kitchen"][0]["ready_at"] = time.time()-1
    plugin.api_tick({"run_staff": True})
    assert any(c.args[0] == "serve_customer" for c in plugin._request.call_args_list)
    assert not any(c.args[0] in {"purchase_ingredient", "hire_staff", "visit_restaurant", "start_session"}
                   for c in plugin._request.call_args_list)


def test_customer_timeout_not_early(plugin):
    plugin.api_tick({})
    assert not any(c.args[0] == "customer_left" for c in plugin._request.call_args_list)
    plugin.fixture["state"]["customer_plan"][0]["deadline"] = time.time()-1
    plugin.api_refresh()
    plugin.api_tick({})
    assert any(c.args[:2] == ("customer_left", {"customer_id": 1}) for c in plugin._request.call_args_list)


def test_account_change_resets_kitchen_and_disabled_blocks_requests(plugin, module):
    ready(plugin)
    module.site.cookie = "secret=two"
    assert plugin.api_state()["kitchen"][0]["status"] == "idle"
    plugin.api_save_config({"enabled": False})
    plugin._request.reset_mock()
    assert not plugin.api_tick({"run_staff": True})["success"]
    plugin._request.assert_not_called()


def test_new_day_drops_old_kitchen(plugin):
    ready(plugin)
    plugin.fixture["state"]["session_date"] = "2026-10-20"
    assert plugin.api_refresh()["kitchen"][0]["status"] == "idle"


def test_visit_confirmation_not_auto_accepted(plugin):
    old = plugin._request
    plugin._request = Mock(side_effect=lambda a,*args,**kwargs:
                           {"success": False, "requires_confirmation": True, "message": "请确认"}
                           if a == "visit_restaurant" else old(a,*args,**kwargs))
    result = action(plugin, "visit_restaurant", target_username="fixture-user")
    assert result["requires_confirmation"]
    calls = [c for c in plugin._request.call_args_list if c.args[0] == "visit_restaurant"]
    assert len(calls) == 1 and "confirm" not in calls[0].args[1]


def test_request_multipart_timeout_and_no_redirect(module, monkeypatch):
    p = module.SiqiRestaurant()
    p.init_plugin({"enabled": True})
    resp = requests.Response()
    resp.status_code = 200
    resp._content = b'{"success":true}'
    post = Mock(return_value=resp)
    monkeypatch.setattr(requests, "post", post)
    assert p._request("purchase_ingredient", {"quantity": 1})["success"]
    assert post.call_args.kwargs["files"]["action"] == (None, "purchase_ingredient")
    assert post.call_args.kwargs["allow_redirects"] is False
    post.reset_mock(side_effect=True)
    post.side_effect = requests.Timeout("secret=one must not leak")
    with pytest.raises(module.RestaurantError, match="结果不明") as exc:
        p._request("purchase_ingredient", {})
    assert "secret" not in str(exc.value) and post.call_count == 1
    module.site.url = "https://evil.example"
    with pytest.raises(module.RestaurantError, match="https://si-qi.xyz"):
        p._credentials()


def test_simultaneous_duplicate_request_one_write(plugin):
    payload = {"action": "purchase_ingredient", "args": {"ingredient_key": "egg", "quantity": 1, "max_cost": 12},
               "request_id": "same-concurrent-request"}
    threads = [threading.Thread(target=plugin.api_action, args=(payload,)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(c.args[0] == "purchase_ingredient" for c in plugin._request.call_args_list) == 1


class GameServer:
    """Independent finite game simulation: queues, ingredient debits, seating and deadlines."""
    def __init__(self, clock, count=15):
        self.clock = clock
        self.data = snapshot()
        self.data['user']['magic'] = 100000
        self.data['state'].update(session_status='ready', customers_total=count,
                                  customer_plan=[], customers_served=0)
        self.data['state']['unlocked']['stations'] = 4
        self.data['state']['unlocked']['seats'] = 4
        self.data['inventory']['ingredients']['egg'] = 4
        self.queue = list(range(1, count+1))
        self.cooldown = {}
        self.calls = []
        self.served = []

    def seat(self):
        state = self.data['state']
        if state['session_status'] != 'open':
            return
        occupied = {c['seat'] for c in state['customer_plan'] if c['status'] == 'waiting'}
        for seat in range(1, 5):
            if seat not in occupied and self.queue and self.cooldown.get(seat, 0) <= self.clock[0]:
                state['customer_plan'].append(dict(id=self.queue.pop(0), seat=seat, dish_key='egg',
                    status='waiting', deadline=self.clock[0]+40, patience=40))
        if not self.queue and not any(c['status']=='waiting' for c in state['customer_plan']):
            state['session_status'] = 'closed'

    def __call__(self, action, payload=None, **kwargs):
        self.calls.append((action, payload, self.clock[0]))
        self.seat()
        if action == 'start_session':
            assert self.data['state']['session_status'] == 'ready'
            self.data['state']['session_status'] = 'open'
            self.seat()
        elif action == 'purchase_ingredient':
            assert payload['quantity'] > 0
            self.data['inventory']['ingredients']['egg'] += payload['quantity']
            self.data['user']['magic'] -= payload['quantity'] * 12
        elif action == 'serve_customer':
            c = next(c for c in self.data['state']['customer_plan'] if c['id']==payload['customer_id'])
            assert c['status'] == 'waiting' and c['deadline'] > self.clock[0]
            assert c['dish_key'] == payload['dish_key']
            assert self.data['inventory']['ingredients']['egg'] >= 2
            self.data['inventory']['ingredients']['egg'] -= 2
            self.data['user']['magic'] += 80
            self.data['state']['customers_served'] += 1
            c['status'] = 'served'
            self.served.append(c['id'])
            self.cooldown[c['seat']] = self.clock[0]+10
            self.seat()
        elif action == 'customer_left':
            c = next(c for c in self.data['state']['customer_plan'] if c['id']==payload['customer_id'])
            assert c['deadline'] <= self.clock[0]
            c['status'] = 'left'
            self.cooldown[c['seat']] = self.clock[0]+10
            self.seat()
        elif action != 'fetch':
            raise AssertionError(f'unexpected automation operation: {action}')
        return copy.deepcopy(self.data)


def enable_auto(p, **config):
    assert p.api_save_config({'auto_enabled':True, 'start_time':'00:00', 'magic_reserve':0, **config})['success']


def test_complete_day_without_any_frontend_tick_with_restart(plugin, module, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    server = GameServer(clock)
    plugin._request = server
    enable_auto(plugin)
    for tick in range(200):
        plugin.run_automation()
        if tick == 4:
            q = module.SiqiRestaurant()
            q.storage = copy.deepcopy(plugin.storage)
            q.init_plugin(plugin._config)
            q._request = server
            plugin = q
        clock[0] += 1
    assert server.data['state']['session_status'] == 'closed'
    assert len(server.served) == len(set(server.served)) == 15
    assert not any(c[0] == 'customer_left' for c in server.calls)
    assert sum(c[0] == 'start_session' for c in server.calls) == 1
    assert plugin._runtime['automation']['spent'] == (30-4)*12
    assert len([c for c in server.calls if c[0]=='fetch']) < 50
    assert all(s['status']=='idle' for s in plugin._runtime['kitchen'])


def test_preflight_budget_and_reserve_prevent_opening(plugin):
    plugin.fixture['state']['session_status'] = 'ready'
    plugin.fixture['inventory']['ingredients']['egg'] = 0
    enable_auto(plugin, daily_budget=1)
    plugin.run_automation()
    assert not any(c.args[0]=='start_session' for c in plugin._request.call_args_list)
    assert '预算' in plugin._runtime['automation']['message']
    enable_auto(plugin, daily_budget=5000, magic_reserve=10000)
    plugin.run_automation()
    assert '保留魔力' in plugin._runtime['automation']['message']
    assert not any(c.args[0]=='start_session' for c in plugin._request.call_args_list)


def test_unknown_purchase_holds_budget_across_restart_and_config(plugin, module):
    plugin.fixture['inventory']['ingredients']['egg'] = 0
    enable_auto(plugin)
    previous = plugin._request
    plugin._request = Mock(side_effect=lambda a,*args,**kw: previous(a,*args,**kw) if a=='fetch'
                           else (_ for _ in ()).throw(module.RestaurantError('写入结果不明')))
    plugin.run_automation()
    assert plugin._runtime['pending']['action'] == 'purchase_ingredient'
    assert plugin._runtime['automation']['spent'] == 24
    q=module.SiqiRestaurant();q.storage=copy.deepcopy(plugin.storage);q.init_plugin(plugin._config)
    q._request=plugin._request
    q.run_automation()
    enable_auto(q, daily_budget=500)
    q.run_automation()
    assert q._runtime['automation']['spent'] == 24
    assert sum(c.args[0]=='purchase_ingredient' for c in q._request.call_args_list) == 1
    module.site.cookie = 'rotated=credential'
    q._context()
    assert q._runtime['automation']['spent'] == 24


def test_scheduler_lifecycle_manual_guard_and_page_readonly(plugin, module):
    enable_auto(plugin)
    jobs = plugin.get_service()
    assert len(jobs)==1 and jobs[0]['trigger'].interval.total_seconds()==1
    module.update_plugin_job.assert_called_with('SiqiRestaurant')
    assert not action(plugin,'start_session')['success']
    plugin.api_tick({'run_staff':True})
    assert plugin._runtime['kitchen'][0]['status']=='idle'
    plugin.stop_service()
    before=plugin._request.call_count
    plugin.run_automation()
    assert plugin._request.call_count==before
    assert plugin.api_save_config({'auto_enabled':False})['success']
    assert plugin.get_service()==[]


def test_cross_stove_service_and_cook_timer(plugin):
    ready(plugin, index=2)
    enable_auto(plugin)
    plugin.run_automation()
    assert plugin._runtime['kitchen'][1]['status']=='idle'
    assert any(c.args[:2]==('serve_customer', {'dish_key':'egg','customer_id':1}) for c in plugin._request.call_args_list)


def test_auto_no_duplicate_dishes_and_no_early_serving(plugin):
    enable_auto(plugin)
    plugin.run_automation()
    plugin.run_automation()
    assert [s['status'] for s in plugin._runtime['kitchen']]==['cooking','idle']
    assert not any(c.args[0]=='serve_customer' for c in plugin._request.call_args_list)


def test_autostart_time_and_idle_fetch_throttle(plugin, module, monkeypatch):
    clock=[1792369800.0]  # before 23:59 Asia/Shanghai
    monkeypatch.setattr(module.time,'time',lambda:clock[0])
    plugin.fixture['state']['session_status']='ready'
    enable_auto(plugin, start_time='23:59')
    for _ in range(30):
        plugin.run_automation();clock[0]+=1
    assert plugin._runtime['automation']['phase']=='waiting'
    assert sum(c.args[0]=='fetch' for c in plugin._request.call_args_list)<=2
    assert not any(c.args[0]=='start_session' for c in plugin._request.call_args_list)


def test_daily_budget_rollover_and_invalid_config(plugin, module, monkeypatch):
    enable_auto(plugin)
    clock=[time.time()];monkeypatch.setattr(module.time,'time',lambda:clock[0])
    plugin._auto_account()['spent']=100
    plugin.api_save_config({'daily_budget':200})
    assert plugin._auto_account()['spent']==100
    assert not plugin.api_save_config({'daily_budget':-1})['success']
    assert not plugin.api_save_config({'start_time':'24:00'})['success']
    clock[0]+=86400
    assert plugin._auto_account()['spent']==0


def test_transient_read_failure_does_not_write_and_backoff(plugin, module):
    enable_auto(plugin)
    plugin._request=Mock(side_effect=module.RestaurantError('读取失败'))
    plugin.run_automation();plugin.run_automation()
    assert plugin._request.call_count==1
    assert not plugin._runtime.get('pending')
    assert plugin._next_auto>time.time()+55

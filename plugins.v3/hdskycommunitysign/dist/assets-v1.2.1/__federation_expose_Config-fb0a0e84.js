import { importShared } from './__federation_fn_import-054b33c3.js';
import { t as time, c as connectionLabel, n as number } from './style-d0553728.js';

const {createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,unref:_unref,createElementBlock:_createElementBlock,withKeys:_withKeys} = await importShared('vue');


const _hoisted_1 = { class: "hcs-app" };
const _hoisted_2 = { class: "hcs-header" };
const _hoisted_3 = { class: "hcs-actions" };
const _hoisted_4 = { class: "hcs-card" };
const _hoisted_5 = { class: "hcs-card-title" };
const _hoisted_6 = {
  key: 0,
  class: "hcs-account"
};
const _hoisted_7 = { class: "hcs-login-row" };
const _hoisted_8 = { class: "hcs-login-row" };
const _hoisted_9 = { class: "hcs-actions" };
const _hoisted_10 = { class: "hcs-hint" };
const _hoisted_11 = { class: "hcs-card" };
const _hoisted_12 = { class: "hcs-switches" };
const _hoisted_13 = { class: "hcs-login-row" };
const _hoisted_14 = { class: "hcs-stack" };

const {computed,onBeforeUnmount,onMounted,reactive,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: { api: { type: Object, required: true }, pluginId: { type: String, required: true } },
  emits: ['switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const config = reactive({ enabled: false, uid: '', use_proxy: false, user_agent: '', auto_sign: false, notify: true, cron: '0 8 * * *', retry_count: 3, retry_interval: 300 });
const view = ref(null), loaded = ref(false), busy = ref(''), message = ref(''), messageType = ref('info');
const code = ref(''), cookie = ref(''), now = ref(Date.now() / 1000);
const auth = computed(() => view.value?.auth || {});
const uidValid = computed(() => /^[1-9][0-9]{0,11}$/.test(config.uid.trim()));
const cooldown = after => Math.max(0, Math.ceil((after || 0) - now.value));
const sendWait = computed(() => cooldown(Math.max(auth.value.send_after || 0, auth.value.retry_after || 0)));
const loginWait = computed(() => cooldown(Math.max(auth.value.verify_after || 0, auth.value.retry_after || 0)));
const blocked = computed(() => !loaded.value || !!busy.value);
const retryValid = computed(() => Number.isInteger(config.retry_count) && config.retry_count >= 0 && config.retry_count <= 10
  && Number.isInteger(config.retry_interval) && config.retry_interval >= 60 && config.retry_interval <= 86400);
const defaults = { VTextField: { variant: 'outlined', density: 'compact', hideDetails: 'auto' }, VBtn: { variant: 'tonal', color: 'primary' } };
let timer;

async function load() {
  busy.value = 'load';
  try {
    view.value = await props.api.get(`plugin/${props.pluginId}/state`);
    Object.assign(config, view.value.config);
    loaded.value = true;
    message.value = '';
  } catch {
    message.value = '读取配置失败，请重试。';
    messageType.value = 'error';
  } finally { busy.value = ''; }
}

async function perform(action) {
  if (blocked.value) return
  busy.value = action;
  message.value = '';
  try {
    const payload = action === 'save' ? { ...config } : {
      action, uid: config.uid.trim(), use_proxy: config.use_proxy, user_agent: config.user_agent,
      ...(action === 'login' ? { code: code.value } : {}),
      ...(action === 'cookie' ? { cookie: cookie.value } : {}),
    };
    const result = await props.api.post(`plugin/${props.pluginId}/${action === 'save' ? 'config' : 'auth'}`, payload);
    view.value = result.state;
    if (action === 'save' && result.success) Object.assign(config, result.state.config);
    now.value = Date.now() / 1000;
    message.value = result.message;
    messageType.value = result.success ? 'success' : 'warning';
  } catch {
    message.value = '操作请求未完成，请检查连接后重试；本次不会自动重发。';
    messageType.value = 'error';
    // 只读本地状态，恢复已保存的冷却；不重复发送验证码或登录请求。
    try { view.value = await props.api.get(`plugin/${props.pluginId}/state`); } catch { /* 保留现有状态 */ }
  } finally {
    if (action === 'login') code.value = '';
    if (action === 'cookie') cookie.value = '';
    busy.value = '';
  }
}

onMounted(() => { load(); timer = setInterval(() => { now.value = Date.now() / 1000; }, 1000); });
onBeforeUnmount(() => { clearInterval(timer); code.value = ''; cookie.value = ''; });

return (_ctx, _cache) => {
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_defaults_provider = _resolveComponent("v-defaults-provider");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createVNode(_component_v_defaults_provider, { defaults: defaults }, {
      default: _withCtx(() => [
        _createElementVNode("header", _hoisted_2, [
          _cache[22] || (_cache[22] = _createElementVNode("div", null, [
            _createElementVNode("h2", null, "天空社区客户端签到"),
            _createElementVNode("p", null, "登录与自动签到设置")
          ], -1)),
          _createElementVNode("div", _hoisted_3, [
            _createVNode(_component_v_btn, {
              disabled: !!busy.value,
              onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
            }, {
              default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                _createTextVNode("每日统计", -1)
              ]))]),
              _: 1
            }, 8, ["disabled"]),
            _createVNode(_component_v_btn, {
              disabled: blocked.value || !retryValid.value,
              loading: busy.value === 'save',
              onClick: _cache[1] || (_cache[1] = $event => (perform('save')))
            }, {
              default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                _createTextVNode("保存设置", -1)
              ]))]),
              _: 1
            }, 8, ["disabled", "loading"]),
            _createVNode(_component_v_btn, {
              variant: "text",
              onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
            }, {
              default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                _createTextVNode("关闭", -1)
              ]))]),
              _: 1
            })
          ])
        ]),
        (message.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: messageType.value,
              variant: "tonal",
              role: "status"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(message.value), 1)
              ]),
              _: 1
            }, 8, ["type"]))
          : _createCommentVNode("", true),
        (busy.value === 'load')
          ? (_openBlock(), _createBlock(_component_v_progress_linear, {
              key: 1,
              indeterminate: "",
              color: "primary",
              "aria-label": "读取配置"
            }))
          : _createCommentVNode("", true),
        (!loaded.value && !busy.value)
          ? (_openBlock(), _createBlock(_component_v_btn, {
              key: 2,
              onClick: load
            }, {
              default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                _createTextVNode("重新读取", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createElementVNode("section", _hoisted_4, [
          _createElementVNode("div", _hoisted_5, [
            _cache[24] || (_cache[24] = _createElementVNode("h3", null, "社区登录", -1)),
            _createVNode(_component_v_chip, {
              color: auth.value.verified ? 'success' : 'default',
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(auth.value.verified ? '已登录' : auth.value.cookie_configured ? '会话待验证' : '未登录'), 1)
              ]),
              _: 1
            }, 8, ["color"])
          ]),
          _cache[28] || (_cache[28] = _createElementVNode("p", { class: "hcs-hint" }, "填写 UID 后直接获取验证码并登录，无需保存或关闭页面。", -1)),
          (auth.value.uid)
            ? (_openBlock(), _createElementBlock("p", _hoisted_6, [
                _createTextVNode(_toDisplayString(auth.value.display_name || '社区账号') + " · UID " + _toDisplayString(auth.value.uid), 1),
                _createElementVNode("span", null, "上次验证 " + _toDisplayString(_unref(time)(auth.value.checked_at)), 1)
              ]))
            : _createCommentVNode("", true),
          _createElementVNode("div", _hoisted_7, [
            _createVNode(_component_v_text_field, {
              modelValue: config.uid,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.uid) = $event)),
              label: "HDSky UID",
              "aria-label": "HDSky UID",
              inputmode: "numeric",
              maxlength: "12",
              disabled: blocked.value,
              autocomplete: "off"
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_btn, {
              disabled: blocked.value || !uidValid.value || sendWait.value > 0,
              loading: busy.value === 'send',
              onClick: _cache[4] || (_cache[4] = $event => (perform('send')))
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(sendWait.value ? `${sendWait.value} 秒后可重发` : '发送验证码'), 1)
              ]),
              _: 1
            }, 8, ["disabled", "loading"])
          ]),
          _createElementVNode("div", _hoisted_8, [
            _createVNode(_component_v_text_field, {
              modelValue: code.value,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((code).value = $event)),
              label: "站内信六位验证码",
              "aria-label": "站内信六位验证码",
              type: "password",
              inputmode: "numeric",
              maxlength: "6",
              autocomplete: "one-time-code",
              disabled: blocked.value,
              onKeydown: _cache[6] || (_cache[6] = _withKeys($event => (!blocked.value && uidValid.value && /^\d{6}$/.test(code.value) && auth.value.pending_uid === config.uid.trim() && !loginWait.value && perform('login')), ["enter"]))
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_btn, {
              disabled: blocked.value || !uidValid.value || !/^\d{6}$/.test(code.value) || auth.value.pending_uid !== config.uid.trim() || loginWait.value > 0,
              loading: busy.value === 'login',
              onClick: _cache[7] || (_cache[7] = $event => (perform('login')))
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(loginWait.value ? `${loginWait.value} 秒后可登录` : '登录'), 1)
              ]),
              _: 1
            }, 8, ["disabled", "loading"])
          ]),
          _createElementVNode("div", _hoisted_9, [
            _createVNode(_component_v_btn, {
              disabled: blocked.value || !auth.value.cookie_configured || cooldown(auth.value.retry_after) > 0,
              loading: busy.value === 'check',
              onClick: _cache[8] || (_cache[8] = $event => (perform('check')))
            }, {
              default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                _createTextVNode("检测 Cookie 与站点连通性", -1)
              ]))]),
              _: 1
            }, 8, ["disabled", "loading"]),
            _cache[26] || (_cache[26] = _createElementVNode("span", { class: "hcs-hint" }, "检测已保存的 Cookie，只读查询，不执行签到。", -1))
          ]),
          _createElementVNode("p", _hoisted_10, [
            _createTextVNode(_toDisplayString(_unref(connectionLabel)(auth.value.connection_status)) + " · " + _toDisplayString(_unref(time)(auth.value.connection_at)), 1),
            _cache[27] || (_cache[27] = _createElementVNode("br", null, null, -1)),
            _createTextVNode("上次查询余额 " + _toDisplayString(_unref(number)(auth.value.balance)) + " 银元 · " + _toDisplayString(_unref(time)(auth.value.balance_at)), 1)
          ])
        ]),
        _createElementVNode("section", _hoisted_11, [
          _cache[30] || (_cache[30] = _createElementVNode("h3", null, "自动签到", -1)),
          _createElementVNode("div", _hoisted_12, [
            _createVNode(_component_v_switch, {
              modelValue: config.enabled,
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.enabled) = $event)),
              label: "启用插件",
              "aria-label": "启用插件",
              color: "primary",
              "hide-details": "",
              disabled: blocked.value
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_sign,
              "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.auto_sign) = $event)),
              label: "每日定时签到",
              "aria-label": "每日定时签到",
              color: "primary",
              "hide-details": "",
              disabled: blocked.value
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_switch, {
              modelValue: config.notify,
              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.notify) = $event)),
              label: "发送结果通知",
              "aria-label": "发送结果通知",
              color: "primary",
              "hide-details": "",
              disabled: blocked.value
            }, null, 8, ["modelValue", "disabled"])
          ]),
          _createVNode(_component_v_text_field, {
            modelValue: config.cron,
            "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.cron) = $event)),
            label: "签到 Cron",
            "aria-label": "签到 Cron",
            hint: "默认每天 08:00，执行时区跟随 MP。",
            "persistent-hint": "",
            disabled: blocked.value
          }, null, 8, ["modelValue", "disabled"]),
          _createElementVNode("div", _hoisted_13, [
            _createVNode(_component_v_text_field, {
              modelValue: config.retry_count,
              "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.retry_count) = $event)),
              modelModifiers: { number: true },
              type: "number",
              min: "0",
              max: "10",
              step: "1",
              label: "签到重试次数",
              "aria-label": "签到重试次数",
              hint: "0 关闭，最多 10 次；不含首次签到。",
              "persistent-hint": "",
              disabled: blocked.value
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_text_field, {
              modelValue: config.retry_interval,
              "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.retry_interval) = $event)),
              modelModifiers: { number: true },
              type: "number",
              min: "60",
              max: "86400",
              step: "1",
              label: "重试间隔（秒）",
              "aria-label": "重试间隔（秒）",
              hint: "60–86400 秒；遇到限流会等待冷却结束。",
              "persistent-hint": "",
              disabled: blocked.value
            }, null, 8, ["modelValue", "disabled"])
          ]),
          _cache[31] || (_cache[31] = _createElementVNode("p", { class: "hcs-hint" }, "失败后按间隔自动重试，手动签到同样适用。结果未知时只查询状态；Cookie 失效停止重试。任务由 MP 管理，每 30 秒检查一次到期计划。", -1)),
          (loaded.value && !retryValid.value)
            ? (_openBlock(), _createBlock(_component_v_alert, {
                key: 0,
                type: "warning",
                variant: "tonal"
              }, {
                default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                  _createTextVNode("重试次数须为 0–10 的整数，间隔须为 60–86400 秒的整数。", -1)
                ]))]),
                _: 1
              }))
            : _createCommentVNode("", true),
          _cache[32] || (_cache[32] = _createElementVNode("p", { class: "hcs-hint" }, "自动签到设置在点击“保存设置”后生效。", -1))
        ]),
        _createVNode(_component_v_expansion_panels, { variant: "accordion" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_expansion_panel, { elevation: "0" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_expansion_panel_title, null, {
                  default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                    _createTextVNode("手动 Cookie 与连接设置", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_expansion_panel_text, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_14, [
                      _cache[35] || (_cache[35] = _createElementVNode("p", { class: "hcs-hint" }, "也可使用 hdsky.supertimi.de 社区的 Cookie 登录。UID 可留空，填写时会核对账号；此处不使用 hdsky.me 主站 Cookie。", -1)),
                      _createVNode(_component_v_text_field, {
                        modelValue: cookie.value,
                        "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((cookie).value = $event)),
                        label: "社区 Cookie",
                        "aria-label": "社区 Cookie",
                        type: "password",
                        autocomplete: "new-password",
                        disabled: blocked.value
                      }, null, 8, ["modelValue", "disabled"]),
                      _createVNode(_component_v_btn, {
                        disabled: blocked.value || !cookie.value.trim() || cooldown(auth.value.retry_after) > 0,
                        loading: busy.value === 'cookie',
                        onClick: _cache[16] || (_cache[16] = $event => (perform('cookie')))
                      }, {
                        default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                          _createTextVNode("验证并保存 Cookie", -1)
                        ]))]),
                        _: 1
                      }, 8, ["disabled", "loading"]),
                      _createVNode(_component_v_switch, {
                        modelValue: config.use_proxy,
                        "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.use_proxy) = $event)),
                        label: "使用 MP 代理",
                        "aria-label": "使用 MP 代理",
                        color: "primary",
                        "hide-details": "",
                        disabled: blocked.value
                      }, null, 8, ["modelValue", "disabled"]),
                      _createVNode(_component_v_text_field, {
                        modelValue: config.user_agent,
                        "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.user_agent) = $event)),
                        label: "User-Agent",
                        "aria-label": "User-Agent",
                        disabled: blocked.value
                      }, null, 8, ["modelValue", "disabled"]),
                      _cache[36] || (_cache[36] = _createElementVNode("p", { class: "hcs-hint" }, "登录操作会应用当前 UID 和连接设置。验证码与手动 Cookie 输入在提交后清空。", -1))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };

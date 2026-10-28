import { importShared } from './__federation_fn_import-054b33c3.js';
import { c as connectionLabel, t as time, n as number, s as statusLabel, a as statusColor } from './style-d0553728.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,unref:_unref,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "hcs-app" };
const _hoisted_2 = { class: "hcs-header" };
const _hoisted_3 = { class: "hcs-actions" };
const _hoisted_4 = {
  key: 2,
  class: "hcs-hint"
};
const _hoisted_5 = { class: "hcs-summary" };
const _hoisted_6 = { class: "hcs-card" };
const _hoisted_7 = { class: "hcs-card" };
const _hoisted_8 = { class: "hcs-card" };
const _hoisted_9 = { class: "hcs-card" };
const _hoisted_10 = { class: "hcs-actions" };
const _hoisted_11 = { class: "hcs-hint" };
const _hoisted_12 = { class: "hcs-card" };
const _hoisted_13 = { class: "hcs-card-title" };
const _hoisted_14 = {
  key: 0,
  class: "hcs-table-wrap"
};
const _hoisted_15 = { class: "hcs-table" };
const _hoisted_16 = {
  key: 1,
  class: "hcs-hint"
};
const _hoisted_17 = { class: "hcs-stack" };

const {computed,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: { api: { type: Object, required: true }, pluginId: { type: String, required: true } },
  emits: ['switch', 'close', 'action'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const view = ref(null), busy = ref(''), message = ref(''), messageType = ref('info'), period = ref(7);
const stats = computed(() => view.value?.statistics || {});
const today = computed(() => stats.value.today || {});
const rows = computed(() => (stats.value.days || []).slice(0, period.value));

async function load() {
  if (busy.value) return
  busy.value = 'load';
  try {
    view.value = await props.api.get(`plugin/${props.pluginId}/state`);
    message.value = '';
    if (view.value.auth.cookie_configured) {
      const result = await props.api.post(`plugin/${props.pluginId}/auth`, { action: 'check' });
      view.value = result.state;
      if (!result.success) { message.value = result.message; messageType.value = 'warning'; }
    }
  }
  catch { message.value = '读取统计失败，请点击刷新重试。'; messageType.value = 'error'; }
  finally { busy.value = ''; }
}
async function sign() {
  if (busy.value) return
  busy.value = 'sign';
  try {
    const result = await props.api.post(`plugin/${props.pluginId}/sign`);
    view.value = result.state;
    message.value = result.message;
    messageType.value = result.success ? 'success' : 'warning';
    emit('action');
  } catch {
    message.value = '签到请求未完成，请刷新查看已保存结果；本次不会自动重发。';
    messageType.value = 'error';
    try { view.value = await props.api.get(`plugin/${props.pluginId}/state`); } catch { /* 保留现有统计 */ }
  } finally { busy.value = ''; }
}
onMounted(load);

return (_ctx, _cache) => {
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_btn_toggle = _resolveComponent("v-btn-toggle");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", null, [
        _cache[3] || (_cache[3] = _createElementVNode("h2", null, "每日签到统计", -1)),
        _createElementVNode("p", null, "天空社区 · " + _toDisplayString(stats.value.uid ? `UID ${stats.value.uid}` : '请先登录社区账号'), 1)
      ]),
      _createElementVNode("div", _hoisted_3, [
        _createVNode(_component_v_btn, {
          color: "primary",
          variant: "tonal",
          disabled: !!busy.value,
          loading: busy.value === 'load',
          onClick: load
        }, {
          default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
            _createTextVNode("刷新余额与统计", -1)
          ]))]),
          _: 1
        }, 8, ["disabled", "loading"]),
        _createVNode(_component_v_btn, {
          color: "primary",
          variant: "tonal",
          disabled: !!busy.value,
          onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
        }, {
          default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
            _createTextVNode("配置", -1)
          ]))]),
          _: 1
        }, 8, ["disabled"]),
        _createVNode(_component_v_btn, {
          variant: "text",
          onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [...(_cache[6] || (_cache[6] = [
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
    (view.value?.status.message)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: view.value.status.success ? 'success' : 'info',
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(view.value.status.message), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    (view.value)
      ? (_openBlock(), _createElementBlock("p", _hoisted_4, _toDisplayString(_unref(connectionLabel)(view.value.auth.connection_status)) + " · " + _toDisplayString(_unref(time)(view.value.auth.connection_at)) + "；上次查询余额 " + _toDisplayString(_unref(number)(view.value.auth.balance)) + " 银元 · " + _toDisplayString(_unref(time)(view.value.auth.balance_at)), 1))
      : _createCommentVNode("", true),
    (view.value?.retry.pending)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 3,
          type: "info",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode("已安排签到重试：已用 " + _toDisplayString(view.value.retry.used) + " / " + _toDisplayString(view.value.retry.limit) + " 次，下次 " + _toDisplayString(_unref(time)(view.value.retry.next_at)) + "。结果未知时仅查询确认。", 1)
          ]),
          _: 1
        }))
      : (view.value?.retry.limit && view.value.retry.used >= view.value.retry.limit)
        ? (_openBlock(), _createBlock(_component_v_alert, {
            key: 4,
            type: "warning",
            variant: "tonal"
          }, {
            default: _withCtx(() => [...(_cache[7] || (_cache[7] = [
              _createTextVNode("自动重试次数已用完，请检查连接或重新登录后手动签到。", -1)
            ]))]),
            _: 1
          }))
        : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_5, [
      _createElementVNode("article", _hoisted_6, [
        _createElementVNode("p", null, "今日签到 · " + _toDisplayString(today.value.day || '北京时间'), 1),
        _createElementVNode("strong", null, _toDisplayString(_unref(statusLabel)(today.value.status)), 1),
        (view.value)
          ? (_openBlock(), _createBlock(_component_v_chip, {
              key: 0,
              color: view.value.config.enabled ? 'success' : 'default',
              size: "small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(view.value.config.enabled ? '插件已启用' : '插件未启用'), 1)
              ]),
              _: 1
            }, 8, ["color"]))
          : _createCommentVNode("", true)
      ]),
      _createElementVNode("article", _hoisted_7, [
        _cache[9] || (_cache[9] = _createElementVNode("p", null, "今日奖励", -1)),
        _createElementVNode("strong", null, [
          _createTextVNode(_toDisplayString(_unref(number)(today.value.amount)) + " ", 1),
          _cache[8] || (_cache[8] = _createElementVNode("small", null, "银元", -1))
        ]),
        _createElementVNode("p", null, "当前余额 " + _toDisplayString(_unref(number)(view.value?.auth.balance)) + " 银元（只读查询，无需签到）", 1)
      ]),
      _createElementVNode("article", _hoisted_8, [
        _cache[11] || (_cache[11] = _createElementVNode("p", null, "近 30 天已签到", -1)),
        _createElementVNode("strong", null, [
          _createTextVNode(_toDisplayString(_unref(number)(stats.value.completed_days)) + " ", 1),
          _cache[10] || (_cache[10] = _createElementVNode("small", null, "天", -1))
        ]),
        _cache[12] || (_cache[12] = _createElementVNode("p", null, "同一账号每天计一次", -1))
      ]),
      _createElementVNode("article", _hoisted_9, [
        _cache[14] || (_cache[14] = _createElementVNode("p", null, "近 30 天奖励合计", -1)),
        _createElementVNode("strong", null, [
          _createTextVNode(_toDisplayString(_unref(number)(stats.value.reward_total)) + " ", 1),
          _cache[13] || (_cache[13] = _createElementVNode("small", null, "银元", -1))
        ]),
        _createElementVNode("p", null, _toDisplayString(stats.value.unknown_reward_days ? `另有 ${stats.value.unknown_reward_days} 天奖励数值未知` : '按已确认的每日奖励汇总'), 1)
      ])
    ]),
    _createElementVNode("div", _hoisted_10, [
      _createVNode(_component_v_btn, {
        color: "primary",
        variant: "flat",
        disabled: !!busy.value || !view.value?.config.enabled || !view.value?.auth.cookie_configured,
        loading: busy.value === 'sign',
        onClick: sign
      }, {
        default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
          _createTextVNode("立即签到", -1)
        ]))]),
        _: 1
      }, 8, ["disabled", "loading"]),
      _createElementVNode("span", _hoisted_11, _toDisplayString(!view.value?.config.enabled ? '在配置页启用插件并保存后可签到。' : '先查询社区今日状态，已签到会自动跳过提交。'), 1)
    ]),
    _createElementVNode("section", _hoisted_12, [
      _createElementVNode("div", _hoisted_13, [
        _cache[18] || (_cache[18] = _createElementVNode("h3", null, "每日明细", -1)),
        _createVNode(_component_v_btn_toggle, {
          modelValue: period.value,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((period).value = $event)),
          mandatory: "",
          density: "compact",
          color: "primary",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, { value: 7 }, {
              default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                _createTextVNode("近 7 天", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_btn, { value: 30 }, {
              default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                _createTextVNode("近 30 天", -1)
              ]))]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue"])
      ]),
      _cache[20] || (_cache[20] = _createElementVNode("p", { class: "hcs-hint" }, "按北京时间归档，仅统计当前账号。尚无记录表示未被插件记录，不能据此判断漏签。", -1)),
      (rows.value.length)
        ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
            _createElementVNode("table", _hoisted_15, [
              _cache[19] || (_cache[19] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", null, "日期"),
                  _createElementVNode("th", null, "状态"),
                  _createElementVNode("th", null, "奖励 / 银元"),
                  _createElementVNode("th", null, "余额 / 银元"),
                  _createElementVNode("th", null, "记录时间")
                ])
              ], -1)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rows.value, (row) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: row.day
                  }, [
                    _createElementVNode("td", null, _toDisplayString(row.day), 1),
                    _createElementVNode("td", null, [
                      _createVNode(_component_v_chip, {
                        color: _unref(statusColor)(row.status),
                        size: "small",
                        variant: "tonal"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(_unref(statusLabel)(row.status)), 1)
                        ]),
                        _: 2
                      }, 1032, ["color"])
                    ]),
                    _createElementVNode("td", null, _toDisplayString(_unref(number)(row.amount)), 1),
                    _createElementVNode("td", null, _toDisplayString(_unref(number)(row.balance)), 1),
                    _createElementVNode("td", null, _toDisplayString(row.time ? _unref(time)(row.time) : '—'), 1)
                  ]))
                }), 128))
              ])
            ])
          ]))
        : (_openBlock(), _createElementBlock("p", _hoisted_16, "登录后刷新即可查询余额与每日状态，无需先签到。"))
    ]),
    (view.value?.history.length)
      ? (_openBlock(), _createBlock(_component_v_expansion_panels, {
          key: 5,
          variant: "accordion"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_expansion_panel, { elevation: "0" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_expansion_panel_title, null, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createTextVNode("最近操作记录", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_expansion_panel_text, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_17, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.history, (row, index) => {
                        return (_openBlock(), _createElementBlock("p", {
                          key: index,
                          class: "hcs-hint"
                        }, _toDisplayString(_unref(time)(row.time)) + " · UID " + _toDisplayString(row.uid || '—') + " · " + _toDisplayString(row.message), 1))
                      }), 128))
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }))
      : _createCommentVNode("", true)
  ]))
}
}

};

export { _sfc_main as default };

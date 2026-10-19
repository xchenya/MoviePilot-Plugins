import { importShared } from './__federation_fn_import-054b33c3.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-c4c0bc37.js';

const style_css_vue_type_style_index_0_src_33c4a3f6_scoped_33c4a3f6_lang = '';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle} = await importShared('vue');


const _hoisted_1 = {
  class: "sq-app",
  "aria-label": "思齐收垃圾配置"
};
const _hoisted_2 = { class: "sq-topbar" };
const _hoisted_3 = { class: "sq-heading" };
const _hoisted_4 = { class: "sq-brand" };
const _hoisted_5 = { class: "sq-actions" };
const _hoisted_6 = ["disabled"];
const _hoisted_7 = { class: "sq-card" };
const _hoisted_8 = { class: "sq-card-heading" };
const _hoisted_9 = { class: "sq-switch-grid sq-card-body" };
const _hoisted_10 = { class: "sq-config-grid" };
const _hoisted_11 = { class: "sq-card" };
const _hoisted_12 = { class: "sq-card-heading" };
const _hoisted_13 = { class: "sq-fields" };
const _hoisted_14 = {
  key: 0,
  class: "sq-hint"
};
const _hoisted_15 = { class: "sq-card" };
const _hoisted_16 = { class: "sq-card-heading" };
const _hoisted_17 = { class: "sq-fields" };
const _hoisted_18 = { class: "sq-card" };
const _hoisted_19 = { class: "sq-card-heading" };
const _hoisted_20 = { class: "sq-fields" };
const _hoisted_21 = { class: "sq-footer" };

const {onMounted,reactive,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: { api: Object, pluginId: { type: String, default: 'SiQiCleanBeach' }, initialConfig: { type: Object, default: () => ({}) } },
  emits: ['switch', 'close', 'config-updated'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const config = reactive({ enabled: false, notify: true, run_once: false, schedule_mode: 'auto', cron: '1 */2 * * *', interval_minutes: 121, auto_brick: false, brick_cron: '', brick_retry_limit: 1, cookie: '' });
const loading = ref(false);
const loaded = ref(false);
const saving = ref(false);
const showCookie = ref(false);
const message = ref('');
const messageType = ref('info');
const modes = [{ title: '按站点冷却（推荐）', value: 'auto' }, { title: '固定时间（Cron）', value: 'cron' }, { title: '旧版固定间隔', value: 'interval' }];
const switches = [
  { key: 'enabled', label: '启用插件', description: '开启后台定时任务', icon: 'mdi-power-plug-outline', accent: '39,134,93', color: '#27865d' },
  { key: 'notify', label: '运行通知', description: '通过 MP 发送任务结果', icon: 'mdi-bell-outline', accent: '65,115,193', color: '#4173c1' },
  { key: 'run_once', label: '保存后运行一次', description: '运行后自动关闭此开关', icon: 'mdi-play-circle-outline', accent: '139,91,171', color: '#8b5bab' },
];
const apiGet = (path) => props.api.get(`plugin/${props.pluginId}${path}`);
const apiPost = (path, payload) => props.api.post(`plugin/${props.pluginId}${path}`, payload);
function applyConfig(value) {
  for (const key of Object.keys(config)) if (Object.hasOwn(value, key)) config[key] = value[key];
}
function validConfig(value) {
  return typeof value?.enabled === 'boolean' && modes.some(mode => mode.value === value.schedule_mode)
}
async function loadConfig() {
  loading.value = true;
  loaded.value = false;
  try {
    const result = await apiGet('/config');
    if (!validConfig(result)) throw new Error('invalid config')
    applyConfig(result);
    loaded.value = true;
    message.value = '';
  } catch {
    message.value = '配置读取失败，请重新加载后再保存。';
    messageType.value = 'error';
  } finally { loading.value = false; }
}
async function saveConfig() {
  if (!loaded.value || saving.value) return
  saving.value = true;
  try {
    const result = await apiPost('/config', { ...config, brick_cron: config.brick_cron || '' });
    if (result?.success !== false && (result?.success !== true || !validConfig(result.config))) {
      message.value = '保存结果未能确认，请重新加载核对。';
      messageType.value = 'error';
      loaded.value = false;
      return
    }
    if (result.success === false) {
      message.value = result?.message || '配置未保存，请稍后重试。';
      messageType.value = 'error';
      return
    }
    applyConfig(result.config);
    emit('config-updated', result.config);
    message.value = result.message || '配置已保存';
    messageType.value = 'success';
  } catch (error) {
    const status = error?.response?.status ?? error?.status;
    message.value = status === 422 ? '设置格式不正确，请检查 Cron、间隔与重试次数后再保存。' : '保存结果未能确认，请重新加载核对。';
    messageType.value = 'error';
    if (status !== 422) loaded.value = false;
  } finally { saving.value = false; }
}
onMounted(loadConfig);

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_text_field = _resolveComponent("v-text-field");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-cog-outline",
            size: "24"
          })
        ]),
        _cache[11] || (_cache[11] = _createElementVNode("div", null, [
          _createElementVNode("h2", null, "思齐收垃圾 · 配置"),
          _createElementVNode("p", null, "管理清理、搬砖与运行通知")
        ], -1))
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_v_btn, {
          variant: "tonal",
          size: "small",
          "aria-label": "状态页",
          onClick: _cache[0] || (_cache[0] = $event => (emit('switch', 'page')))
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              icon: "mdi-view-dashboard-outline",
              size: "18"
            }),
            _cache[12] || (_cache[12] = _createElementVNode("span", { class: "sq-button-label" }, "状态页", -1))
          ]),
          _: 1
        }),
        _createVNode(_component_v_btn, {
          color: "#27865d",
          variant: "tonal",
          size: "small",
          "prepend-icon": "mdi-content-save-outline",
          loading: saving.value,
          disabled: !loaded.value || saving.value,
          onClick: saveConfig
        }, {
          default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
            _createTextVNode("保存", -1)
          ]))]),
          _: 1
        }, 8, ["loading", "disabled"]),
        _createVNode(_component_v_btn, {
          variant: "text",
          size: "small",
          "aria-label": "关闭",
          onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              icon: "mdi-close",
              size: "18"
            })
          ]),
          _: 1
        })
      ])
    ]),
    (message.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: messageType.value,
          density: "compact",
          variant: "tonal",
          closable: "",
          role: "status",
          "onClick:close": _cache[2] || (_cache[2] = $event => (message.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1),
            (!loaded.value && !loading.value)
              ? (_openBlock(), _createBlock(_component_v_btn, {
                  key: 0,
                  variant: "text",
                  size: "small",
                  onClick: loadConfig
                }, {
                  default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                    _createTextVNode("重新加载", -1)
                  ]))]),
                  _: 1
                }))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    (loading.value)
      ? (_openBlock(), _createBlock(_component_v_progress_linear, {
          key: 1,
          indeterminate: "",
          color: "#27865d",
          "aria-label": "读取配置"
        }))
      : _createCommentVNode("", true),
    _createElementVNode("fieldset", {
      class: "sq-form",
      disabled: !loaded.value || saving.value
    }, [
      _createElementVNode("section", _hoisted_7, [
        _createElementVNode("div", _hoisted_8, [
          _createElementVNode("h3", null, [
            _createVNode(_component_v_icon, {
              icon: "mdi-toggle-switch-outline",
              size: "18",
              color: "#27865d"
            }),
            _cache[15] || (_cache[15] = _createTextVNode("基础设置", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_9, [
          (_openBlock(), _createElementBlock(_Fragment, null, _renderList(switches, (item) => {
            return _createElementVNode("label", {
              key: item.key,
              class: _normalizeClass(["sq-switch", {'sq-switch-active': config[item.key]}]),
              style: _normalizeStyle({'--sq-accent': item.accent})
            }, [
              _createElementVNode("div", null, [
                _createVNode(_component_v_icon, {
                  icon: item.icon,
                  size: "20"
                }, null, 8, ["icon"]),
                _createElementVNode("span", null, [
                  _createElementVNode("strong", null, _toDisplayString(item.label), 1),
                  _createElementVNode("small", null, _toDisplayString(item.description), 1)
                ])
              ]),
              _createVNode(_component_v_switch, {
                modelValue: config[item.key],
                "onUpdate:modelValue": $event => ((config[item.key]) = $event),
                color: item.color,
                "aria-label": item.label,
                disabled: !loaded.value || saving.value,
                density: "compact",
                "hide-details": ""
              }, null, 8, ["modelValue", "onUpdate:modelValue", "color", "aria-label", "disabled"])
            ], 6)
          }), 64))
        ])
      ]),
      _createElementVNode("div", _hoisted_10, [
        _createElementVNode("section", _hoisted_11, [
          _createElementVNode("div", _hoisted_12, [
            _createElementVNode("h3", null, [
              _createVNode(_component_v_icon, {
                icon: "mdi-trash-can-outline",
                size: "18",
                color: "#27865d"
              }),
              _cache[16] || (_cache[16] = _createTextVNode("沙滩清理", -1))
            ])
          ]),
          _createElementVNode("div", _hoisted_13, [
            _createVNode(_component_v_select, {
              modelValue: config.schedule_mode,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.schedule_mode) = $event)),
              items: modes,
              label: "定时模式",
              density: "compact",
              variant: "outlined",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            (config.schedule_mode === 'auto')
              ? (_openBlock(), _createElementBlock("p", _hoisted_14, "按两小时冷却自动安排，到期后约 15 秒执行；等待期间不访问站点。"))
              : _createCommentVNode("", true),
            (config.schedule_mode === 'cron')
              ? (_openBlock(), _createBlock(_component_v_text_field, {
                  key: 1,
                  modelValue: config.cron,
                  "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.cron) = $event)),
                  label: "清理 Cron 表达式",
                  placeholder: "5 */2 * * *",
                  density: "compact",
                  variant: "outlined",
                  hint: "例如 5 */2 * * *，每两小时的第 5 分钟",
                  "persistent-hint": ""
                }, null, 8, ["modelValue"]))
              : _createCommentVNode("", true),
            (config.schedule_mode === 'interval')
              ? (_openBlock(), _createBlock(_component_v_text_field, {
                  key: 2,
                  modelValue: config.interval_minutes,
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.interval_minutes) = $event)),
                  modelModifiers: { number: true },
                  label: "执行间隔（分钟）",
                  type: "number",
                  min: "1",
                  density: "compact",
                  variant: "outlined",
                  hint: "兼容旧版配置，推荐使用按站点冷却",
                  "persistent-hint": ""
                }, null, 8, ["modelValue"]))
              : _createCommentVNode("", true)
          ])
        ]),
        _createElementVNode("section", _hoisted_15, [
          _createElementVNode("div", _hoisted_16, [
            _createElementVNode("h3", null, [
              _createVNode(_component_v_icon, {
                icon: "mdi-wall",
                size: "18",
                color: "#b66b2a"
              }),
              _cache[17] || (_cache[17] = _createTextVNode("每日搬砖", -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_brick,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.auto_brick) = $event)),
              color: "#b66b2a",
              "aria-label": "自动搬砖",
              disabled: !loaded.value || saving.value,
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue", "disabled"])
          ]),
          _createElementVNode("div", _hoisted_17, [
            _createVNode(_component_v_text_field, {
              modelValue: config.brick_cron,
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.brick_cron) = $event)),
              disabled: !config.auto_brick,
              label: "搬砖独立 Cron（可选）",
              placeholder: "0 10,16 * * *",
              clearable: "",
              density: "compact",
              variant: "outlined",
              hint: "留空沿用原调度；示例为每天 10 点、16 点",
              "persistent-hint": ""
            }, null, 8, ["modelValue", "disabled"]),
            _createVNode(_component_v_text_field, {
              modelValue: config.brick_retry_limit,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.brick_retry_limit) = $event)),
              modelModifiers: { number: true },
              disabled: !config.auto_brick,
              label: "失败重试次数",
              type: "number",
              min: "0",
              max: "10",
              density: "compact",
              variant: "outlined",
              hint: "默认 1 次，0 关闭；写入结果不确定时不重发",
              "persistent-hint": ""
            }, null, 8, ["modelValue", "disabled"]),
            _cache[18] || (_cache[18] = _createElementVNode("p", { class: "sq-hint" }, "每日上限 50 块，按服务端零点重置。Cron 使用 MoviePilot 时区。", -1))
          ])
        ])
      ]),
      _createElementVNode("section", _hoisted_18, [
        _createElementVNode("div", _hoisted_19, [
          _createElementVNode("h3", null, [
            _createVNode(_component_v_icon, {
              icon: "mdi-cookie-outline",
              size: "18",
              color: "#9b680a"
            }),
            _cache[19] || (_cache[19] = _createTextVNode("站点连接", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_20, [
          _createVNode(_component_v_text_field, {
            modelValue: config.cookie,
            "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.cookie) = $event)),
            type: showCookie.value ? 'text' : 'password',
            label: "思齐 Cookie",
            autocomplete: "off",
            density: "compact",
            variant: "outlined",
            "append-inner-icon": showCookie.value ? 'mdi-eye-off-outline' : 'mdi-eye-outline',
            "onClick:appendInner": _cache[10] || (_cache[10] = $event => (showCookie.value = !showCookie.value)),
            hint: "留空自动读取 MoviePilot 站点管理中的思齐 Cookie",
            "persistent-hint": ""
          }, null, 8, ["modelValue", "type", "append-inner-icon"]),
          _cache[20] || (_cache[20] = _createElementVNode("p", { class: "sq-hint" }, "保存后立即运行仅执行一次，随后自动关闭。", -1))
        ])
      ])
    ], 8, _hoisted_6),
    _createElementVNode("footer", _hoisted_21, [
      _cache[22] || (_cache[22] = _createElementVNode("span", null, "v2.5.0 · xchenya", -1)),
      _createVNode(_component_v_btn, {
        variant: "text",
        size: "small",
        disabled: !loaded.value || saving.value,
        loading: saving.value,
        onClick: saveConfig
      }, {
        default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
          _createTextVNode("保存配置", -1)
        ]))]),
        _: 1
      }, 8, ["disabled", "loading"])
    ])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-33c4a3f6"]]);

export { Config as default };

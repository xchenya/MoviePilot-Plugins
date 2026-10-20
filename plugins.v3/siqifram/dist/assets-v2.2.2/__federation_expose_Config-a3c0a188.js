import { importShared } from './__federation_fn_import-054b33c3.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-c4c0bc37.js';

const Config_vue_vue_type_style_index_0_scoped_4cf38228_lang = '';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,createElementBlock:_createElementBlock,normalizeProps:_normalizeProps,guardReactiveProps:_guardReactiveProps,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "siqi-config" };
const _hoisted_2 = { class: "siqi-topbar" };
const _hoisted_3 = { class: "siqi-topbar__left" };
const _hoisted_4 = { class: "siqi-topbar__icon" };
const _hoisted_5 = { class: "siqi-topbar__right" };
const _hoisted_6 = { class: "siqi-config-col" };
const _hoisted_7 = { class: "siqi-card" };
const _hoisted_8 = { class: "siqi-card__header" };
const _hoisted_9 = { class: "siqi-card__title d-flex align-center" };
const _hoisted_10 = { class: "siqi-switch-grid" };
const _hoisted_11 = { class: "siqi-switch-main" };
const _hoisted_12 = { class: "siqi-switch-main" };
const _hoisted_13 = { class: "siqi-switch-main" };
const _hoisted_14 = { class: "siqi-switch-main" };
const _hoisted_15 = { class: "siqi-switch-desc" };
const _hoisted_16 = { class: "siqi-schedule-card siqi-schedule-card--delay" };
const _hoisted_17 = { class: "siqi-schedule-card__head" };
const _hoisted_18 = { class: "siqi-schedule-card siqi-schedule-card--cron" };
const _hoisted_19 = { class: "siqi-schedule-card__head" };
const _hoisted_20 = { class: "siqi-card" };
const _hoisted_21 = { class: "siqi-card__header" };
const _hoisted_22 = { class: "siqi-card__title d-flex align-center" };
const _hoisted_23 = { class: "siqi-switch-grid" };
const _hoisted_24 = { class: "siqi-switch-main" };
const _hoisted_25 = { class: "siqi-switch-main" };
const _hoisted_26 = { class: "siqi-switch-main" };
const _hoisted_27 = { class: "siqi-switch-main" };
const _hoisted_28 = { class: "siqi-card" };
const _hoisted_29 = { class: "siqi-card__header" };
const _hoisted_30 = { class: "siqi-card__title d-flex align-center" };
const _hoisted_31 = { class: "siqi-form-grid" };
const _hoisted_32 = {
  key: 0,
  class: "text-error"
};
const _hoisted_33 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_34 = { class: "d-flex align-center flex-wrap ga-2" };
const _hoisted_35 = {
  class: "text-caption text-medium-emphasis",
  role: "status",
  "aria-live": "polite"
};
const _hoisted_36 = {
  key: 0,
  class: "d-flex align-center ga-2",
  role: "alert"
};
const _hoisted_37 = { class: "text-error" };
const _hoisted_38 = { class: "siqi-card" };
const _hoisted_39 = { class: "siqi-card__header" };
const _hoisted_40 = { class: "siqi-card__title d-flex align-center" };
const _hoisted_41 = { class: "siqi-schedule-card siqi-schedule-card--cron" };
const _hoisted_42 = { class: "siqi-schedule-card__head" };
const _hoisted_43 = { class: "d-flex align-center flex-wrap ga-2" };

const {reactive,ref,onMounted} = await importShared('vue');



const _sfc_main = {
  __name: 'Config',
  props: { api: Object, pluginId: { type: String, default: 'SiqiFram' }, initialConfig: { type: Object, default: () => ({}) } },
  emits: ['switch', 'close', 'config-updated'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const stealCropOptions = ['萝卜', '西红柿', '玉米', '茄子', '蘑菇', '樱桃'];
const { auto_steal, steal_crops, steal_cron, ...initialPlantConfig } = props.initialConfig;
const config = reactive({ enabled: false, notify: true, cron: '5 */4 * * *', cookie: '', seed_id: '1', auto_plant: true, auto_harvest: true, auto_sell: false, auto_like: false, use_proxy: false, use_ai_captcha: false, harvest_delay_minutes: 2, retry_count: 2, retry_interval: 3, ...initialPlantConfig });
const stealConfig = reactive({ auto_steal: !!auto_steal, steal_crops: Array.isArray(steal_crops) ? [...steal_crops] : [...stealCropOptions], steal_cron: steal_cron ?? '*/15 * * * *' });
const loading = ref(false);
const saving = ref(false);
const configLoaded = ref(false);
const stealLoaded = ref(false);
const stealSaving = ref(false);
const stealStatus = ref('');
const stealStatusType = ref('info');
const seedLoading = ref(false);
const seedCached = ref(false);
const seedError = ref('');
const showCookie = ref(false);
const aiAvailable = ref(false);
const seedOptions = ref([]);
const message = ref('');
const messageType = ref('success');
let messageTimer = null;
let loadedCookie = '';

const apiGet = (path) => props.api.get(`plugin/${props.pluginId}${path}`);
const apiPost = (path, data) => props.api.post(`plugin/${props.pluginId}${path}`, data);

function show(text, type = 'success') {
  message.value = text;
  messageType.value = type;
  if (messageTimer) clearTimeout(messageTimer);
  messageTimer = setTimeout(() => {
    if (message.value === text) message.value = '';
    messageTimer = null;
  }, 3000);
}

async function loadConfig() {
  loading.value = true;
  try {
    const res = await apiGet('/config');
    const { auto_steal, steal_crops, steal_cron, ...plantConfig } = res;
    Object.assign(config, plantConfig);
    config.seed_id = String(config.seed_id || '1');
    loadedCookie = config.cookie || '';
    aiAvailable.value = !!res.ai_available;
    if (!res.ai_available) config.use_ai_captcha = false;
    configLoaded.value = true;
  } catch (e) {
    show(`加载失败：${e.message}`, 'error');
  } finally {
    loading.value = false;
  }
}

async function loadSeeds(refresh = false) {
  if (seedLoading.value) return
  seedLoading.value = true;
  seedError.value = '';
  try {
    let res = await apiGet(refresh ? '/seeds?refresh=true' : '/seeds');
    if (!refresh && res.needs_refresh) res = await apiGet('/seeds?refresh=true');
    const seeds = Array.isArray(res?.seeds) ? res.seeds : [];
    if (!res.success || !seeds.length) throw new Error(res.message || '种子列表暂不可用')
    seedCached.value = !!res.cached;
    const totalHarvest = Number(res?.user_stats?.total_harvest || 0);
    if (seeds.length) {
      seedOptions.value = seeds.map(seed => ({
        title: `${seed.icon || '🌱'} ${seed.name || `种子 ${seed.id}`}（ID ${seed.id}）`,
        value: String(seed.id),
        locked: totalHarvest < Number(seed.unlock_harvest || 0),
        unlockHarvest: Number(seed.unlock_harvest || 0),
        props: {
          disabled: totalHarvest < Number(seed.unlock_harvest || 0)
        }
      }));
    }
  } catch (e) {
    seedError.value = e.message || '种子列表加载失败';
  } finally {
    seedLoading.value = false;
  }
}

async function saveConfig() {
  if (!configLoaded.value) return show('配置尚未加载成功，请关闭后重新打开', 'error')
  if (seedLoading.value) return show('种子数据读取中，请稍后保存配置', 'info')
  const delay = Number(config.harvest_delay_minutes);
  config.harvest_delay_minutes = Number.isFinite(delay) ? Math.min(30, Math.max(0, Math.trunc(delay))) : 2;
  saving.value = true;
  try {
    const res = await apiPost('/config', { ...config });
    if (res.success && res.config) {
      emit('config-updated', res.config);
      if (loadedCookie !== (res.config.cookie || '')) {
        seedOptions.value = [];
        await loadSeeds();
      }
      loadedCookie = res.config.cookie || '';
    }
    show(res.message || (res.success ? '保存成功' : '保存失败'), res.success ? 'success' : 'error');
  } catch (e) {
    show(`保存失败：${e.message}`, 'error');
  } finally {
    saving.value = false;
  }
}

async function loadStealConfig() {
  try {
    Object.assign(stealConfig, await apiGet('/steal-config'));
    stealLoaded.value = true;
  } catch (e) {
    show(`偷菜配置加载失败：${e.message}`, 'error');
  }
}

async function saveStealConfig(runOnce = false) {
  if (stealSaving.value) return
  if (!stealLoaded.value) return show('偷菜配置尚未加载成功，请关闭后重新打开', 'error')
  stealSaving.value = true;
  stealStatus.value = '正在保存偷菜设置…';
  stealStatusType.value = 'info';
  let saved = false;
  try {
    const res = await apiPost('/steal-config', { auto_steal: stealConfig.auto_steal, steal_crops: [...stealConfig.steal_crops], steal_cron: stealConfig.steal_cron });
    saved = !!res.success;
    if (saved && res.config) Object.assign(stealConfig, res.config);
    stealStatus.value = res.message || (saved ? '偷菜配置已保存' : '偷菜配置保存失败');
    stealStatusType.value = saved ? 'success' : 'error';
    if (saved && runOnce === true) {
      stealStatus.value = '偷菜设置已保存，正在运行一次偷菜…';
      stealStatusType.value = 'info';
      const result = await apiPost('/steal');
      const detail = result.message || result.msg || (result.success ? '偷菜执行完成' : '站点未返回成功结果');
      stealStatus.value = result.uncertain ? `偷菜设置已保存；执行结果不明：${detail}`
        : result.success ? `偷菜设置已保存；${detail}` : `偷菜设置已保存，但运行失败：${detail}`;
      stealStatusType.value = result.success && !result.uncertain ? 'success' : 'error';
    }
    show(stealStatus.value, stealStatusType.value);
  } catch (e) {
    stealStatus.value = saved ? `偷菜设置已保存，但未能确认偷菜执行结果：${e.message}` : `偷菜配置保存失败：${e.message}`;
    stealStatusType.value = 'error';
    show(stealStatus.value, 'error');
  } finally {
    stealSaving.value = false;
  }
}

onMounted(() => {
  loadConfig();
  loadSeeds();
  loadStealConfig();
});

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_btn_group = _resolveComponent("v-btn-group");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_VCronField = _resolveComponent("VCronField");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_textarea = _resolveComponent("v-textarea");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-cog-outline",
            size: "24"
          })
        ]),
        _cache[24] || (_cache[24] = _createElementVNode("div", null, [
          _createElementVNode("div", { class: "siqi-topbar__title" }, "思齐农场 · 配置 · v2.2.2"),
          _createElementVNode("div", { class: "siqi-topbar__sub" }, "管理定时任务、自动化策略与站点 Cookie")
        ], -1))
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_v_btn_group, {
          variant: "tonal",
          density: "compact",
          class: "elevation-0"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_btn, {
              color: "success",
              size: "small",
              "min-width": "40",
              class: "px-0 px-sm-3",
              onClick: _cache[0] || (_cache[0] = $event => (emit('switch', 'page')))
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  icon: "mdi-view-dashboard",
                  size: "18",
                  class: "mr-sm-1"
                }),
                _cache[25] || (_cache[25] = _createElementVNode("span", { class: "d-none d-sm-inline" }, "状态页", -1))
              ]),
              _: 1
            }),
            _createVNode(_component_v_btn, {
              color: "success",
              size: "small",
              "min-width": "40",
              class: "px-0 px-sm-3",
              onClick: saveConfig,
              loading: saving.value,
              disabled: !configLoaded.value || seedLoading.value
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  icon: "mdi-content-save",
                  size: "18",
                  class: "mr-sm-1"
                }),
                _cache[26] || (_cache[26] = _createElementVNode("span", { class: "d-none d-sm-inline" }, "保存", -1))
              ]),
              _: 1
            }, 8, ["loading", "disabled"]),
            _createVNode(_component_v_btn, {
              color: "success",
              size: "small",
              "min-width": "40",
              class: "px-0 px-sm-3",
              onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  icon: "mdi-close",
                  size: "18",
                  class: "mr-sm-1"
                }),
                _cache[27] || (_cache[27] = _createElementVNode("span", { class: "d-none d-sm-inline" }, "关闭", -1))
              ]),
              _: 1
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
          class: "siqi-toast",
          closable: "",
          "onClick:close": _cache[2] || (_cache[2] = $event => (message.value=''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_6, [
      _createElementVNode("div", _hoisted_7, [
        _createElementVNode("div", _hoisted_8, [
          _createElementVNode("span", _hoisted_9, [
            _createVNode(_component_v_icon, {
              icon: "mdi-toggle-switch-outline",
              size: "18",
              color: "#22c55e",
              class: "mr-1"
            }),
            _cache[28] || (_cache[28] = _createTextVNode("基础设置 ", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_10, [
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.enabled}]),
            style: {"--siqi-accent":"34,197,94"}
          }, [
            _createElementVNode("div", _hoisted_11, [
              _createVNode(_component_v_icon, {
                icon: "mdi-power-plug",
                size: "18"
              }),
              _cache[29] || (_cache[29] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "启用插件"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "开启定时任务与页面功能")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.enabled,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.enabled) = $event)),
              color: "green",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.notify}]),
            style: {"--siqi-accent":"59,130,246"}
          }, [
            _createElementVNode("div", _hoisted_12, [
              _createVNode(_component_v_icon, {
                icon: "mdi-bell-outline",
                size: "18"
              }),
              _cache[30] || (_cache[30] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "开启通知"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "任务完成后发送站内通知")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.notify,
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.notify) = $event)),
              color: "blue",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.use_proxy}]),
            style: {"--siqi-accent":"139,92,246"}
          }, [
            _createElementVNode("div", _hoisted_13, [
              _createVNode(_component_v_icon, {
                icon: "mdi-lan-connect",
                size: "18"
              }),
              _cache[31] || (_cache[31] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "使用代理"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "请求站点时使用系统代理")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.use_proxy,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.use_proxy) = $event)),
              color: "purple",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.use_ai_captcha && aiAvailable.value}]),
            style: {"--siqi-accent":"99,102,241"}
          }, [
            _createElementVNode("div", _hoisted_14, [
              _createVNode(_component_v_icon, {
                icon: "mdi-robot",
                size: "18"
              }),
              _createElementVNode("div", null, [
                _cache[32] || (_cache[32] = _createElementVNode("div", { class: "siqi-switch-label" }, "AI辅助验证码识别", -1)),
                _createElementVNode("div", _hoisted_15, _toDisplayString(aiAvailable.value ? '基础识别失败后使用AI智能助手识别验证码重试一键收获' : '未检测到AI智能助手配置（需启用MP智能助手）'), 1)
              ])
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.use_ai_captcha,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.use_ai_captcha) = $event)),
              color: "indigo",
              "hide-details": "",
              density: "compact",
              disabled: !aiAvailable.value
            }, null, 8, ["modelValue", "disabled"])
          ], 2),
          _createElementVNode("div", _hoisted_16, [
            _createElementVNode("div", _hoisted_17, [
              _createVNode(_component_v_icon, {
                icon: "mdi-timer-outline",
                size: "17"
              }),
              _cache[33] || (_cache[33] = _createElementVNode("span", null, "收获执行延迟（分钟）(0-30，默认 2)", -1))
            ]),
            _createVNode(_component_v_text_field, {
              modelValue: config.harvest_delay_minutes,
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.harvest_delay_minutes) = $event)),
              modelModifiers: { number: true },
              type: "number",
              min: "0",
              max: "30",
              density: "compact",
              variant: "outlined",
              class: "siqi-input siqi-harvest-delay-field"
            }, null, 8, ["modelValue"])
          ]),
          _createElementVNode("div", _hoisted_18, [
            _createElementVNode("div", _hoisted_19, [
              _createVNode(_component_v_icon, {
                icon: "mdi-calendar-clock-outline",
                size: "17"
              }),
              _cache[34] || (_cache[34] = _createElementVNode("span", null, "Cron 兜底巡检 (例如：5 */4 * * *)", -1))
            ]),
            _createVNode(_component_VCronField, {
              modelValue: config.cron,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.cron) = $event)),
              density: "compact",
              class: "siqi-input siqi-cron-field"
            }, null, 8, ["modelValue"])
          ])
        ])
      ]),
      _createElementVNode("div", _hoisted_20, [
        _createElementVNode("div", _hoisted_21, [
          _createElementVNode("span", _hoisted_22, [
            _createVNode(_component_v_icon, {
              icon: "mdi-robot-outline",
              size: "18",
              color: "#f59e0b",
              class: "mr-1"
            }),
            _cache[35] || (_cache[35] = _createTextVNode("自动化策略 ", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_23, [
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.auto_harvest}]),
            style: {"--siqi-accent":"245,158,11"}
          }, [
            _createElementVNode("div", _hoisted_24, [
              _createVNode(_component_v_icon, {
                icon: "mdi-basket-fill",
                size: "18"
              }),
              _cache[36] || (_cache[36] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "自动收获"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "收获成熟作物")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_harvest,
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.auto_harvest) = $event)),
              color: "orange",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.auto_plant}]),
            style: {"--siqi-accent":"34,197,94"}
          }, [
            _createElementVNode("div", _hoisted_25, [
              _createVNode(_component_v_icon, {
                icon: "mdi-seed",
                size: "18"
              }),
              _cache[37] || (_cache[37] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "自动补种"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "为空地补种默认种子")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_plant,
              "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.auto_plant) = $event)),
              color: "green",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.auto_like}]),
            style: {"--siqi-accent":"236,72,153"}
          }, [
            _createElementVNode("div", _hoisted_26, [
              _createVNode(_component_v_icon, {
                icon: "mdi-thumb-up-outline",
                size: "18"
              }),
              _cache[38] || (_cache[38] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "自动点赞"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "随机批量点赞农场")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_like,
              "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.auto_like) = $event)),
              color: "pink",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2),
          _createElementVNode("div", {
            class: _normalizeClass(["siqi-switch-item", {'siqi-switch-item--active': config.auto_sell}]),
            style: {"--siqi-accent":"14,165,233"}
          }, [
            _createElementVNode("div", _hoisted_27, [
              _createVNode(_component_v_icon, {
                icon: "mdi-cash-sync",
                size: "18"
              }),
              _cache[39] || (_cache[39] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "siqi-switch-label" }, "自动出售"),
                _createElementVNode("div", { class: "siqi-switch-desc" }, "出售收获背包库存")
              ], -1))
            ]),
            _createVNode(_component_v_switch, {
              modelValue: config.auto_sell,
              "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.auto_sell) = $event)),
              color: "info",
              "hide-details": "",
              density: "compact"
            }, null, 8, ["modelValue"])
          ], 2)
        ])
      ]),
      _createElementVNode("div", _hoisted_28, [
        _createElementVNode("div", _hoisted_29, [
          _createElementVNode("span", _hoisted_30, [
            _createVNode(_component_v_icon, {
              icon: "mdi-tune-variant",
              size: "18",
              color: "#0ea5e9",
              class: "mr-1"
            }),
            _cache[40] || (_cache[40] = _createTextVNode("参数设置 ", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_31, [
          _createVNode(_component_v_select, {
            modelValue: config.seed_id,
            "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.seed_id) = $event)),
            items: seedOptions.value,
            label: "默认种子",
            density: "compact",
            variant: "outlined",
            "hide-details": "",
            class: "siqi-input seed-select",
            "prepend-inner-icon": "mdi-sprout",
            loading: seedLoading.value
          }, {
            item: _withCtx(({ props: itemProps, item }) => [
              _createVNode(_component_v_list_item, _normalizeProps(_guardReactiveProps(itemProps)), {
                subtitle: _withCtx(() => [
                  (item.raw.locked)
                    ? (_openBlock(), _createElementBlock("span", _hoisted_32, "未解锁：需总收获 " + _toDisplayString(item.raw.unlockHarvest), 1))
                    : (_openBlock(), _createElementBlock("span", _hoisted_33, "已解锁"))
                ]),
                _: 2
              }, 1040)
            ]),
            _: 1
          }, 8, ["modelValue", "items", "loading"]),
          _createVNode(_component_v_text_field, {
            modelValue: config.retry_count,
            "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.retry_count) = $event)),
            modelModifiers: { number: true },
            label: "读取重试次数",
            type: "number",
            density: "compact",
            variant: "outlined",
            "hide-details": "",
            class: "siqi-input",
            "prepend-inner-icon": "mdi-reload"
          }, null, 8, ["modelValue"]),
          _createVNode(_component_v_text_field, {
            modelValue: config.retry_interval,
            "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.retry_interval) = $event)),
            modelModifiers: { number: true },
            label: "读取重试间隔（秒）",
            type: "number",
            density: "compact",
            variant: "outlined",
            "hide-details": "",
            class: "siqi-input",
            "prepend-inner-icon": "mdi-timer-sand"
          }, null, 8, ["modelValue"])
        ]),
        _cache[42] || (_cache[42] = _createElementVNode("div", { class: "siqi-field-hint" }, "默认种子用于自动补种空地；下拉列表来自站点种子商店，建议选择已解锁种子。", -1)),
        _createElementVNode("div", _hoisted_34, [
          _createElementVNode("span", _hoisted_35, _toDisplayString(seedLoading.value ? '种子数据读取中…' : seedOptions.value.length ? (seedCached.value ? '已显示缓存种子列表，解锁状态变化后可刷新。' : '已读取最新种子列表。') : '暂无种子列表。'), 1),
          _createVNode(_component_v_btn, {
            size: "small",
            variant: "text",
            onClick: _cache[16] || (_cache[16] = $event => (loadSeeds(true))),
            loading: seedLoading.value,
            disabled: seedLoading.value || saving.value
          }, {
            default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
              _createTextVNode("刷新种子列表", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"])
        ]),
        (seedError.value)
          ? (_openBlock(), _createElementBlock("div", _hoisted_36, [
              _createElementVNode("span", _hoisted_37, _toDisplayString(seedError.value) + "；当前默认种子保持不变。", 1)
            ]))
          : _createCommentVNode("", true),
        _createVNode(_component_v_textarea, {
          modelValue: config.cookie,
          "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.cookie) = $event)),
          label: "Cookie（留空时尝试读取站点cookie）",
          rows: "2",
          "auto-grow": "",
          variant: "outlined",
          class: _normalizeClass(["siqi-input mt-3", {'siqi-secret-input': !showCookie.value}]),
          "prepend-inner-icon": "mdi-cookie",
          autocomplete: "off"
        }, {
          "append-inner": _withCtx(() => [
            _createVNode(_component_v_btn, {
              variant: "text",
              density: "comfortable",
              size: "x-small",
              icon: "",
              class: "siqi-secret-toggle",
              onClick: _cache[17] || (_cache[17] = _withModifiers($event => (showCookie.value = !showCookie.value), ["stop"]))
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_icon, {
                  icon: showCookie.value ? 'mdi-eye-off-outline' : 'mdi-eye-outline',
                  size: "18"
                }, null, 8, ["icon"])
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue", "class"])
      ]),
      _createElementVNode("div", _hoisted_38, [
        _createElementVNode("div", _hoisted_39, [
          _createElementVNode("span", _hoisted_40, [
            _createVNode(_component_v_icon, {
              icon: "mdi-incognito",
              size: "18",
              color: "red",
              class: "mr-1"
            }),
            _cache[43] || (_cache[43] = _createTextVNode("偷菜设置 ", -1))
          ]),
          _createVNode(_component_v_btn, {
            color: "red",
            size: "small",
            variant: "tonal",
            onClick: _cache[19] || (_cache[19] = $event => (saveStealConfig())),
            loading: stealSaving.value,
            disabled: !stealLoaded.value || stealSaving.value
          }, {
            default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
              _createTextVNode("保存偷菜设置", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"])
        ]),
        _createVNode(_component_v_switch, {
          modelValue: stealConfig.auto_steal,
          "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((stealConfig.auto_steal) = $event)),
          label: "自动偷菜",
          color: "red",
          "hide-details": "",
          density: "compact"
        }, null, 8, ["modelValue"]),
        _createElementVNode("div", _hoisted_41, [
          _createElementVNode("div", _hoisted_42, [
            _createVNode(_component_v_icon, {
              icon: "mdi-calendar-clock-outline",
              size: "17"
            }),
            _cache[45] || (_cache[45] = _createElementVNode("span", null, "偷菜巡检 Cron（默认每15分钟）", -1))
          ]),
          _createVNode(_component_VCronField, {
            modelValue: stealConfig.steal_cron,
            "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((stealConfig.steal_cron) = $event)),
            density: "compact",
            class: "siqi-input siqi-cron-field"
          }, null, 8, ["modelValue"])
        ]),
        _createVNode(_component_v_select, {
          modelValue: stealConfig.steal_crops,
          "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((stealConfig.steal_crops) = $event)),
          items: stealCropOptions,
          label: "允许偷取的作物",
          multiple: "",
          chips: "",
          "closable-chips": "",
          density: "compact",
          variant: "outlined",
          "hide-details": "",
          class: "siqi-input"
        }, null, 8, ["modelValue"]),
        _cache[48] || (_cache[48] = _createElementVNode("div", { class: "siqi-field-hint" }, "偷菜巡检只检查所选作物，按站点当日剩余可偷数量执行，与总 Cron 和成熟收获任务独立。当日可偷数量用完后暂停巡检，次日 0 点恢复（MoviePilot 配置时区）。只影响偷菜，不改变默认种子或种子解锁列表；全部取消则不偷菜。", -1)),
        _createElementVNode("div", _hoisted_43, [
          _createVNode(_component_v_btn, {
            color: "red",
            size: "small",
            variant: "tonal",
            onClick: _cache[23] || (_cache[23] = $event => (saveStealConfig(true))),
            loading: stealSaving.value,
            disabled: !stealLoaded.value || stealSaving.value
          }, {
            default: _withCtx(() => [...(_cache[46] || (_cache[46] = [
              _createTextVNode("保存后运行一次偷菜", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"]),
          _cache[47] || (_cache[47] = _createElementVNode("span", { class: "text-caption text-medium-emphasis" }, "自动偷菜关闭时也可手动运行；仅保存偷菜设置并执行偷菜。", -1))
        ]),
        (stealStatus.value)
          ? (_openBlock(), _createElementBlock("div", {
              key: 0,
              class: _normalizeClass(["text-caption", {'text-error': stealStatusType.value === 'error'}]),
              role: "status",
              "aria-live": "polite"
            }, _toDisplayString(stealStatus.value), 3))
          : _createCommentVNode("", true)
      ])
    ])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-4cf38228"]]);

export { Config as default };

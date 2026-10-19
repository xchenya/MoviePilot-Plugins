import { importShared } from './__federation_fn_import-054b33c3.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-c4c0bc37.js';

const style_css_vue_type_style_index_0_src_8cf0ec68_scoped_8cf0ec68_lang = '';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,normalizeStyle:_normalizeStyle} = await importShared('vue');


const _hoisted_1 = {
  class: "sq-app",
  "aria-label": "思齐收垃圾"
};
const _hoisted_2 = { class: "sq-topbar" };
const _hoisted_3 = { class: "sq-heading" };
const _hoisted_4 = { class: "sq-brand" };
const _hoisted_5 = { class: "sq-actions" };
const _hoisted_6 = { class: "sq-stats" };
const _hoisted_7 = { class: "sq-stat-icon" };
const _hoisted_8 = { class: "sq-card" };
const _hoisted_9 = { class: "sq-card-heading" };
const _hoisted_10 = { class: "sq-task-grid" };
const _hoisted_11 = { class: "sq-task" };
const _hoisted_12 = { class: "sq-task-heading" };
const _hoisted_13 = { class: "sq-result" };
const _hoisted_14 = { class: "sq-next" };
const _hoisted_15 = { class: "sq-task" };
const _hoisted_16 = { class: "sq-task-heading" };
const _hoisted_17 = { class: "sq-result" };
const _hoisted_18 = { class: "sq-next" };
const _hoisted_19 = { class: "sq-card" };
const _hoisted_20 = {
  key: 0,
  class: "sq-card-body"
};
const _hoisted_21 = { class: "sq-hint sq-stock-note" };
const _hoisted_22 = {
  key: 0,
  class: "sq-inventory"
};
const _hoisted_23 = {
  key: 1,
  class: "sq-empty"
};
const _hoisted_24 = {
  key: 1,
  class: "sq-history"
};
const _hoisted_25 = { class: "sq-time" };
const _hoisted_26 = {
  key: 0,
  class: "sq-empty"
};
const _hoisted_27 = { class: "sq-footer" };

const {computed,onMounted,onUnmounted,ref} = await importShared('vue');



const _sfc_main = {
  __name: 'Page',
  props: { api: Object, pluginId: { type: String, default: 'SiQiCleanBeach' } },
  emits: ['switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const data = ref({ stats: {}, inventory: {}, display: {} });
const loading = ref(false);
const loaded = ref(false);
const starting = ref(false);
const message = ref('');
const messageType = ref('info');
const tab = ref('inventory');
const view = computed(() => data.value.display || {});
const stats = computed(() => data.value.stats || {});
const inventory = computed(() => data.value.inventory || {});
const items = computed(() => Object.entries(inventory.value).map(([name, item]) => ({ name, count: item.count || 0 })).sort((a, b) => b.count - a.count));
const history = computed(() => [...(stats.value.history || [])].slice(-20).reverse());
const metrics = computed(() => [
  { label: '物品总数', value: number(items.value.reduce((sum, item) => sum + item.count, 0)), icon: 'mdi-package-variant-closed', accent: '39,134,93' },
  { label: '物品种类', value: number(items.value.length), icon: 'mdi-shape-outline', accent: '65,115,193' },
  { label: '今日搬砖', value: `${view.value.daily_bricks ?? '—'} / 50`, icon: 'mdi-wall', accent: '182,107,42' },
  { label: '砖块库存', value: inventory.value['砖块'] ? number(inventory.value['砖块'].count) : '—', icon: 'mdi-cube-outline', accent: '139,91,171' },
]);
const stockNote = computed(() => !stats.value.last_update ? '等待首次库存同步' : `库存更新于 ${formatTime(stats.value.last_update)} · ${stats.value.inventory_refreshed ? '最近一轮已刷新' : '缓存，最近一轮未刷新'}`);
const apiGet = (path) => props.api.get(`plugin/${props.pluginId}${path}`);
const apiPost = (path, payload) => props.api.post(`plugin/${props.pluginId}${path}`, payload);
const number = (value) => Number(value || 0).toLocaleString('zh-CN');
function formatTime(value) {
  if (!value) return '—'
  const date = new Date(Number(value) * 1000);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('sv-SE', { timeZone: view.value.timezone || 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function itemIcon(name) {
  return ({ '砖块': 'mdi-wall', '木材': 'mdi-tree-outline', '塑料袋': 'mdi-shopping-outline', '瓶子': 'mdi-bottle-soda-outline', '螺丝': 'mdi-screw-flat-top', '旧电池': 'mdi-battery-outline', '破铜片': 'mdi-circle-multiple-outline', '木工件': 'mdi-hand-saw', '塑料件': 'mdi-pail-outline', '简易工具': 'mdi-tools', '能量碎片': 'mdi-lightning-bolt-outline', '魔丸胚胎': 'mdi-egg-outline', '魔丸': 'mdi-flask-outline', '蚯蚓': 'mdi-bug-outline' })[name] || 'mdi-package-variant'
}
function status(value) {
  return ({ completed: { label: '全部完成', color: '#27865d' }, partial: { label: '部分完成', color: '#9b680a' }, auth_failed: { label: '认证失败', color: '#bb3939' }, error: { label: '执行失败', color: '#bb3939' } })[value] || { label: '待核对', color: '#9b680a' }
}
let timer;
let disposed = false;
function scheduleRefresh() {
  clearTimeout(timer);
  if (!disposed && view.value.running && !document.hidden) timer = setTimeout(refresh, 3000);
}
async function refresh() {
  if (loading.value || disposed) return
  loading.value = true;
  try {
    const result = await apiGet('/stats');
    if (!result?.success || !result.data?.stats || !result.data?.inventory) throw new Error('invalid response')
    data.value = result.data;
    loaded.value = true;
  } catch {
    message.value = '读取面板失败，请稍后点击刷新。';
    messageType.value = 'error';
  } finally {
    loading.value = false;
    scheduleRefresh();
  }
}
async function runOnce() {
  if (starting.value || view.value.running || !loaded.value) return
  starting.value = true;
  try {
    const result = await apiPost('/run');
    message.value = result?.message || '请刷新查看任务状态';
    messageType.value = result?.success ? 'info' : 'warning';
  } catch {
    message.value = '运行请求未能确认，请刷新核对任务状态。';
    messageType.value = 'warning';
  } finally {
    starting.value = false;
    await refresh();
  }
}
function visibilityChanged() {
  clearTimeout(timer);
  if (!document.hidden) refresh();
}
onMounted(() => { refresh(); document.addEventListener('visibilitychange', visibilityChanged); });
onUnmounted(() => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibilityChanged); });

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_table = _resolveComponent("v-table");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-beach",
            size: "24"
          })
        ]),
        _createElementVNode("div", null, [
          _createElementVNode("h2", null, [
            _cache[4] || (_cache[4] = _createTextVNode("思齐收垃圾 ", -1)),
            _createVNode(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: view.value.enabled ? '#27865d' : undefined
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(view.value.enabled ? '已启用' : '已暂停'), 1)
              ]),
              _: 1
            }, 8, ["color"])
          ]),
          _cache[5] || (_cache[5] = _createElementVNode("p", null, "沙滩清理与每日搬砖", -1))
        ])
      ]),
      _createElementVNode("div", _hoisted_5, [
        _createVNode(_component_v_btn, {
          variant: "tonal",
          size: "small",
          "aria-label": "刷新面板",
          title: "刷新面板（读取插件缓存）",
          loading: loading.value,
          onClick: refresh
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              icon: "mdi-refresh",
              size: "18"
            }),
            _cache[6] || (_cache[6] = _createElementVNode("span", { class: "sq-button-label" }, "刷新", -1))
          ]),
          _: 1
        }, 8, ["loading"]),
        _createVNode(_component_v_btn, {
          variant: "tonal",
          size: "small",
          "aria-label": "配置",
          onClick: _cache[0] || (_cache[0] = $event => (emit('switch', 'config')))
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_icon, {
              icon: "mdi-cog-outline",
              size: "18"
            }),
            _cache[7] || (_cache[7] = _createElementVNode("span", { class: "sq-button-label" }, "配置", -1))
          ]),
          _: 1
        }),
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
          variant: "tonal",
          density: "compact",
          closable: "",
          role: "status",
          "onClick:close": _cache[2] || (_cache[2] = $event => (message.value = ''))
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    (view.value.auth_blocked)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: "warning",
          variant: "tonal",
          density: "compact"
        }, {
          default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
            _createTextVNode("Cookie 已失效，自动任务已暂停。请更新配置后再运行。", -1)
          ]))]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (loading.value && !loaded.value)
      ? (_openBlock(), _createBlock(_component_v_progress_linear, {
          key: 2,
          indeterminate: "",
          color: "#27865d",
          "aria-label": "读取面板"
        }))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_6, [
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(metrics.value, (item) => {
        return (_openBlock(), _createElementBlock("article", {
          key: item.label,
          class: "sq-stat",
          style: _normalizeStyle({'--sq-accent': item.accent})
        }, [
          _createElementVNode("div", _hoisted_7, [
            _createVNode(_component_v_icon, {
              icon: item.icon,
              size: "22"
            }, null, 8, ["icon"])
          ]),
          _createElementVNode("div", null, [
            _createElementVNode("p", null, _toDisplayString(item.label), 1),
            _createElementVNode("strong", null, _toDisplayString(loaded.value ? item.value : '—'), 1)
          ])
        ], 4))
      }), 128))
    ]),
    _createElementVNode("section", _hoisted_8, [
      _createElementVNode("div", _hoisted_9, [
        _createElementVNode("h3", null, [
          _createVNode(_component_v_icon, {
            icon: "mdi-calendar-clock-outline",
            size: "18"
          }),
          _cache[9] || (_cache[9] = _createTextVNode("任务状态", -1))
        ]),
        _createVNode(_component_v_btn, {
          color: "#27865d",
          variant: "tonal",
          size: "small",
          loading: starting.value || view.value.running,
          disabled: !loaded.value || starting.value || view.value.running,
          "prepend-icon": "mdi-play",
          onClick: runOnce
        }, {
          default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
            _createTextVNode("运行一次", -1)
          ]))]),
          _: 1
        }, 8, ["loading", "disabled"])
      ]),
      _createElementVNode("div", _hoisted_10, [
        _createElementVNode("article", _hoisted_11, [
          _createElementVNode("div", _hoisted_12, [
            _createVNode(_component_v_icon, {
              icon: "mdi-trash-can-outline",
              color: "#27865d",
              size: "20"
            }),
            _cache[11] || (_cache[11] = _createElementVNode("h4", null, "沙滩清理", -1)),
            _createVNode(_component_v_chip, {
              size: "x-small",
              variant: "tonal"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(view.value.schedule || '读取中'), 1)
              ]),
              _: 1
            })
          ]),
          _createElementVNode("p", _hoisted_13, _toDisplayString(stats.value.clean_result || '暂无执行记录'), 1),
          _createElementVNode("div", _hoisted_14, [
            _cache[12] || (_cache[12] = _createElementVNode("span", null, "下次执行时间", -1)),
            _createElementVNode("strong", null, _toDisplayString(view.value.beach_next || '—'), 1)
          ])
        ]),
        _createElementVNode("article", _hoisted_15, [
          _createElementVNode("div", _hoisted_16, [
            _createVNode(_component_v_icon, {
              icon: "mdi-wall",
              color: "#b66b2a",
              size: "20"
            }),
            _cache[13] || (_cache[13] = _createElementVNode("h4", null, "每日搬砖", -1)),
            _createVNode(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: view.value.auto_brick ? '#b66b2a' : undefined
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(view.value.auto_brick ? '已开启' : '未开启'), 1)
              ]),
              _: 1
            }, 8, ["color"])
          ]),
          _createElementVNode("p", _hoisted_17, _toDisplayString(view.value.brick_today_result || '今日暂无成功搬砖记录'), 1),
          _createElementVNode("div", _hoisted_18, [
            _cache[14] || (_cache[14] = _createElementVNode("span", null, "下次执行时间", -1)),
            _createElementVNode("strong", null, _toDisplayString(view.value.brick_next || '—'), 1)
          ])
        ])
      ])
    ]),
    _createElementVNode("section", _hoisted_19, [
      _createVNode(_component_v_tabs, {
        modelValue: tab.value,
        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((tab).value = $event)),
        color: "#27865d",
        density: "compact",
        class: "sq-tabs"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_v_tab, { value: "inventory" }, {
            default: _withCtx(() => [
              _createVNode(_component_v_icon, {
                icon: "mdi-package-variant-closed",
                size: "18",
                class: "mr-2"
              }),
              _cache[15] || (_cache[15] = _createTextVNode("物品库存", -1))
            ]),
            _: 1
          }),
          _createVNode(_component_v_tab, { value: "history" }, {
            default: _withCtx(() => [
              _createVNode(_component_v_icon, {
                icon: "mdi-history",
                size: "18",
                class: "mr-2"
              }),
              _cache[16] || (_cache[16] = _createTextVNode("执行记录", -1))
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"]),
      (tab.value === 'inventory')
        ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
            _createElementVNode("p", _hoisted_21, _toDisplayString(stockNote.value), 1),
            (items.value.length)
              ? (_openBlock(), _createElementBlock("div", _hoisted_22, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(items.value, (item) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: item.name,
                      class: "sq-item"
                    }, [
                      _createVNode(_component_v_icon, {
                        icon: itemIcon(item.name),
                        size: "20",
                        color: "#27865d"
                      }, null, 8, ["icon"]),
                      _createElementVNode("span", null, _toDisplayString(item.name), 1),
                      _createElementVNode("strong", null, _toDisplayString(number(item.count)), 1)
                    ]))
                  }), 128))
                ]))
              : (_openBlock(), _createElementBlock("div", _hoisted_23, [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-package-variant",
                    size: "32"
                  }),
                  _createElementVNode("p", null, _toDisplayString(loaded.value ? '暂无库存数据，运行任务后自动更新' : '正在读取库存'), 1)
                ]))
          ]))
        : (_openBlock(), _createElementBlock("div", _hoisted_24, [
            _createVNode(_component_v_table, {
              density: "compact",
              hover: ""
            }, {
              default: _withCtx(() => [
                _cache[17] || (_cache[17] = _createElementVNode("thead", null, [
                  _createElementVNode("tr", null, [
                    _createElementVNode("th", null, "执行时间"),
                    _createElementVNode("th", null, "清理 / 搬砖"),
                    _createElementVNode("th", null, "状态")
                  ])
                ], -1)),
                _createElementVNode("tbody", null, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value, (record, index) => {
                    return (_openBlock(), _createElementBlock("tr", { key: index }, [
                      _createElementVNode("td", _hoisted_25, _toDisplayString(formatTime(record.time)), 1),
                      _createElementVNode("td", null, [
                        _createElementVNode("p", null, "清理：" + _toDisplayString(record.clean?.message || '未记录'), 1),
                        _createElementVNode("p", null, "搬砖：" + _toDisplayString(record.brick?.message || '未记录'), 1)
                      ]),
                      _createElementVNode("td", null, [
                        _createVNode(_component_v_chip, {
                          size: "x-small",
                          variant: "tonal",
                          color: status(record.status).color
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(status(record.status).label), 1)
                          ]),
                          _: 2
                        }, 1032, ["color"])
                      ])
                    ]))
                  }), 128))
                ])
              ]),
              _: 1
            }),
            (!history.value.length)
              ? (_openBlock(), _createElementBlock("p", _hoisted_26, "暂无执行记录"))
              : _createCommentVNode("", true)
          ]))
    ]),
    _createElementVNode("footer", _hoisted_27, [
      _createElementVNode("span", null, _toDisplayString(view.value.running ? '任务运行中，结果将自动更新' : '等待期间不访问站点'), 1),
      _createElementVNode("span", null, "v" + _toDisplayString(view.value.version || '2.5.0') + " · xchenya", 1)
    ])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-8cf0ec68"]]);

export { Page as default };

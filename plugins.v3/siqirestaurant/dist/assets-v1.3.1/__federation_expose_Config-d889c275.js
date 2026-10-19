import { importShared } from './__federation_fn_import-054b33c3.js';
import './style-de941daf.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,normalizeClass:_normalizeClass,normalizeStyle:_normalizeStyle} = await importShared('vue');


const _hoisted_1 = { class: "sr-app sr-config" };
const _hoisted_2 = { class: "sr-topbar" };
const _hoisted_3 = { class: "sr-topbar-left" };
const _hoisted_4 = { class: "sr-topbar-icon" };
const _hoisted_5 = { class: "sr-card-title" };
const _hoisted_6 = { class: "sr-switch-grid" };
const _hoisted_7 = { class: "sr-switch-copy" };
const _hoisted_8 = ["for"];
const _hoisted_9 = { class: "sr-card sr-config-card" };
const _hoisted_10 = { class: "sr-card-title" };
const _hoisted_11 = { class: "sr-form-grid" };
const _hoisted_12 = { class: "sr-card sr-config-card" };
const _hoisted_13 = { class: "sr-card-title" };
const _hoisted_14 = { class: "sr-form-grid sr-visit-fields" };
const _hoisted_15 = { class: "sr-expansion-heading" };
const _hoisted_16 = { class: "sr-connection-status" };
const _hoisted_17 = { class: "sr-stack" };
const _hoisted_18 = { class: "sr-expansion-heading" };
const _hoisted_19 = { class: "sr-config-footer" };

const {onMounted,reactive,ref} = await importShared('vue');

const _sfc_main = {
  __name: 'Config',
  props: {api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object},
  emits: ['switch','close','config-updated'],
  setup(__props, { emit: __emit }) {

const props=__props;
const emit=__emit;
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000,auto_visit:false,visit_targets:[],notify:false});
const fieldDefaults = { VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VBtn: { size: 'small', variant: 'tonal', color: 'success' } };
const switchGroups = [
  { title: '基础设置', icon: 'mdi-toggle-switch-outline', color: '#22c55e', items: [
    { key: 'enabled', label: '启用插件', desc: '开启餐厅管理与后台服务', icon: 'mdi-power-plug', color: '#22c55e', accent: '34,197,94' },
    { key: 'notify', label: '发送运行通知', desc: '通过 MP 通知渠道推送结果与异常', icon: 'mdi-bell-outline', color: '#3b82f6', accent: '59,130,246' },
    { key: 'use_proxy', label: '使用系统代理', desc: '使用 MP 已配置的代理连接站点', icon: 'mdi-lan-connect', color: '#8b5cf6', accent: '139,92,246' }
  ] },
  { title: '自动化策略', icon: 'mdi-robot-outline', color: '#f59e0b', items: [
    { key: 'auto_enabled', label: '后台自动经营', desc: '每日开业、并行烹饪与及时上菜', icon: 'mdi-chef-hat', color: '#f59e0b', accent: '245,158,11' },
    { key: 'auto_purchase', label: '自动补足食材', desc: '按实际订单补货，遵守预算上限', icon: 'mdi-basket-outline', color: '#22c55e', accent: '34,197,94' },
    { key: 'auto_visit', label: '自动下馆子', desc: '经营结束后到访，每日最多 3 人', icon: 'mdi-silverware-fork-knife', color: '#ec4899', accent: '236,72,153' }
  ] }
];
const targets=ref(['','','']);
const cookie=ref(''),clearCookie=ref(false),message=ref(''),messageType=ref('info'),saving=ref(false),loaded=ref(false);
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');loaded.value=true;}catch(e){message.value=e.message || '读取配置失败';messageType.value='error';}});
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,auto_visit:config.auto_visit,visit_targets:targets.value,notify:config.notify,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;messageType.value=r.success?'success':'error';if(r.success){Object.assign(config,r.config);targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');cookie.value='';clearCookie.value=false;emit('config-updated',r.config);}}catch(e){message.value=e.message || '保存失败';messageType.value='error';}finally{saving.value=false;}}

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_btn_group = _resolveComponent("v-btn-group");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_expansion_panel_title = _resolveComponent("v-expansion-panel-title");
  const _component_v_checkbox = _resolveComponent("v-checkbox");
  const _component_v_expansion_panel_text = _resolveComponent("v-expansion-panel-text");
  const _component_v_expansion_panel = _resolveComponent("v-expansion-panel");
  const _component_v_expansion_panels = _resolveComponent("v-expansion-panels");
  const _component_v_defaults_provider = _resolveComponent("v-defaults-provider");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createVNode(_component_v_defaults_provider, { defaults: fieldDefaults }, {
      default: _withCtx(() => [
        _createElementVNode("header", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _createElementVNode("div", _hoisted_4, [
              _createVNode(_component_v_icon, {
                icon: "mdi-cog-outline",
                size: "24"
              })
            ]),
            _cache[8] || (_cache[8] = _createElementVNode("div", { class: "sr-topbar-copy" }, [
              _createElementVNode("h2", null, "思齐餐厅 · 配置"),
              _createElementVNode("p", null, "管理自动经营、下馆子与运行通知")
            ], -1))
          ]),
          _createVNode(_component_v_btn_group, {
            variant: "tonal",
            density: "compact",
            class: "sr-topbar-actions"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_v_btn, {
                color: "success",
                "aria-label": "返回餐厅",
                title: "返回餐厅",
                onClick: _cache[0] || (_cache[0] = $event => (emit('switch','page')))
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-view-dashboard-outline",
                    size: "18"
                  }),
                  _cache[9] || (_cache[9] = _createElementVNode("span", null, "餐厅", -1))
                ]),
                _: 1
              }),
              _createVNode(_component_v_btn, {
                color: "success",
                "aria-label": "保存配置",
                title: "保存配置",
                onClick: save,
                loading: saving.value,
                disabled: saving.value || !loaded.value
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-content-save-outline",
                    size: "18"
                  }),
                  _cache[10] || (_cache[10] = _createElementVNode("span", null, "保存", -1))
                ]),
                _: 1
              }, 8, ["loading", "disabled"]),
              _createVNode(_component_v_btn, {
                color: "success",
                "aria-label": "关闭",
                title: "关闭",
                onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-close",
                    size: "18"
                  }),
                  _cache[11] || (_cache[11] = _createElementVNode("span", null, "关闭", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        (message.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: messageType.value,
              variant: "tonal",
              density: "compact",
              closable: "",
              role: "status",
              "onClick:close": _cache[2] || (_cache[2] = $event => (message.value=''))
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(message.value), 1)
              ]),
              _: 1
            }, 8, ["type"]))
          : _createCommentVNode("", true),
        (!loaded.value && !message.value)
          ? (_openBlock(), _createBlock(_component_v_progress_linear, {
              key: 1,
              indeterminate: "",
              color: "success",
              "aria-label": "读取配置"
            }))
          : _createCommentVNode("", true),
        (_openBlock(), _createElementBlock(_Fragment, null, _renderList(switchGroups, (group) => {
          return _createElementVNode("section", {
            key: group.title,
            class: "sr-card sr-config-card"
          }, [
            _createElementVNode("div", _hoisted_5, [
              _createElementVNode("h3", null, [
                _createVNode(_component_v_icon, {
                  icon: group.icon,
                  color: group.color,
                  size: "18"
                }, null, 8, ["icon", "color"]),
                _createTextVNode(_toDisplayString(group.title), 1)
              ])
            ]),
            _createElementVNode("div", _hoisted_6, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(group.items, (item) => {
                return (_openBlock(), _createElementBlock("div", {
                  key: item.key,
                  class: _normalizeClass(["sr-switch-item", {'sr-switch-active':config[item.key]}]),
                  style: _normalizeStyle({'--sr-accent':item.accent})
                }, [
                  _createElementVNode("div", _hoisted_7, [
                    _createVNode(_component_v_icon, {
                      icon: item.icon,
                      size: "20"
                    }, null, 8, ["icon"]),
                    _createElementVNode("div", null, [
                      _createElementVNode("label", {
                        for: `sr-${item.key}`
                      }, _toDisplayString(item.label), 9, _hoisted_8),
                      _createElementVNode("p", null, _toDisplayString(item.desc), 1)
                    ])
                  ]),
                  _createVNode(_component_v_switch, {
                    id: `sr-${item.key}`,
                    modelValue: config[item.key],
                    "onUpdate:modelValue": $event => ((config[item.key]) = $event),
                    "aria-label": item.label,
                    color: item.color,
                    disabled: !loaded.value,
                    "hide-details": "",
                    density: "compact"
                  }, null, 8, ["id", "modelValue", "onUpdate:modelValue", "aria-label", "color", "disabled"])
                ], 6))
              }), 128))
            ])
          ])
        }), 64)),
        _createElementVNode("section", _hoisted_9, [
          _createElementVNode("div", _hoisted_10, [
            _createElementVNode("h3", null, [
              _createVNode(_component_v_icon, {
                icon: "mdi-tune-variant",
                color: "info",
                size: "18"
              }),
              _cache[12] || (_cache[12] = _createTextVNode("经营参数", -1))
            ]),
            _createVNode(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: "info"
            }, {
              default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                _createTextVNode("北京时间", -1)
              ]))]),
              _: 1
            })
          ]),
          _createElementVNode("div", _hoisted_11, [
            _createVNode(_component_v_text_field, {
              modelValue: config.start_time,
              "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.start_time) = $event)),
              label: "每日开业时间",
              type: "time",
              "prepend-inner-icon": "mdi-clock-outline"
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_text_field, {
              modelValue: config.daily_budget,
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.daily_budget) = $event)),
              modelModifiers: { number: true },
              label: "每日采购预算（魔力）",
              type: "number",
              min: "0",
              max: "1000000",
              step: "1",
              "prepend-inner-icon": "mdi-basket-outline"
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_text_field, {
              modelValue: config.magic_reserve,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.magic_reserve) = $event)),
              modelModifiers: { number: true },
              label: "最低保留魔力",
              type: "number",
              min: "0",
              max: "1000000000",
              step: "1",
              "prepend-inner-icon": "mdi-shield-check-outline"
            }, null, 8, ["modelValue"])
          ]),
          _cache[14] || (_cache[14] = _createElementVNode("p", { class: "sr-hint" }, "错过开业时间会补开；关闭页面后继续运行。采购预算每日重置，保存设置与重启不会清零。", -1))
        ]),
        _createElementVNode("section", _hoisted_12, [
          _createElementVNode("div", _hoisted_13, [
            _createElementVNode("h3", null, [
              _createVNode(_component_v_icon, {
                icon: "mdi-account-group-outline",
                color: "#ec4899",
                size: "18"
              }),
              _cache[15] || (_cache[15] = _createTextVNode("下馆子名单", -1))
            ]),
            _createVNode(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: "#ec4899"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(targets.value.some(t=>t.trim())?'指定用户':'随机 3 人'), 1)
              ]),
              _: 1
            })
          ]),
          _createElementVNode("div", _hoisted_14, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(targets.value, (_, i) => {
              return (_openBlock(), _createBlock(_component_v_text_field, {
                key: i,
                modelValue: targets.value[i],
                "onUpdate:modelValue": $event => ((targets.value[i]) = $event),
                modelModifiers: { trim: true },
                label: `用户名 ${i+1}（选填）`,
                "aria-label": `下馆子用户名 ${i+1}`,
                maxlength: "64",
                placeholder: "留空可随机",
                "prepend-inner-icon": "mdi-account-outline"
              }, null, 8, ["modelValue", "onUpdate:modelValue", "label", "aria-label"]))
            }), 128))
          ]),
          _cache[16] || (_cache[16] = _createElementVNode("p", { class: "sr-hint" }, "全部留空时，每天随机选择 3 位不同用户；填写后只到访名单中的用户，空位不补人。不可到访的用户会跳过并记录原因。", -1)),
          _cache[17] || (_cache[17] = _createElementVNode("p", { class: "sr-hint" }, "沿用开业时间，可单独开启下馆子。已用次数会扣除，重启不会重复到访；开启后按原站“一键下馆子”规则确认到访，为对方增加顾客。", -1))
        ]),
        _createVNode(_component_v_expansion_panels, {
          class: "sr-expansions",
          variant: "accordion",
          multiple: ""
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_expansion_panel, { elevation: "0" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_expansion_panel_title, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_15, [
                      _createVNode(_component_v_icon, {
                        icon: "mdi-cookie-outline",
                        size: "18",
                        color: "#f59e0b"
                      }),
                      _cache[18] || (_cache[18] = _createElementVNode("strong", null, "连接与凭据", -1)),
                      _createElementVNode("div", _hoisted_16, [
                        _createVNode(_component_v_chip, {
                          size: "x-small",
                          color: config.site_configured?'success':'default'
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(!loaded.value?'读取中':config.site_configured?'站点已关联':'站点未关联'), 1)
                          ]),
                          _: 1
                        }, 8, ["color"]),
                        _createVNode(_component_v_chip, {
                          size: "x-small",
                          color: config.cookie_configured?'success':'warning'
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(!loaded.value?'读取中':config.cookie_configured?'Cookie 已配置':'Cookie 未配置'), 1)
                          ]),
                          _: 1
                        }, 8, ["color"])
                      ])
                    ])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_expansion_panel_text, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_17, [
                      _cache[19] || (_cache[19] = _createElementVNode("p", { class: "sr-hint" }, "优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent；未关联时，可先在 MP 添加思齐站点。", -1)),
                      _createVNode(_component_v_text_field, {
                        modelValue: cookie.value,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((cookie).value = $event)),
                        label: "手动 Cookie（选填）",
                        type: "password",
                        autocomplete: "new-password",
                        "prepend-inner-icon": "mdi-key-outline",
                        placeholder: "仅在需要覆盖站点 Cookie 时填写",
                        hint: "留空保留现有配置，已保存的凭据不会回显。",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"]),
                      _createVNode(_component_v_checkbox, {
                        modelValue: clearCookie.value,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((clearCookie).value = $event)),
                        label: "清除插件内手动 Cookie，改用站点管理",
                        color: "warning",
                        density: "compact",
                        "hide-details": ""
                      }, null, 8, ["modelValue"])
                    ])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_expansion_panel, { elevation: "0" }, {
              default: _withCtx(() => [
                _createVNode(_component_v_expansion_panel_title, null, {
                  default: _withCtx(() => [
                    _createElementVNode("div", _hoisted_18, [
                      _createVNode(_component_v_icon, {
                        icon: "mdi-information-outline",
                        size: "18",
                        color: "info"
                      }),
                      _cache[20] || (_cache[20] = _createElementVNode("strong", null, "托管与通知说明", -1))
                    ])
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_expansion_panel_text, null, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createElementVNode("ul", { class: "sr-guide" }, [
                      _createElementVNode("li", null, "使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。"),
                      _createElementVNode("li", null, "开业前检查食材缺口和预算；补货后的魔力余额不低于最低保留值。"),
                      _createElementVNode("li", null, "通知汇总经营与下馆子结果，并提示预算不足、结果不明等异常；同类每天最多一次，不逐单推送。"),
                      _createElementVNode("li", null, "手动经营、雇佣与下馆子需先关闭两个后台任务开关。建议不要同时使用网页和插件经营同一餐厅。")
                    ], -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createElementVNode("footer", _hoisted_19, [
          _cache[23] || (_cache[23] = _createElementVNode("span", { class: "sr-hint" }, "调整完成后保存生效", -1)),
          _createVNode(_component_v_btn, {
            "prepend-icon": "mdi-content-save-outline",
            onClick: save,
            loading: saving.value,
            disabled: saving.value || !loaded.value
          }, {
            default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
              _createTextVNode("保存配置", -1)
            ]))]),
            _: 1
          }, 8, ["loading", "disabled"])
        ])
      ]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };

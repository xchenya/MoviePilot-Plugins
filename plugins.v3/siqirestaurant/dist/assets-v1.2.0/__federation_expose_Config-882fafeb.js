import { importShared } from './__federation_fn_import-054b33c3.js';
import './style-de941daf.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,vModelText:_vModelText,renderList:_renderList,Fragment:_Fragment,normalizeClass:_normalizeClass,createTextVNode:_createTextVNode} = await importShared('vue');


const _hoisted_1 = { class: "sr-app sr-config" };
const _hoisted_2 = { class: "sr-header sr-config-header" };
const _hoisted_3 = {
  key: 0,
  role: "status",
  class: "sr-notice"
};
const _hoisted_4 = { class: "sr-config-master sr-setting" };
const _hoisted_5 = { class: "sr-switch" };
const _hoisted_6 = { class: "sr-config-grid" };
const _hoisted_7 = { class: "sr-card sr-config-panel" };
const _hoisted_8 = { class: "sr-setting" };
const _hoisted_9 = { class: "sr-switch" };
const _hoisted_10 = { class: "sr-field" };
const _hoisted_11 = { class: "sr-card sr-config-panel" };
const _hoisted_12 = { class: "sr-setting" };
const _hoisted_13 = { class: "sr-switch" };
const _hoisted_14 = { class: "sr-budget-fields" };
const _hoisted_15 = { class: "sr-field" };
const _hoisted_16 = { class: "sr-field" };
const _hoisted_17 = { class: "sr-card sr-config-panel" };
const _hoisted_18 = { class: "sr-setting" };
const _hoisted_19 = { class: "sr-switch" };
const _hoisted_20 = { class: "sr-visit-fields" };
const _hoisted_21 = ["onUpdate:modelValue", "aria-label"];
const _hoisted_22 = { class: "sr-card sr-config-panel" };
const _hoisted_23 = { class: "sr-setting" };
const _hoisted_24 = { class: "sr-switch" };
const _hoisted_25 = { class: "sr-config-details" };
const _hoisted_26 = { class: "sr-connection-status" };
const _hoisted_27 = { class: "sr-details-body" };
const _hoisted_28 = { class: "sr-setting" };
const _hoisted_29 = { class: "sr-switch" };
const _hoisted_30 = { class: "sr-field" };
const _hoisted_31 = { class: "sr-clear-cookie" };
const _hoisted_32 = { class: "sr-config-footer" };
const _hoisted_33 = { class: "sr-config-help" };
const _hoisted_34 = { class: "sr-actions" };
const _hoisted_35 = ["disabled"];

const {onMounted,reactive,ref} = await importShared('vue');

const _sfc_main = {
  __name: 'Config',
  props: {api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object},
  emits: ['switch','close','config-updated'],
  setup(__props, { emit: __emit }) {

const props=__props;
const emit=__emit;
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000,auto_visit:false,visit_targets:[],notify:false});
const targets=ref(['','','']);
const cookie=ref(''),clearCookie=ref(false),message=ref(''),saving=ref(false),loaded=ref(false);
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');loaded.value=true;}catch(e){message.value=e.message || '读取配置失败';}});
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,auto_visit:config.auto_visit,visit_targets:targets.value,notify:config.notify,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;if(r.success){Object.assign(config,r.config);targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');cookie.value='';clearCookie.value=false;emit('config-updated',r.config);}}catch(e){message.value=e.message || '保存失败';}finally{saving.value=false;}}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _cache[13] || (_cache[13] = _createElementVNode("div", null, [
        _createElementVNode("span", { class: "sr-eyebrow" }, "SIQI · RESTAURANT"),
        _createElementVNode("h2", null, "餐厅设置"),
        _createElementVNode("p", null, "安排每日经营，让餐厅按你的节奏运转。")
      ], -1)),
      _createElementVNode("button", {
        onClick: _cache[0] || (_cache[0] = $event => (emit('switch','page')))
      }, "返回餐厅")
    ]),
    (message.value)
      ? (_openBlock(), _createElementBlock("p", _hoisted_3, _toDisplayString(message.value), 1))
      : _createCommentVNode("", true),
    _createElementVNode("label", _hoisted_4, [
      _cache[15] || (_cache[15] = _createElementVNode("span", { class: "sr-setting-copy" }, [
        _createElementVNode("strong", null, "启用插件"),
        _createElementVNode("small", null, "开启餐厅管理与后台服务")
      ], -1)),
      _createElementVNode("span", _hoisted_5, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event))
        }, null, 512), [
          [_vModelCheckbox, config.enabled]
        ]),
        _cache[14] || (_cache[14] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
      ])
    ]),
    _createElementVNode("div", _hoisted_6, [
      _createElementVNode("section", _hoisted_7, [
        _cache[20] || (_cache[20] = _createElementVNode("div", { class: "sr-config-panel-head" }, [
          _createElementVNode("h3", null, "自动经营"),
          _createElementVNode("span", { class: "sr-badge" }, "北京时间")
        ], -1)),
        _createElementVNode("label", _hoisted_8, [
          _cache[17] || (_cache[17] = _createElementVNode("span", { class: "sr-setting-copy" }, [
            _createElementVNode("strong", null, "后台自动经营"),
            _createElementVNode("small", null, "每日开业、烹饪与上菜")
          ], -1)),
          _createElementVNode("span", _hoisted_9, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.auto_enabled) = $event))
            }, null, 512), [
              [_vModelCheckbox, config.auto_enabled]
            ]),
            _cache[16] || (_cache[16] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
          ])
        ]),
        _createElementVNode("label", _hoisted_10, [
          _cache[18] || (_cache[18] = _createElementVNode("span", null, "每日开业时间", -1)),
          _withDirectives(_createElementVNode("input", {
            type: "time",
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.start_time) = $event))
          }, null, 512), [
            [_vModelText, config.start_time]
          ]),
          _cache[19] || (_cache[19] = _createElementVNode("small", null, "错过时间会补开，关闭插件页面后仍会继续经营。", -1))
        ])
      ]),
      _createElementVNode("section", _hoisted_11, [
        _cache[25] || (_cache[25] = _createElementVNode("div", { class: "sr-config-panel-head" }, [
          _createElementVNode("h3", null, "食材与预算"),
          _createElementVNode("span", { class: "sr-badge" }, "魔力")
        ], -1)),
        _createElementVNode("label", _hoisted_12, [
          _cache[22] || (_cache[22] = _createElementVNode("span", { class: "sr-setting-copy" }, [
            _createElementVNode("strong", null, "自动补足食材"),
            _createElementVNode("small", null, "只采购实际订单缺少的食材")
          ], -1)),
          _createElementVNode("span", _hoisted_13, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.auto_purchase) = $event))
            }, null, 512), [
              [_vModelCheckbox, config.auto_purchase]
            ]),
            _cache[21] || (_cache[21] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_14, [
          _createElementVNode("label", _hoisted_15, [
            _cache[23] || (_cache[23] = _createElementVNode("span", null, "每日采购预算", -1)),
            _withDirectives(_createElementVNode("input", {
              type: "number",
              min: "0",
              max: "1000000",
              step: "1",
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.daily_budget) = $event))
            }, null, 512), [
              [
                _vModelText,
                config.daily_budget,
                void 0,
                { number: true }
              ]
            ])
          ]),
          _createElementVNode("label", _hoisted_16, [
            _cache[24] || (_cache[24] = _createElementVNode("span", null, "最低保留魔力", -1)),
            _withDirectives(_createElementVNode("input", {
              type: "number",
              min: "0",
              max: "1000000000",
              step: "1",
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.magic_reserve) = $event))
            }, null, 512), [
              [
                _vModelText,
                config.magic_reserve,
                void 0,
                { number: true }
              ]
            ])
          ])
        ]),
        _cache[26] || (_cache[26] = _createElementVNode("p", { class: "sr-config-help" }, "预算每日重置，保存设置与重启不会清零。", -1))
      ]),
      _createElementVNode("section", _hoisted_17, [
        _cache[29] || (_cache[29] = _createElementVNode("div", { class: "sr-config-panel-head" }, [
          _createElementVNode("h3", null, "自动下馆子"),
          _createElementVNode("span", { class: "sr-badge" }, "每日最多 3 人")
        ], -1)),
        _createElementVNode("label", _hoisted_18, [
          _cache[28] || (_cache[28] = _createElementVNode("span", { class: "sr-setting-copy" }, [
            _createElementVNode("strong", null, "自动下馆子"),
            _createElementVNode("small", null, "经营结束后，按名单到访其他餐馆")
          ], -1)),
          _createElementVNode("span", _hoisted_19, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.auto_visit) = $event))
            }, null, 512), [
              [_vModelCheckbox, config.auto_visit]
            ]),
            _cache[27] || (_cache[27] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_20, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(targets.value, (_, i) => {
            return (_openBlock(), _createElementBlock("label", {
              key: i,
              class: "sr-field"
            }, [
              _createElementVNode("span", null, "用户名 " + _toDisplayString(i+1), 1),
              _withDirectives(_createElementVNode("input", {
                "onUpdate:modelValue": $event => ((targets.value[i]) = $event),
                maxlength: "64",
                "aria-label": `下馆子用户名 ${i+1}`,
                placeholder: "选填"
              }, null, 8, _hoisted_21), [
                [
                  _vModelText,
                  targets.value[i],
                  void 0,
                  { trim: true }
                ]
              ])
            ]))
          }), 128))
        ]),
        _cache[30] || (_cache[30] = _createElementVNode("p", { class: "sr-config-help" }, "全部留空：每天随机选择 3 位不同用户。填写后只到访名单中的用户，空位不补人。不可到访的用户会跳过并记录原因。", -1)),
        _cache[31] || (_cache[31] = _createElementVNode("p", { class: "sr-config-help" }, "沿用每日开业时间；也可单独开启下馆子。已用次数会扣除，重启不会重复到访。开启即按原站“一键下馆子”规则确认到访，为对方增加顾客。", -1))
      ]),
      _createElementVNode("section", _hoisted_22, [
        _cache[34] || (_cache[34] = _createElementVNode("div", { class: "sr-config-panel-head" }, [
          _createElementVNode("h3", null, "消息通知"),
          _createElementVNode("span", { class: "sr-badge" }, "MoviePilot")
        ], -1)),
        _createElementVNode("label", _hoisted_23, [
          _cache[33] || (_cache[33] = _createElementVNode("span", { class: "sr-setting-copy" }, [
            _createElementVNode("strong", null, "发送运行通知"),
            _createElementVNode("small", null, "通过 MP 已配置的通知渠道发送")
          ], -1)),
          _createElementVNode("span", _hoisted_24, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.notify) = $event))
            }, null, 512), [
              [_vModelCheckbox, config.notify]
            ]),
            _cache[32] || (_cache[32] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
          ])
        ]),
        _cache[35] || (_cache[35] = _createElementVNode("p", { class: "sr-config-help" }, "汇总今日经营与下馆子结果，提示预算不足、写入结果不明等异常。同类通知每天最多一次，逐次上菜和补货不会推送。", -1))
      ])
    ]),
    _createElementVNode("details", _hoisted_25, [
      _createElementVNode("summary", null, [
        _cache[36] || (_cache[36] = _createElementVNode("span", { class: "sr-summary-copy" }, [
          _createElementVNode("strong", null, "连接与凭据"),
          _createElementVNode("small", null, "站点管理、代理与手动 Cookie")
        ], -1)),
        _createElementVNode("span", _hoisted_26, [
          _createElementVNode("span", {
            class: _normalizeClass(["sr-badge", {'sr-status-ready':loaded.value && config.site_configured}])
          }, _toDisplayString(!loaded.value?'读取中':config.site_configured?'站点已关联':'站点未关联'), 3),
          _createElementVNode("span", {
            class: _normalizeClass(["sr-badge", {'sr-status-ready':loaded.value && config.cookie_configured,'sr-status-warning':loaded.value && !config.cookie_configured}])
          }, _toDisplayString(!loaded.value?'读取中':config.cookie_configured?'Cookie 已配置':'Cookie 未配置'), 3)
        ])
      ]),
      _createElementVNode("div", _hoisted_27, [
        _cache[42] || (_cache[42] = _createElementVNode("p", { class: "sr-config-help" }, "优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent；未关联时，可先在 MP 添加思齐站点。", -1)),
        _createElementVNode("label", _hoisted_28, [
          _cache[38] || (_cache[38] = _createElementVNode("span", { class: "sr-setting-copy" }, [
            _createElementVNode("strong", null, "使用 MoviePilot 系统代理"),
            _createElementVNode("small", null, "通过 MP 中已配置的代理连接站点")
          ], -1)),
          _createElementVNode("span", _hoisted_29, [
            _withDirectives(_createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.use_proxy) = $event))
            }, null, 512), [
              [_vModelCheckbox, config.use_proxy]
            ]),
            _cache[37] || (_cache[37] = _createElementVNode("span", { "aria-hidden": "true" }, null, -1))
          ])
        ]),
        _createElementVNode("label", _hoisted_30, [
          _cache[39] || (_cache[39] = _createElementVNode("span", null, [
            _createTextVNode("手动 Cookie "),
            _createElementVNode("small", null, "选填")
          ], -1)),
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((cookie).value = $event)),
            type: "password",
            autocomplete: "new-password",
            placeholder: "仅在需要覆盖站点 Cookie 时填写"
          }, null, 512), [
            [_vModelText, cookie.value]
          ]),
          _cache[40] || (_cache[40] = _createElementVNode("small", null, "留空保留现有配置，已保存的凭据不会回显。", -1))
        ]),
        _createElementVNode("label", _hoisted_31, [
          _withDirectives(_createElementVNode("input", {
            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((clearCookie).value = $event)),
            type: "checkbox"
          }, null, 512), [
            [_vModelCheckbox, clearCookie.value]
          ]),
          _cache[41] || (_cache[41] = _createTextVNode("清除插件内手动 Cookie，改用站点管理", -1))
        ]),
        _cache[43] || (_cache[43] = _createElementVNode("p", { class: "sr-config-help" }, "Cookie 只由 MP 后端发往 https://si-qi.xyz。", -1))
      ])
    ]),
    _cache[44] || (_cache[44] = _createElementVNode("details", { class: "sr-config-details sr-config-guide" }, [
      _createElementVNode("summary", null, [
        _createElementVNode("span", { class: "sr-summary-copy" }, [
          _createElementVNode("strong", null, "托管说明"),
          _createElementVNode("small", null, "调度方式与操作注意事项")
        ])
      ]),
      _createElementVNode("div", { class: "sr-details-body" }, [
        _createElementVNode("ul", null, [
          _createElementVNode("li", null, "使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。"),
          _createElementVNode("li", null, "开业前检查预算能否覆盖保守估计的食材缺口；补货后余额不低于最低保留魔力。"),
          _createElementVNode("li", null, "保存并启用后，到达开业时间会立即开始。关闭托管后，已发送的请求会完成，但不会继续下一步。"),
          _createElementVNode("li", null, "扩招员工、丢弃成品与手动下馆子需先关闭两个后台任务开关。"),
          _createElementVNode("li", null, "建议不要同时使用网页和插件经营同一餐厅，两端厨房进度相互独立。")
        ])
      ])
    ], -1)),
    _createElementVNode("footer", _hoisted_32, [
      _createElementVNode("span", _hoisted_33, _toDisplayString(loaded.value?'调整完成后保存生效':'正在读取配置…'), 1),
      _createElementVNode("div", _hoisted_34, [
        _createElementVNode("button", {
          onClick: _cache[12] || (_cache[12] = $event => (emit('close')))
        }, "关闭"),
        _createElementVNode("button", {
          class: "sr-primary",
          onClick: save,
          disabled: saving.value || !loaded.value
        }, _toDisplayString(saving.value?'保存中…':'保存配置'), 9, _hoisted_35)
      ])
    ])
  ]))
}
}

};

export { _sfc_main as default };

import { importShared } from './__federation_fn_import-054b33c3.js';
import './style-de941daf.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,createTextVNode:_createTextVNode,vModelText:_vModelText} = await importShared('vue');


const _hoisted_1 = { class: "sr-app sr-config" };
const _hoisted_2 = { class: "sr-header" };
const _hoisted_3 = {
  key: 0,
  role: "status",
  class: "sr-notice"
};
const _hoisted_4 = { class: "sr-card" };
const _hoisted_5 = { class: "sr-actions" };
const _hoisted_6 = ["disabled"];

const {onMounted,reactive,ref} = await importShared('vue');

const _sfc_main = {
  __name: 'Config',
  props: {api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object},
  emits: ['switch','close','config-updated'],
  setup(__props, { emit: __emit }) {

const props=__props;
const emit=__emit;
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000});
const cookie=ref(''),clearCookie=ref(false),message=ref(''),saving=ref(false),loaded=ref(false);
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));loaded.value=true;}catch(e){message.value=e.message || '读取配置失败';}});
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;if(r.success){Object.assign(config,r.config);cookie.value='';clearCookie.value=false;emit('config-updated',r.config);}}catch(e){message.value=e.message || '保存失败';}finally{saving.value=false;}}

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _cache[11] || (_cache[11] = _createElementVNode("div", null, [
        _createElementVNode("span", { class: "sr-eyebrow" }, "SIQI · RESTAURANT"),
        _createElementVNode("h2", null, "餐厅设置")
      ], -1)),
      _createElementVNode("button", {
        onClick: _cache[0] || (_cache[0] = $event => (emit('switch','page')))
      }, "返回餐厅")
    ]),
    _cache[25] || (_cache[25] = _createElementVNode("p", { class: "sr-muted" }, "优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent。后台自动经营由 MP 定时任务执行，关闭插件页面后仍会继续。", -1)),
    (message.value)
      ? (_openBlock(), _createElementBlock("p", _hoisted_3, _toDisplayString(message.value), 1))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_4, [
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event))
        }, null, 512), [
          [_vModelCheckbox, config.enabled]
        ]),
        _cache[12] || (_cache[12] = _createTextVNode("启用插件", -1))
      ]),
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.use_proxy) = $event))
        }, null, 512), [
          [_vModelCheckbox, config.use_proxy]
        ]),
        _cache[13] || (_cache[13] = _createTextVNode("使用 MoviePilot 系统代理", -1))
      ]),
      _cache[21] || (_cache[21] = _createElementVNode("hr", null, null, -1)),
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.auto_enabled) = $event))
        }, null, 512), [
          [_vModelCheckbox, config.auto_enabled]
        ]),
        _cache[14] || (_cache[14] = _createTextVNode("后台自动经营（每日开业、烹饪、上菜）", -1))
      ]),
      _createElementVNode("label", null, [
        _cache[15] || (_cache[15] = _createTextVNode("每日开业时间（北京时间，错过后补开）", -1)),
        _withDirectives(_createElementVNode("input", {
          type: "time",
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.start_time) = $event))
        }, null, 512), [
          [_vModelText, config.start_time]
        ])
      ]),
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.auto_purchase) = $event))
        }, null, 512), [
          [_vModelCheckbox, config.auto_purchase]
        ]),
        _cache[16] || (_cache[16] = _createTextVNode("按实际订单自动补足缺少的食材", -1))
      ]),
      _createElementVNode("label", null, [
        _cache[17] || (_cache[17] = _createTextVNode("每日采购预算（魔力）", -1)),
        _withDirectives(_createElementVNode("input", {
          type: "number",
          min: "0",
          max: "1000000",
          step: "1",
          "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.daily_budget) = $event))
        }, null, 512), [
          [
            _vModelText,
            config.daily_budget,
            void 0,
            { number: true }
          ]
        ])
      ]),
      _createElementVNode("label", null, [
        _cache[18] || (_cache[18] = _createTextVNode("补货后至少保留魔力", -1)),
        _withDirectives(_createElementVNode("input", {
          type: "number",
          min: "0",
          max: "1000000000",
          step: "1",
          "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.magic_reserve) = $event))
        }, null, 512), [
          [
            _vModelText,
            config.magic_reserve,
            void 0,
            { number: true }
          ]
        ])
      ]),
      _cache[22] || (_cache[22] = _createElementVNode("p", { class: "sr-muted" }, "托管使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。开业前检查预算能否覆盖保守估计的食材缺口。不会自动扩招员工、丢弃成品或下馆子；这些仍可暂停托管后手动操作。", -1)),
      _cache[23] || (_cache[23] = _createElementVNode("p", { class: "sr-muted" }, "保存并启用后，到达开业时间会立即开始。采购预算按北京时间每日重置，保存设置和重启不会清零。已发送的请求会完成；关闭托管后不会继续下一步。", -1)),
      _createElementVNode("p", null, "站点配置：" + _toDisplayString(config.site_configured?'已找到思齐':'未找到，可先在 MP 添加思齐站点') + " · Cookie：" + _toDisplayString(config.cookie_configured?'已配置':'未配置'), 1),
      _createElementVNode("label", null, [
        _cache[19] || (_cache[19] = _createTextVNode("手动 Cookie（选填，留空保留现有配置）", -1)),
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((cookie).value = $event)),
          type: "password",
          autocomplete: "new-password",
          placeholder: "仅在需要覆盖站点 Cookie 时填写"
        }, null, 512), [
          [_vModelText, cookie.value]
        ])
      ]),
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((clearCookie).value = $event)),
          type: "checkbox"
        }, null, 512), [
          [_vModelCheckbox, clearCookie.value]
        ]),
        _cache[20] || (_cache[20] = _createTextVNode("清除插件内手动 Cookie，改用站点管理", -1))
      ]),
      _cache[24] || (_cache[24] = _createElementVNode("p", { class: "sr-muted" }, "Cookie 只由 MP 后端发往 https://si-qi.xyz；接口不回显凭据。建议不要同时使用网页和插件经营同一餐厅，两端厨房进度相互独立。", -1)),
      _createElementVNode("div", _hoisted_5, [
        _createElementVNode("button", {
          class: "sr-primary",
          onClick: save,
          disabled: saving.value || !loaded.value
        }, "保存配置", 8, _hoisted_6),
        _createElementVNode("button", {
          onClick: _cache[10] || (_cache[10] = $event => (emit('close')))
        }, "关闭")
      ])
    ])
  ]))
}
}

};

export { _sfc_main as default };

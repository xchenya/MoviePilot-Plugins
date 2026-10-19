import { importShared } from './__federation_fn_import-054b33c3.js';
import './style-de941daf.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,normalizeClass:_normalizeClass,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,vModelCheckbox:_vModelCheckbox,withDirectives:_withDirectives,vModelSelect:_vModelSelect,vModelText:_vModelText,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "sr-app" };
const _hoisted_2 = { class: "sr-header" };
const _hoisted_3 = { class: "sr-actions" };
const _hoisted_4 = ["disabled"];
const _hoisted_5 = {
  key: 1,
  class: "sr-notice sr-error"
};
const _hoisted_6 = ["disabled"];
const _hoisted_7 = { class: "sr-stats" };
const _hoisted_8 = {
  class: "sr-card sr-automation",
  "aria-label": "后台自动经营状态"
};
const _hoisted_9 = { class: "sr-card-title" };
const _hoisted_10 = {
  key: 0,
  class: "sr-muted"
};
const _hoisted_11 = { class: "sr-toolbar" };
const _hoisted_12 = ["disabled"];
const _hoisted_13 = ["disabled"];
const _hoisted_14 = {
  class: "sr-tabs",
  "aria-label": "餐厅功能"
};
const _hoisted_15 = ["onClick"];
const _hoisted_16 = { class: "sr-section-head" };
const _hoisted_17 = { class: "sr-kitchen-grid" };
const _hoisted_18 = { class: "sr-card-title" };
const _hoisted_19 = { class: "sr-badge" };
const _hoisted_20 = ["value", "max"];
const _hoisted_21 = { key: 2 };
const _hoisted_22 = ["onUpdate:modelValue", "disabled", "aria-label"];
const _hoisted_23 = ["value"];
const _hoisted_24 = { key: 1 };
const _hoisted_25 = {
  key: 2,
  class: "sr-muted"
};
const _hoisted_26 = { class: "sr-actions sr-wrap" };
const _hoisted_27 = ["disabled", "onClick"];
const _hoisted_28 = ["disabled", "onClick"];
const _hoisted_29 = ["disabled", "onClick"];
const _hoisted_30 = ["disabled", "onClick"];
const _hoisted_31 = {
  key: 2,
  class: "sr-cooking"
};
const _hoisted_32 = ["onUpdate:modelValue", "disabled", "aria-label"];
const _hoisted_33 = ["value"];
const _hoisted_34 = ["disabled", "onClick"];
const _hoisted_35 = ["disabled", "onClick"];
const _hoisted_36 = ["disabled", "onClick"];
const _hoisted_37 = {
  key: 3,
  class: "sr-staff-actions"
};
const _hoisted_38 = ["disabled", "onClick"];
const _hoisted_39 = {
  key: 0,
  class: "sr-empty"
};
const _hoisted_40 = { class: "sr-grid" };
const _hoisted_41 = { class: "sr-actions" };
const _hoisted_42 = ["onUpdate:modelValue", "aria-label"];
const _hoisted_43 = ["disabled", "onClick"];
const _hoisted_44 = { class: "sr-grid" };
const _hoisted_45 = { class: "sr-muted" };
const _hoisted_46 = { class: "sr-badge" };
const _hoisted_47 = { class: "sr-actions sr-wrap" };
const _hoisted_48 = { class: "sr-grid" };
const _hoisted_49 = ["disabled", "onClick"];
const _hoisted_50 = { class: "sr-card" };
const _hoisted_51 = { class: "sr-card-title" };
const _hoisted_52 = { class: "sr-actions sr-wrap" };
const _hoisted_53 = ["disabled"];
const _hoisted_54 = ["disabled"];
const _hoisted_55 = ["disabled"];
const _hoisted_56 = { class: "sr-grid" };
const _hoisted_57 = ["disabled", "onClick"];
const _hoisted_58 = { class: "sr-section-head" };
const _hoisted_59 = { class: "sr-muted" };
const _hoisted_60 = { class: "sr-table-wrap" };
const _hoisted_61 = { class: "sr-table-wrap" };
const _hoisted_62 = {
  class: "sr-dialog",
  role: "dialog",
  "aria-modal": "true",
  "aria-labelledby": "sr-confirm-title"
};
const _hoisted_63 = { id: "sr-confirm-title" };

const {computed,onMounted,onUnmounted,onActivated,onDeactivated,reactive,ref} = await importShared('vue');

const _sfc_main = {
  __name: 'Page',
  props: { api: Object, pluginId: {type:String,default:'SiqiRestaurant'}, initialConfig: Object },
  emits: ['switch','close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const view = ref({}), busy = ref(false), message = ref(''), ok = ref(true), runStaff = ref(false);
const selected = reactive({}), serveTargets = reactive({}), quantities = reactive({});
const targetName = ref(''), recommendations = ref([]), logDays = ref(0), activeTab = ref('kitchen');
const now = ref(Date.now()/1000), confirmation = ref(null);
let clockOffset=0, timer=null, clock=null, alive=false, confirmResolver=null;
const data = computed(()=>view.value.restaurant || {}), state = computed(()=>data.value.state || {});
const blocked = computed(()=>busy.value || !!view.value.uncertain || !!view.value.automation?.enabled || !!view.value.automation?.active || !data.value.state);
const tabs = [{id:'kitchen',label:'厨房与餐位'},{id:'supplies',label:'食材与菜品'},{id:'staff',label:'员工'},{id:'visits',label:'下馆子'},{id:'logs',label:'经营日志'}];
const roles = [{key:'chef',label:'🧑‍🍳 厨师'},{key:'server',label:'💁 服务员'}];
const actionLabels = {purchase_ingredient:'购买食材',hire_staff:'雇佣员工',update_staff_assignment:'员工调度',start_session:'开始营业',visit_restaurant:'下馆子',serve_customer:'上菜',discard_dish:'丢弃菜品',customer_left:'顾客离席',resolve:'核对解锁',automation:'自动经营',auto_visit:'自动下馆子',notification:'通知'};
const number = n => Number(n || 0).toLocaleString();
const statusLabel = computed(()=>({ready:'准备营业',open:'营业中',closed:'已闭店'}[state.value.session_status] || '未连接'));
const stats = computed(()=>[{label:'魔力余额',value:number(data.value.user?.magic)},{label:'受欢迎值',value:number(state.value.popularity)},{label:'今日顾客',value:`${state.value.customers_served || 0} / ${state.value.customers_total || 0}`},{label:'今日净收益',value:number(state.value.net_earnings_today)},{label:'累计净收益',value:number(state.value.net_earnings_total)}]);
const unlockedDishes = computed(()=>(data.value.config?.dishes || []).filter(d=>state.value.unlocked?.dishes?.includes(d.key)));
const filteredLogs = computed(()=>(data.value.logs || []).filter(l=>!logDays.value || Date.parse(`${l.log_date}T00:00:00+08:00`) >= now.value*1000-logDays.value*86400000));
const dish = key=>(data.value.config?.dishes || []).find(d=>d.key===key);
const dishName = key=>dish(key)?.name || key;
const remaining = timestamp=>Math.max(0,Math.ceil(Number(timestamp)-now.value));
const patience = customer=>customer?.deadline?remaining(customer.deadline):Number(customer?.patience || 0);
const customerAt = index=>(state.value.customer_plan || []).find(c=>c.status==='waiting' && Number(c.seat)===index);
const cleaningLeft = index=>remaining(view.value.cleaning?.[String(index)] || 0);
const matchingCustomers = stove=>(state.value.customer_plan || []).filter(c=>c.status==='waiting' && c.seat && c.dish_key===stove.dish_key && patience(c)>0 && !cleaningLeft(c.seat));
function recipeText(key){const d=dish(key);if(!d)return '';return (d.ingredients||[]).map(i=>`${data.value.config?.ingredients?.find(x=>x.key===i.key)?.name || i.key} ×${i.quantity}`).join('、')+` · ${data.value.config?.tools?.find(t=>t.key===d.tool)?.name || d.tool}`}
function prepared(stove){const d=dish(stove.dish_key);return d && stove.tool_key===d.tool && d.ingredients.every(i=>Number(stove.ingredients[i.key]||0)>=Number(i.quantity))}
function available(key){return Math.max(0,Number(data.value.inventory?.ingredients?.[key]||0)-(view.value.kitchen||[]).reduce((n,s)=>n+Number(s.ingredients?.[key]||0),0))}
function stoveStatus(s){return {idle:'空闲',prepping:prepared(s)?'已备齐':'备菜中',cooking:'烹饪中',ready:'待上菜'}[s.status] || s.status}
function assigned(index,role){const a=data.value.staff?.assignments_map || data.value.staff?.assignments || {};const value=(Array.isArray(a)?a.find(x=>Number(x.station_index)===index):a[index])?.[role];return value===true || value===1 || value==='1'}
function unwrap(result){if(result?.restaurant || typeof result?.success==='boolean')return result;if(result?.data && typeof result.data.success==='boolean')return result.data;throw new Error('插件接口返回格式不正确')}
function update(result){if(!alive)return;view.value=result;clockOffset=(result.server_now || Date.now()/1000)-Date.now()/1000;now.value=Date.now()/1000+clockOffset;for(const s of result.kitchen||[]){selected[s.index]??='';const matches=matchingCustomers(s);if(!matches.some(c=>String(c.id)===String(serveTargets[s.index])))serveTargets[s.index]=matches.find(c=>Number(c.seat)===s.index)?.id || matches[0]?.id || '';}for(const item of result.restaurant?.config?.ingredients || [])quantities[item.key]??=1;if(result.uncertain || result.automation?.enabled)runStaff.value=false;}
async function request(path,payload,verb='post',quiet=false){if(busy.value)return null;busy.value=true;try{const r=unwrap(await props.api[verb](`plugin/${props.pluginId}${path}`,payload));update(r);if(!quiet || !r.success){message.value=r.message || (r.success?'操作完成':'操作失败');ok.value=r.success;}return r}catch(e){if(alive){message.value=e.message || '请求失败，请刷新后核对';ok.value=false;runStaff.value=false;}return null}finally{busy.value=false;}}
const act=(action,args={})=>request('/action',{action,args,request_id:(crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)});
const refresh=()=>request('/refresh',{});
function confirm(title,text){return new Promise(resolve=>{confirmation.value={title,text};confirmResolver=resolve;})}
function cancelConfirm(){confirmation.value=null;confirmResolver?.(false);confirmResolver=null;}
function acceptConfirm(){confirmation.value=null;confirmResolver?.(true);confirmResolver=null;}
async function startSession(){if(await confirm('开始今日经营','每天只能开业一次，开业后顾客耐心开始倒计时。可先备菜，再开始经营。'))await act('start_session');}
async function buy(item){const q=Number(quantities[item.key]??1);if(!Number.isInteger(q)||q<1||q>10000){message.value='购买数量须为 1–10000 的整数';ok.value=false;return}if(await confirm('购买食材',`${item.name} × ${q}，当前报价合计 ${number(q*item.price)} 魔力。`))await act('purchase_ingredient',{ingredient_key:item.key,quantity:q,max_cost:q*Number(item.price)});}
async function hire(role){if(await confirm('雇佣员工',`雇佣 1 位${role.label}，当前报价 ${number(data.value.staff?.next_prices?.[role.key])} 魔力。`))await act('hire_staff',{role:role.key,quantity:1,max_cost:Number(data.value.staff?.next_prices?.[role.key])});}
async function askDiscard(s){if(await confirm('丢弃菜品',`丢弃「${dishName(s.dish_key)}」会按站点规则消耗食材，无售出收益。`))await act('discard',{station_index:s.index});}
async function askReturn(s){if(await confirm('归位灶台','与原网页一致，归位会提交丢弃菜品并消耗相应食材，无售出收益。'))await act('return_stove',{station_index:s.index});}
async function recommend(){const r=await act('list_visitable_restaurants');if(r?.success)recommendations.value=r.restaurants || [];}
async function lookup(){const r=await act('inspect_restaurant_target',{target_username:targetName.value});if(r?.success)recommendations.value=r.candidate?[r.candidate]:[];}
async function visit(name){if(!await confirm('前往用餐',`前往 ${name} 的餐馆，将使用今日一次下馆子机会。`))return;let r=await act('visit_restaurant',{target_username:name});if(r?.requires_confirmation && await confirm('站点确认',r.message || '站点要求再次确认前往'))await act('visit_restaurant',{target_username:name,confirm:'yes'});}
async function resolveUncertain(){if(await confirm('核对后解锁','请确认已经核对网站的余额、库存、员工与顾客状态。解除后不会重发原请求；结果不明的成品将释放本地预留。'))await request('/resolve',{acknowledged:true});}
async function poll(){if(!alive)return;try{if(!document.hidden && !busy.value && !confirmation.value && data.value.state)await (view.value.automation?.enabled ? request('/state',undefined,'get',true) : request('/tick',{run_staff:runStaff.value},'post',true));}finally{if(alive)timer=setTimeout(poll,2000);}}
function start(){if(alive)return;alive=true;request('/state',undefined,'get',true);clock=setInterval(()=>{now.value=Date.now()/1000+clockOffset;},500);timer=setTimeout(poll,2000);}
function stop(){alive=false;runStaff.value=false;clearTimeout(timer);clearInterval(clock);cancelConfirm();}
onMounted(start);onActivated(start);onDeactivated(stop);onUnmounted(stop);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", null, [
        _cache[9] || (_cache[9] = _createElementVNode("span", { class: "sr-eyebrow" }, "SIQI · RESTAURANT", -1)),
        _createElementVNode("h2", null, [
          _cache[8] || (_cache[8] = _createTextVNode("思齐餐厅 ", -1)),
          _createElementVNode("small", null, _toDisplayString(statusLabel.value), 1)
        ]),
        _cache[10] || (_cache[10] = _createElementVNode("p", null, "经营你的餐厅，照顾每一位顾客。", -1))
      ]),
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("button", {
          onClick: refresh,
          disabled: busy.value
        }, "刷新", 8, _hoisted_4),
        _createElementVNode("button", {
          onClick: _cache[0] || (_cache[0] = $event => (emit('switch', 'config')))
        }, "配置"),
        _createElementVNode("button", {
          onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
        }, "关闭")
      ])
    ]),
    (message.value)
      ? (_openBlock(), _createElementBlock("div", {
          key: 0,
          role: "status",
          class: _normalizeClass(["sr-notice", { 'sr-error': !ok.value }])
        }, _toDisplayString(message.value), 3))
      : _createCommentVNode("", true),
    (view.value.uncertain)
      ? (_openBlock(), _createElementBlock("div", _hoisted_5, [
          _cache[11] || (_cache[11] = _createTextVNode("上次站点操作结果不明，已暂停写入。请先刷新并核对网站。 ", -1)),
          _createElementVNode("button", {
            onClick: resolveUncertain,
            disabled: busy.value
          }, "已核对，解除锁定", 8, _hoisted_6)
        ]))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_7, [
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(stats.value, (item) => {
        return (_openBlock(), _createElementBlock("article", {
          key: item.label
        }, [
          _createElementVNode("span", null, _toDisplayString(item.label), 1),
          _createElementVNode("strong", null, _toDisplayString(item.value), 1)
        ]))
      }), 128))
    ]),
    _createElementVNode("section", _hoisted_8, [
      _createElementVNode("div", _hoisted_9, [
        _createElementVNode("h3", null, "后台自动经营 · " + _toDisplayString(view.value.automation?.enabled?'已开启':'已暂停'), 1),
        _createElementVNode("button", {
          onClick: _cache[2] || (_cache[2] = $event => (emit('switch','config')))
        }, _toDisplayString(view.value.automation?.enabled?'暂停 / 调整托管':'设置自动经营'), 1)
      ]),
      _createElementVNode("p", null, _toDisplayString(view.value.automation?.enabled ? (view.value.automation.message || '等待后台首次检查') : '可在配置中开启每日自动经营。'), 1),
      (view.value.automation?.enabled)
        ? (_openBlock(), _createElementBlock("p", _hoisted_10, "今日补货预算已占用 " + _toDisplayString(number(view.value.automation.spent)) + " / " + _toDisplayString(number(view.value.automation.daily_budget)) + " 魔力 · " + _toDisplayString(view.value.automation.last_check ? `最近后台检查 ${new Date(view.value.automation.last_check*1000).toLocaleTimeString()}` : '尚未检查') + "。关闭本页面后继续运行。", 1))
        : _createCommentVNode("", true)
    ]),
    _createElementVNode("div", _hoisted_11, [
      _createElementVNode("button", {
        class: "sr-primary",
        disabled: blocked.value || state.value.session_status !== 'ready' || !state.value.customers_total,
        onClick: startSession
      }, "开始今日经营", 8, _hoisted_12),
      _createElementVNode("label", null, [
        _withDirectives(_createElementVNode("input", {
          type: "checkbox",
          "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((runStaff).value = $event)),
          disabled: blocked.value || !data.value.staff?.unlocked
        }, null, 8, _hoisted_13), [
          [_vModelCheckbox, runStaff.value]
        ]),
        _cache[12] || (_cache[12] = _createTextVNode("运行已雇员工", -1))
      ]),
      _cache[13] || (_cache[13] = _createElementVNode("span", null, "员工按同编号餐位服务。离开面板或标签页进入后台后暂停执行。", -1))
    ]),
    _createElementVNode("nav", _hoisted_14, [
      (_openBlock(), _createElementBlock(_Fragment, null, _renderList(tabs, (tab) => {
        return _createElementVNode("button", {
          key: tab.id,
          class: _normalizeClass({active:activeTab.value===tab.id}),
          onClick: $event => (activeTab.value=tab.id)
        }, _toDisplayString(tab.label), 11, _hoisted_15)
      }), 64))
    ]),
    (activeTab.value === 'kitchen')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
          _createElementVNode("div", _hoisted_16, [
            _cache[14] || (_cache[14] = _createElementVNode("h3", null, "厨房与餐位", -1)),
            _createElementVNode("span", null, "排队 " + _toDisplayString(state.value.queued_customers || 0) + " · 剩余 " + _toDisplayString(state.value.customers_remaining ?? '—'), 1)
          ]),
          _cache[17] || (_cache[17] = _createElementVNode("p", { class: "sr-muted" }, "选择菜品 → 备齐食材与工具 → 开始烹饪 → 上菜。灶台进度保存在 MP 中，刷新页面可继续。", -1)),
          _createElementVNode("div", _hoisted_17, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.kitchen || [], (stove) => {
              return (_openBlock(), _createElementBlock("article", {
                class: "sr-card",
                key: stove.index
              }, [
                _createElementVNode("div", _hoisted_18, [
                  _createElementVNode("h3", null, "灶台 " + _toDisplayString(stove.index), 1),
                  _createElementVNode("span", _hoisted_19, _toDisplayString(stoveStatus(stove)), 1)
                ]),
                _createElementVNode("div", {
                  class: _normalizeClass(["sr-seat", {occupied:customerAt(stove.index)}])
                }, [
                  (cleaningLeft(stove.index)>0)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                        _createTextVNode("🧹 餐位清理中 · " + _toDisplayString(cleaningLeft(stove.index)) + " 秒", 1)
                      ], 64))
                    : (customerAt(stove.index))
                      ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                          _createElementVNode("strong", null, "餐位 " + _toDisplayString(stove.index) + " · " + _toDisplayString(dishName(customerAt(stove.index).dish_key)), 1),
                          _createElementVNode("span", null, "耐心剩余 " + _toDisplayString(patience(customerAt(stove.index))) + " 秒", 1),
                          _createElementVNode("progress", {
                            value: patience(customerAt(stove.index)),
                            max: customerAt(stove.index).patience || 60
                          }, null, 8, _hoisted_20)
                        ], 64))
                      : (_openBlock(), _createElementBlock("span", _hoisted_21, "餐位 " + _toDisplayString(stove.index) + " · 等待顾客", 1))
                ], 2),
                (stove.status==='idle')
                  ? _withDirectives((_openBlock(), _createElementBlock("select", {
                      key: 0,
                      "onUpdate:modelValue": $event => ((selected[stove.index]) = $event),
                      disabled: blocked.value,
                      "aria-label": `灶台 ${stove.index} 菜品`
                    }, [
                      _cache[15] || (_cache[15] = _createElementVNode("option", { value: "" }, "选择菜品", -1)),
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(unlockedDishes.value, (dish) => {
                        return (_openBlock(), _createElementBlock("option", {
                          key: dish.key,
                          value: dish.key
                        }, _toDisplayString(dish.name) + " · " + _toDisplayString(dish.cook_time) + " 秒", 9, _hoisted_23))
                      }), 128))
                    ], 8, _hoisted_22)), [
                      [_vModelSelect, selected[stove.index]]
                    ])
                  : (_openBlock(), _createElementBlock("h4", _hoisted_24, _toDisplayString(dishName(stove.dish_key)), 1)),
                (stove.dish_key)
                  ? (_openBlock(), _createElementBlock("p", _hoisted_25, _toDisplayString(recipeText(stove.dish_key)), 1))
                  : _createCommentVNode("", true),
                _createElementVNode("div", _hoisted_26, [
                  (stove.status==='idle')
                    ? (_openBlock(), _createElementBlock("button", {
                        key: 0,
                        disabled: blocked.value || !selected[stove.index],
                        onClick: $event => (act('assign_dish',{station_index:stove.index,dish_key:selected[stove.index]}))
                      }, "选择菜品", 8, _hoisted_27))
                    : _createCommentVNode("", true),
                  (stove.status==='prepping')
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                        _createElementVNode("button", {
                          disabled: blocked.value,
                          onClick: $event => (act('prepare',{station_index:stove.index}))
                        }, "备齐食材与工具", 8, _hoisted_28),
                        _createElementVNode("button", {
                          class: "sr-primary",
                          disabled: blocked.value || !prepared(stove),
                          onClick: $event => (act('cook',{station_index:stove.index}))
                        }, "开始烹饪", 8, _hoisted_29),
                        _createElementVNode("button", {
                          disabled: blocked.value,
                          onClick: $event => (act('cancel',{station_index:stove.index}))
                        }, "取消", 8, _hoisted_30)
                      ], 64))
                    : _createCommentVNode("", true),
                  (stove.status==='cooking')
                    ? (_openBlock(), _createElementBlock("span", _hoisted_31, "🔥 烹饪中 · " + _toDisplayString(remaining(stove.ready_at)) + " 秒", 1))
                    : _createCommentVNode("", true),
                  (stove.status==='ready')
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                        _withDirectives(_createElementVNode("select", {
                          "onUpdate:modelValue": $event => ((serveTargets[stove.index]) = $event),
                          disabled: blocked.value,
                          "aria-label": `灶台 ${stove.index} 上菜餐位`
                        }, [
                          _cache[16] || (_cache[16] = _createElementVNode("option", { value: "" }, "选择上菜餐位", -1)),
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(matchingCustomers(stove), (c) => {
                            return (_openBlock(), _createElementBlock("option", {
                              key: c.id,
                              value: c.id
                            }, "餐位 " + _toDisplayString(c.seat) + " · " + _toDisplayString(patience(c)) + " 秒", 9, _hoisted_33))
                          }), 128))
                        ], 8, _hoisted_32), [
                          [_vModelSelect, serveTargets[stove.index]]
                        ]),
                        _createElementVNode("button", {
                          class: "sr-primary",
                          disabled: blocked.value || !serveTargets[stove.index],
                          onClick: $event => (act('serve',{station_index:stove.index,customer_id:serveTargets[stove.index]}))
                        }, "上菜", 8, _hoisted_34),
                        _createElementVNode("button", {
                          disabled: blocked.value,
                          onClick: $event => (askReturn(stove))
                        }, "归位", 8, _hoisted_35),
                        _createElementVNode("button", {
                          class: "sr-danger",
                          disabled: blocked.value,
                          onClick: $event => (askDiscard(stove))
                        }, "丢弃", 8, _hoisted_36)
                      ], 64))
                    : _createCommentVNode("", true)
                ]),
                (data.value.staff?.unlocked)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_37, [
                      (_openBlock(), _createElementBlock(_Fragment, null, _renderList(roles, (role) => {
                        return _createElementVNode("button", {
                          key: role.key,
                          class: _normalizeClass({'sr-selected': assigned(stove.index,role.key)}),
                          disabled: blocked.value || (!assigned(stove.index,role.key) && !data.value.staff?.available?.[role.key]),
                          onClick: $event => (act('update_staff_assignment',{station_index:stove.index,role:role.key,assigned:assigned(stove.index,role.key)?0:1}))
                        }, _toDisplayString(role.label) + " · " + _toDisplayString(assigned(stove.index,role.key)?'已上岗':'分配'), 11, _hoisted_38)
                      }), 64))
                    ]))
                  : _createCommentVNode("", true)
              ]))
            }), 128))
          ]),
          (!view.value.kitchen?.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_39, "请先启用插件并刷新餐厅数据。"))
            : _createCommentVNode("", true)
        ], 64))
      : _createCommentVNode("", true),
    (activeTab.value === 'supplies')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
          _cache[18] || (_cache[18] = _createElementVNode("h3", null, "食材商店与仓库", -1)),
          _cache[19] || (_cache[19] = _createElementVNode("p", { class: "sr-muted" }, "可用库存已扣除本插件厨房预留。购买前会显示本次魔力支出。", -1)),
          _createElementVNode("div", _hoisted_40, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.ingredients || [], (item) => {
              return (_openBlock(), _createElementBlock("article", {
                class: "sr-card",
                key: item.key
              }, [
                _createElementVNode("h3", null, _toDisplayString(item.name), 1),
                _createElementVNode("p", null, [
                  _createTextVNode("可用 " + _toDisplayString(number(available(item.key))) + " ", 1),
                  _createElementVNode("small", null, "／总计 " + _toDisplayString(number(data.value.inventory?.ingredients?.[item.key])), 1)
                ]),
                _createElementVNode("p", null, _toDisplayString(number(item.price)) + " 魔力 / 份", 1),
                _createElementVNode("div", _hoisted_41, [
                  _withDirectives(_createElementVNode("input", {
                    type: "number",
                    min: "1",
                    max: "10000",
                    "onUpdate:modelValue": $event => ((quantities[item.key]) = $event),
                    "aria-label": `${item.name}购买数量`
                  }, null, 8, _hoisted_42), [
                    [
                      _vModelText,
                      quantities[item.key],
                      void 0,
                      { number: true }
                    ]
                  ]),
                  _createElementVNode("button", {
                    disabled: blocked.value,
                    onClick: $event => (buy(item))
                  }, "购买", 8, _hoisted_43)
                ])
              ]))
            }), 128))
          ]),
          _cache[20] || (_cache[20] = _createElementVNode("h3", { class: "sr-section-head" }, "菜品手册", -1)),
          _createElementVNode("div", _hoisted_44, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.dishes || [], (dish) => {
              return (_openBlock(), _createElementBlock("article", {
                key: dish.key,
                class: "sr-card"
              }, [
                _createElementVNode("h3", null, _toDisplayString(dish.name), 1),
                _createElementVNode("p", null, _toDisplayString(dish.cook_time) + " 秒 · 售价 " + _toDisplayString(number(dish.sell_price ?? dish.price)) + " 魔力", 1),
                _createElementVNode("p", _hoisted_45, _toDisplayString(recipeText(dish.key)), 1),
                _createElementVNode("span", _hoisted_46, _toDisplayString(state.value.unlocked?.dishes?.includes(dish.key)?'已解锁':`需 ${number(dish.unlock_popularity)} 欢迎值`), 1)
              ]))
            }), 128))
          ]),
          _cache[21] || (_cache[21] = _createElementVNode("h3", { class: "sr-section-head" }, "烹饪工具", -1)),
          _createElementVNode("div", _hoisted_47, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.tools || [], (tool) => {
              return (_openBlock(), _createElementBlock("span", {
                key: tool.key,
                class: "sr-badge"
              }, _toDisplayString(tool.name) + " · " + _toDisplayString(data.value.inventory?.tools?.[tool.key]?'已解锁':'未解锁'), 1))
            }), 128))
          ])
        ], 64))
      : _createCommentVNode("", true),
    (activeTab.value === 'staff')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 4 }, [
          _cache[22] || (_cache[22] = _createElementVNode("h3", null, "员工管理", -1)),
          _cache[23] || (_cache[23] = _createElementVNode("p", { class: "sr-muted" }, "雇佣后在厨房分配到灶台，再开启“运行已雇员工”。每次雇佣 1 人，价格取站点当前报价。", -1)),
          _createElementVNode("div", _hoisted_48, [
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(roles, (role) => {
              return _createElementVNode("article", {
                class: "sr-card",
                key: role.key
              }, [
                _createElementVNode("h3", null, _toDisplayString(role.label), 1),
                _createElementVNode("p", null, "已雇佣 " + _toDisplayString(data.value.staff?.inventory?.[role.key] || 0) + " / " + _toDisplayString(data.value.staff?.capacity?.[role.key] || 0) + " · 空闲 " + _toDisplayString(data.value.staff?.available?.[role.key] || 0), 1),
                _createElementVNode("p", null, "下一位 " + _toDisplayString(number(data.value.staff?.next_prices?.[role.key])) + " 魔力", 1),
                _createElementVNode("button", {
                  disabled: blocked.value || !data.value.staff?.next_prices?.[role.key],
                  onClick: $event => (hire(role))
                }, "雇佣 1 人", 8, _hoisted_49)
              ])
            }), 64))
          ]),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.staff?.packages || [], (pkg, i) => {
            return (_openBlock(), _createElementBlock("p", { key: i }, _toDisplayString(number(pkg.threshold)) + " 欢迎值：厨师 +" + _toDisplayString(pkg.limits?.chef?.count || 0) + "，服务员 +" + _toDisplayString(pkg.limits?.server?.count || 0) + " " + _toDisplayString(pkg.unlocked?'✓':''), 1))
          }), 128))
        ], 64))
      : _createCommentVNode("", true),
    (activeTab.value === 'visits')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 5 }, [
          _createElementVNode("h3", null, [
            _cache[24] || (_cache[24] = _createTextVNode("下馆子 ", -1)),
            _createElementVNode("small", null, "今日 " + _toDisplayString(data.value.visits?.count || 0) + " / " + _toDisplayString(data.value.visits?.limit || 3), 1)
          ]),
          _createElementVNode("section", _hoisted_50, [
            _createElementVNode("div", _hoisted_51, [
              _createElementVNode("h3", null, "自动下馆子 · " + _toDisplayString(view.value.automation?.visit_enabled?'已开启':'已关闭'), 1),
              _createElementVNode("button", {
                onClick: _cache[4] || (_cache[4] = $event => (emit('switch','config')))
              }, "设置名单与通知")
            ]),
            _createElementVNode("p", null, _toDisplayString(view.value.automation?.visits?.message || '可指定最多 3 人；全部留空时每天随机到访 3 人。'), 1),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.automation?.visits?.attempts || {}, (attempt, name) => {
              return (_openBlock(), _createElementBlock("p", {
                key: name,
                class: "sr-muted"
              }, _toDisplayString(attempt.username) + " · " + _toDisplayString(attempt.message), 1))
            }), 128))
          ]),
          _createElementVNode("div", _hoisted_52, [
            _withDirectives(_createElementVNode("input", {
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((targetName).value = $event)),
              maxlength: "64",
              placeholder: "输入餐馆主人用户名",
              "aria-label": "餐馆主人用户名"
            }, null, 512), [
              [
                _vModelText,
                targetName.value,
                void 0,
                { trim: true }
              ]
            ]),
            _createElementVNode("button", {
              disabled: busy.value || !targetName.value,
              onClick: lookup
            }, "查询", 8, _hoisted_53),
            _createElementVNode("button", {
              disabled: busy.value,
              onClick: recommend
            }, "随机推荐", 8, _hoisted_54),
            _createElementVNode("button", {
              class: "sr-primary",
              disabled: blocked.value || !targetName.value,
              onClick: _cache[6] || (_cache[6] = $event => (visit(targetName.value)))
            }, "前往用餐", 8, _hoisted_55)
          ]),
          _createElementVNode("div", _hoisted_56, [
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(recommendations.value, (item) => {
              return (_openBlock(), _createElementBlock("article", {
                key: item.username,
                class: "sr-card"
              }, [
                _createElementVNode("h3", null, _toDisplayString(item.username), 1),
                _createElementVNode("p", null, _toDisplayString(item.message || '可查询餐馆详情后前往'), 1),
                _createElementVNode("button", {
                  disabled: blocked.value || item.can_visit===false,
                  onClick: $event => (visit(item.username))
                }, "前往用餐", 8, _hoisted_57)
              ]))
            }), 128))
          ]),
          _cache[25] || (_cache[25] = _createElementVNode("h3", { class: "sr-section-head" }, "今日到访", -1)),
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.visits?.records || [], (record, i) => {
            return (_openBlock(), _createElementBlock("p", { key: i }, _toDisplayString(record.target_username), 1))
          }), 128))
        ], 64))
      : _createCommentVNode("", true),
    (activeTab.value === 'logs')
      ? (_openBlock(), _createElementBlock(_Fragment, { key: 6 }, [
          _createElementVNode("div", _hoisted_58, [
            _cache[28] || (_cache[28] = _createElementVNode("h3", null, "经营日志", -1)),
            _createElementVNode("label", null, [
              _cache[27] || (_cache[27] = _createTextVNode("最近 ", -1)),
              _withDirectives(_createElementVNode("select", {
                "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((logDays).value = $event))
              }, [...(_cache[26] || (_cache[26] = [
                _createElementVNode("option", { value: 0 }, "全部", -1),
                _createElementVNode("option", { value: 7 }, "7 天", -1),
                _createElementVNode("option", { value: 30 }, "30 天", -1)
              ]))], 512), [
                [
                  _vModelSelect,
                  logDays.value,
                  void 0,
                  { number: true }
                ]
              ])
            ])
          ]),
          _createElementVNode("p", _hoisted_59, "站点返回的 " + _toDisplayString(data.value.logs?.length || 0) + " 条记录；筛选内净收益 " + _toDisplayString(number(filteredLogs.value.reduce((n,r)=>n+Number(r.net_earnings||0),0))) + " 魔力。", 1),
          _createElementVNode("div", _hoisted_60, [
            _createElementVNode("table", null, [
              _cache[29] || (_cache[29] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", null, "日期"),
                  _createElementVNode("th", null, "顾客完成 / 总数"),
                  _createElementVNode("th", null, "欢迎值"),
                  _createElementVNode("th", null, "净收益"),
                  _createElementVNode("th", null, "流失")
                ])
              ], -1)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(filteredLogs.value, (log) => {
                  return (_openBlock(), _createElementBlock("tr", {
                    key: log.log_date
                  }, [
                    _createElementVNode("td", null, _toDisplayString(log.log_date), 1),
                    _createElementVNode("td", null, _toDisplayString(log.customers_served) + " / " + _toDisplayString(log.customers_total), 1),
                    _createElementVNode("td", null, _toDisplayString(number(log.popularity_change)), 1),
                    _createElementVNode("td", null, _toDisplayString(number(log.net_earnings)), 1),
                    _createElementVNode("td", null, _toDisplayString(log.details?.left || 0), 1)
                  ]))
                }), 128))
              ])
            ])
          ]),
          _cache[31] || (_cache[31] = _createElementVNode("h3", { class: "sr-section-head" }, "最近操作", -1)),
          _createElementVNode("div", _hoisted_61, [
            _createElementVNode("table", null, [
              _cache[30] || (_cache[30] = _createElementVNode("thead", null, [
                _createElementVNode("tr", null, [
                  _createElementVNode("th", null, "时间"),
                  _createElementVNode("th", null, "操作"),
                  _createElementVNode("th", null, "结果")
                ])
              ], -1)),
              _createElementVNode("tbody", null, [
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.events || [], (event, i) => {
                  return (_openBlock(), _createElementBlock("tr", { key: i }, [
                    _createElementVNode("td", null, _toDisplayString(new Date(event.time*1000).toLocaleString()), 1),
                    _createElementVNode("td", null, _toDisplayString(actionLabels[event.action] || event.action), 1),
                    _createElementVNode("td", null, _toDisplayString(event.message), 1)
                  ]))
                }), 128))
              ])
            ])
          ])
        ], 64))
      : _createCommentVNode("", true),
    (confirmation.value)
      ? (_openBlock(), _createElementBlock("div", {
          key: 7,
          class: "sr-overlay",
          role: "presentation",
          onClick: _withModifiers(cancelConfirm, ["self"])
        }, [
          _createElementVNode("section", _hoisted_62, [
            _createElementVNode("h3", _hoisted_63, _toDisplayString(confirmation.value.title), 1),
            _createElementVNode("p", null, _toDisplayString(confirmation.value.text), 1),
            _createElementVNode("div", { class: "sr-actions" }, [
              _createElementVNode("button", { onClick: cancelConfirm }, "取消"),
              _createElementVNode("button", {
                class: "sr-primary",
                onClick: acceptConfirm
              }, "确认")
            ])
          ])
        ]))
      : _createCommentVNode("", true)
  ]))
}
}

};

export { _sfc_main as default };

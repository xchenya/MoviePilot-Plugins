import { importShared } from './__federation_fn_import-054b33c3.js';
import './style-de941daf.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,normalizeStyle:_normalizeStyle,normalizeClass:_normalizeClass,withKeys:_withKeys} = await importShared('vue');


const _hoisted_1 = { class: "sr-app sr-page" };
const _hoisted_2 = { class: "sr-topbar" };
const _hoisted_3 = { class: "sr-topbar-left" };
const _hoisted_4 = { class: "sr-topbar-icon" };
const _hoisted_5 = { class: "sr-topbar-copy" };
const _hoisted_6 = { class: "sr-alert-row" };
const _hoisted_7 = { class: "sr-stats" };
const _hoisted_8 = { class: "sr-stat-icon" };
const _hoisted_9 = {
  class: "sr-card sr-automation",
  "aria-label": "后台自动经营状态"
};
const _hoisted_10 = { class: "sr-card-title sr-card-band" };
const _hoisted_11 = { class: "sr-card-body sr-automation-body" };
const _hoisted_12 = { class: "sr-hint" };
const _hoisted_13 = { class: "sr-budget-meter" };
const _hoisted_14 = {
  key: 3,
  class: "sr-stack"
};
const _hoisted_15 = { class: "sr-card" };
const _hoisted_16 = { class: "sr-card-title sr-card-band sr-band-brown" };
const _hoisted_17 = { class: "sr-actions" };
const _hoisted_18 = { class: "sr-card-body sr-stack" };
const _hoisted_19 = { class: "sr-toolbar" };
const _hoisted_20 = { class: "sr-hint" };
const _hoisted_21 = { class: "sr-kitchen-grid" };
const _hoisted_22 = { class: "sr-card-title" };
const _hoisted_23 = { key: 1 };
const _hoisted_24 = {
  key: 2,
  class: "sr-hint"
};
const _hoisted_25 = { class: "sr-actions sr-wrap" };
const _hoisted_26 = {
  key: 3,
  class: "sr-staff-actions"
};
const _hoisted_27 = {
  key: 0,
  class: "sr-empty"
};
const _hoisted_28 = {
  key: 4,
  class: "sr-stack"
};
const _hoisted_29 = { class: "sr-card" };
const _hoisted_30 = { class: "sr-card-title sr-card-band sr-band-orange" };
const _hoisted_31 = { class: "sr-card-body sr-grid" };
const _hoisted_32 = { class: "sr-inventory-value" };
const _hoisted_33 = { class: "sr-actions" };
const _hoisted_34 = {
  key: 0,
  class: "sr-empty"
};
const _hoisted_35 = { class: "sr-card" };
const _hoisted_36 = { class: "sr-card-title sr-card-band" };
const _hoisted_37 = { class: "sr-card-body sr-grid" };
const _hoisted_38 = { class: "sr-hint" };
const _hoisted_39 = { class: "sr-tools" };
const _hoisted_40 = {
  key: 5,
  class: "sr-card"
};
const _hoisted_41 = { class: "sr-card-title sr-card-band sr-band-blue" };
const _hoisted_42 = { class: "sr-card-body sr-stack" };
const _hoisted_43 = { class: "sr-staff-grid" };
const _hoisted_44 = { class: "sr-card-title" };
const _hoisted_45 = {
  key: 6,
  class: "sr-stack"
};
const _hoisted_46 = { class: "sr-card" };
const _hoisted_47 = { class: "sr-card-title sr-card-band sr-band-pink" };
const _hoisted_48 = { class: "sr-card-body sr-stack" };
const _hoisted_49 = { class: "sr-visit-status" };
const _hoisted_50 = { class: "sr-hint" };
const _hoisted_51 = {
  key: 0,
  class: "sr-visit-results"
};
const _hoisted_52 = { class: "sr-hint" };
const _hoisted_53 = { class: "sr-visit-search" };
const _hoisted_54 = {
  key: 1,
  class: "sr-hint"
};
const _hoisted_55 = {
  key: 2,
  class: "sr-grid"
};
const _hoisted_56 = { class: "sr-hint" };
const _hoisted_57 = { class: "sr-card" };
const _hoisted_58 = { class: "sr-card-title sr-card-band" };
const _hoisted_59 = { class: "sr-card-body sr-actions sr-wrap" };
const _hoisted_60 = {
  key: 0,
  class: "sr-hint"
};
const _hoisted_61 = {
  key: 7,
  class: "sr-stack"
};
const _hoisted_62 = { class: "sr-card" };
const _hoisted_63 = { class: "sr-card-title sr-card-band sr-band-blue" };
const _hoisted_64 = { class: "sr-card-body" };
const _hoisted_65 = { class: "sr-hint" };
const _hoisted_66 = { key: 0 };
const _hoisted_67 = { class: "sr-card" };
const _hoisted_68 = { class: "sr-card-title sr-card-band" };
const _hoisted_69 = { class: "sr-event-message" };
const _hoisted_70 = { key: 0 };

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
const fastPolling = computed(()=>state.value.session_status==='open' || (view.value.kitchen || []).some(stove=>stove.status==='cooking') || Object.keys(view.value.cleaning || {}).length>0);
const blocked = computed(()=>busy.value || !!view.value.uncertain || !!view.value.automation?.enabled || !!view.value.automation?.active || !data.value.state);
const uiDefaults = { VBtn: { size: 'small', variant: 'tonal', color: 'success' }, VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VSelect: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VChip: { size: 'x-small', variant: 'tonal' } };
const dishOptions = computed(()=>unlockedDishes.value.map(d=>({title:`${d.name} · ${d.cook_time} 秒`,value:d.key})));
const seatOptions = stove=>matchingCustomers(stove).map(c=>({title:`餐位 ${c.seat} · ${patience(c)} 秒`,value:c.id}));
const tabs = [{id:'kitchen',label:'厨房与餐位',icon:'mdi-stove'},{id:'supplies',label:'食材与菜品',icon:'mdi-basket-outline'},{id:'staff',label:'员工',icon:'mdi-account-tie-outline'},{id:'visits',label:'下馆子',icon:'mdi-silverware-fork-knife'},{id:'logs',label:'经营日志',icon:'mdi-text-box-outline'}];
const roles = [{key:'chef',label:'厨师',icon:'mdi-chef-hat'},{key:'server',label:'服务员',icon:'mdi-account-tie-outline'}];
const actionLabels = {purchase_ingredient:'购买食材',hire_staff:'雇佣员工',update_staff_assignment:'员工调度',start_session:'开始营业',visit_restaurant:'下馆子',serve_customer:'上菜',discard_dish:'丢弃菜品',customer_left:'顾客离席',resolve:'核对解锁',automation:'自动经营',auto_visit:'自动下馆子',notification:'通知'};
const number = n => Number(n || 0).toLocaleString();
const statusLabel = computed(()=>({ready:'准备营业',open:'营业中',closed:'已闭店'}[state.value.session_status] || '未连接'));
const stats = computed(()=>[{label:'魔力余额',icon:'mdi-auto-fix',accent:'245,158,11',value:number(data.value.user?.magic)},{label:'受欢迎值',icon:'mdi-heart-outline',accent:'236,72,153',value:number(state.value.popularity)},{label:'今日顾客',icon:'mdi-account-group-outline',accent:'34,197,94',value:`${state.value.customers_served || 0} / ${state.value.customers_total || 0}`},{label:'今日净收益',icon:'mdi-cash-plus',accent:'59,130,246',value:number(state.value.net_earnings_today)},{label:'累计净收益',icon:'mdi-chart-line',accent:'139,92,246',value:number(state.value.net_earnings_total)}]);
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
async function request(path,payload,verb='post',quiet=false){if(busy.value)return null;busy.value=true;try{const r=unwrap(await props.api[verb](`plugin/${props.pluginId}${path}`,payload));update(r);if(!quiet || !r.success){message.value=r.message || (r.success?'操作完成':'操作失败');ok.value=r.success;}return r}catch(e){if(alive){message.value=e.message || '请求失败，请刷新后核对';ok.value=false;runStaff.value=false;}return null}finally{busy.value=false;schedule();}}
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
function clearTimers(){clearTimeout(timer);clearInterval(clock);timer=null;clock=null;}
function schedule(){
  clearTimers();
  if(!alive || document.hidden)return
  timer=setTimeout(poll,fastPolling.value?2000:60000);
  // Only running kitchen tasks need a local countdown between responses.
  if(fastPolling.value)clock=setInterval(()=>{now.value=Date.now()/1000+clockOffset;},500);
}
async function poll(){
  if(!alive)return
  if(document.hidden || busy.value || confirmation.value){schedule();return}
  if(!data.value.state || view.value.automation?.active || view.value.automation?.enabled)await request('/state',undefined,'get',true);
  else await request('/tick',{run_staff:runStaff.value},'post',true);
}
function visibilityChanged(){
  if(document.hidden){clearTimers();return}
  if(alive && !busy.value && !confirmation.value)request('/state',undefined,'get',true);
  else schedule();
}
function start(){if(alive)return;alive=true;document.addEventListener('visibilitychange',visibilityChanged);if(!document.hidden)request('/state',undefined,'get',true);}
function stop(){alive=false;runStaff.value=false;clearTimers();document.removeEventListener('visibilitychange',visibilityChanged);cancelConfirm();}
onMounted(start);onActivated(start);onDeactivated(stop);onUnmounted(stop);

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_btn_group = _resolveComponent("v-btn-group");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_table = _resolveComponent("v-table");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_dialog = _resolveComponent("v-dialog");
  const _component_v_defaults_provider = _resolveComponent("v-defaults-provider");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createVNode(_component_v_defaults_provider, { defaults: uiDefaults }, {
      default: _withCtx(() => [
        _createElementVNode("header", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _createElementVNode("div", _hoisted_4, [
              _createVNode(_component_v_icon, {
                icon: "mdi-silverware-fork-knife",
                size: "24"
              })
            ]),
            _createElementVNode("div", _hoisted_5, [
              _createElementVNode("h2", null, [
                _cache[12] || (_cache[12] = _createTextVNode("思齐餐厅 ", -1)),
                _createVNode(_component_v_chip, {
                  color: state.value.session_status==='open'?'success':'default'
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(statusLabel.value), 1)
                  ]),
                  _: 1
                }, 8, ["color"])
              ]),
              _createElementVNode("p", null, _toDisplayString(data.value.state ? (fastPolling.value ? '营业或烹饪中，每 2 秒更新状态' : '空闲中，每 60 秒更新状态') : '管理厨房、食材、员工与餐厅互动'), 1)
            ])
          ]),
          _createVNode(_component_v_btn_group, {
            variant: "tonal",
            density: "compact",
            class: "sr-topbar-actions"
          }, {
            default: _withCtx(() => [
              _createVNode(_component_v_btn, {
                color: "success",
                "aria-label": "刷新",
                title: "刷新",
                onClick: refresh,
                loading: busy.value,
                disabled: busy.value
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-refresh",
                    size: "18"
                  }),
                  _cache[13] || (_cache[13] = _createElementVNode("span", null, "刷新", -1))
                ]),
                _: 1
              }, 8, ["loading", "disabled"]),
              _createVNode(_component_v_btn, {
                color: "success",
                "aria-label": "配置",
                title: "配置",
                onClick: _cache[0] || (_cache[0] = $event => (emit('switch','config')))
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-cog-outline",
                    size: "18"
                  }),
                  _cache[14] || (_cache[14] = _createElementVNode("span", null, "配置", -1))
                ]),
                _: 1
              }),
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
                  _cache[15] || (_cache[15] = _createElementVNode("span", null, "关闭", -1))
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
              type: ok.value?'success':'error',
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
        (view.value.uncertain)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 1,
              type: "warning",
              variant: "tonal",
              density: "compact"
            }, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_6, [
                  _cache[17] || (_cache[17] = _createElementVNode("span", null, "上次站点操作结果不明，已暂停写入。请先刷新并核对网站。", -1)),
                  _createVNode(_component_v_btn, {
                    color: "warning",
                    onClick: resolveUncertain,
                    disabled: busy.value
                  }, {
                    default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                      _createTextVNode("已核对，解除锁定", -1)
                    ]))]),
                    _: 1
                  }, 8, ["disabled"])
                ])
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        (busy.value && !data.value.state)
          ? (_openBlock(), _createBlock(_component_v_progress_linear, {
              key: 2,
              indeterminate: "",
              color: "success",
              "aria-label": "读取餐厅"
            }))
          : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_7, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(stats.value, (item) => {
            return (_openBlock(), _createElementBlock("article", {
              key: item.label,
              class: "sr-stat",
              style: _normalizeStyle({'--sr-accent':item.accent})
            }, [
              _createElementVNode("div", _hoisted_8, [
                _createVNode(_component_v_icon, {
                  icon: item.icon,
                  size: "22"
                }, null, 8, ["icon"])
              ]),
              _createElementVNode("div", null, [
                _createElementVNode("span", null, _toDisplayString(item.label), 1),
                _createElementVNode("strong", null, _toDisplayString(data.value.state?item.value:'—'), 1)
              ])
            ], 4))
          }), 128))
        ]),
        _createElementVNode("section", _hoisted_9, [
          _createElementVNode("div", _hoisted_10, [
            _createElementVNode("h3", null, [
              _createVNode(_component_v_icon, {
                icon: "mdi-robot-outline",
                size: "19",
                color: "success"
              }),
              _cache[18] || (_cache[18] = _createTextVNode("后台自动经营 ", -1)),
              _createVNode(_component_v_chip, {
                color: view.value.automation?.enabled?'success':'default'
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(view.value.automation?.enabled?'已开启':'已暂停'), 1)
                ]),
                _: 1
              }, 8, ["color"])
            ]),
            _createVNode(_component_v_btn, {
              variant: "text",
              "prepend-icon": "mdi-tune-variant",
              onClick: _cache[3] || (_cache[3] = $event => (emit('switch','config')))
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(view.value.automation?.enabled?'暂停 / 调整托管':'设置自动经营'), 1)
              ]),
              _: 1
            })
          ]),
          _createElementVNode("div", _hoisted_11, [
            _createElementVNode("div", null, [
              _createElementVNode("p", null, _toDisplayString(view.value.automation?.enabled ? (view.value.automation.message || '等待后台首次检查') : '可在配置中开启每日自动经营。'), 1),
              _createElementVNode("p", _hoisted_12, _toDisplayString(view.value.automation?.last_check ? `最近检查 ${new Date(view.value.automation.last_check*1000).toLocaleTimeString()}` : '等待后台检查') + " · 关闭页面后继续运行", 1)
            ]),
            _createElementVNode("div", _hoisted_13, [
              _createElementVNode("div", null, [
                _cache[19] || (_cache[19] = _createElementVNode("span", null, "今日补货预算", -1)),
                _createElementVNode("strong", null, _toDisplayString(number(view.value.automation?.spent)) + " / " + _toDisplayString(number(view.value.automation?.daily_budget)), 1)
              ]),
              _createVNode(_component_v_progress_linear, {
                "model-value": Math.min(100,Number(view.value.automation?.spent||0)/Math.max(1,Number(view.value.automation?.daily_budget||0))*100),
                color: "success",
                height: "5",
                rounded: "",
                "aria-label": "今日补货预算使用比例"
              }, null, 8, ["model-value"])
            ])
          ])
        ]),
        _createVNode(_component_v_tabs, {
          modelValue: activeTab.value,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((activeTab).value = $event)),
          color: "success",
          density: "compact",
          "show-arrows": "",
          class: "sr-tabs",
          "aria-label": "餐厅功能"
        }, {
          default: _withCtx(() => [
            (_openBlock(), _createElementBlock(_Fragment, null, _renderList(tabs, (tab) => {
              return _createVNode(_component_v_tab, {
                key: tab.id,
                value: tab.id,
                "prepend-icon": tab.icon
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(tab.label), 1)
                ]),
                _: 2
              }, 1032, ["value", "prepend-icon"])
            }), 64))
          ]),
          _: 1
        }, 8, ["modelValue"]),
        (activeTab.value==='kitchen')
          ? (_openBlock(), _createElementBlock("div", _hoisted_14, [
              _createElementVNode("section", _hoisted_15, [
                _createElementVNode("div", _hoisted_16, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-stove",
                      size: "19"
                    }),
                    _cache[20] || (_cache[20] = _createTextVNode("厨房与餐位", -1))
                  ]),
                  _createElementVNode("div", _hoisted_17, [
                    _createVNode(_component_v_chip, null, {
                      default: _withCtx(() => [
                        _createTextVNode("排队 " + _toDisplayString(state.value.queued_customers || 0), 1)
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_chip, null, {
                      default: _withCtx(() => [
                        _createTextVNode("剩余 " + _toDisplayString(state.value.customers_remaining ?? '—'), 1)
                      ]),
                      _: 1
                    })
                  ])
                ]),
                _createElementVNode("div", _hoisted_18, [
                  _createElementVNode("div", _hoisted_19, [
                    _createVNode(_component_v_btn, {
                      "prepend-icon": "mdi-storefront-outline",
                      disabled: blocked.value || state.value.session_status!=='ready' || !state.value.customers_total,
                      onClick: startSession
                    }, {
                      default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                        _createTextVNode("开始今日经营", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_v_switch, {
                      modelValue: runStaff.value,
                      "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((runStaff).value = $event)),
                      label: "运行已雇员工",
                      color: "success",
                      "hide-details": "",
                      density: "compact",
                      disabled: blocked.value || !data.value.staff?.unlocked
                    }, null, 8, ["modelValue", "disabled"]),
                    _createElementVNode("span", _hoisted_20, _toDisplayString(view.value.automation?.active || view.value.automation?.enabled?'后台托管中，手动操作已暂停':'员工按同编号餐位服务，仅在页面可见时执行'), 1)
                  ]),
                  _createElementVNode("div", _hoisted_21, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.kitchen || [], (stove) => {
                      return (_openBlock(), _createElementBlock("article", {
                        key: stove.index,
                        class: _normalizeClass(["sr-stove", `sr-stove-${stove.status}`])
                      }, [
                        _createElementVNode("div", _hoisted_22, [
                          _createElementVNode("h3", null, [
                            _createVNode(_component_v_icon, {
                              icon: "mdi-fire",
                              size: "18",
                              color: stove.status==='idle'?'#9e9e9e':'#f59e0b'
                            }, null, 8, ["color"]),
                            _createTextVNode("灶台 " + _toDisplayString(stove.index), 1)
                          ]),
                          _createVNode(_component_v_chip, {
                            color: stove.status==='ready'?'success':stove.status==='idle'?'default':'#f59e0b'
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(stoveStatus(stove)), 1)
                            ]),
                            _: 2
                          }, 1032, ["color"])
                        ]),
                        _createElementVNode("div", {
                          class: _normalizeClass(["sr-seat", {occupied:customerAt(stove.index)}])
                        }, [
                          (cleaningLeft(stove.index)>0)
                            ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                _createVNode(_component_v_icon, {
                                  icon: "mdi-broom",
                                  size: "20"
                                }),
                                _createTextVNode("餐位清理中 · " + _toDisplayString(cleaningLeft(stove.index)) + " 秒", 1)
                              ], 64))
                            : (customerAt(stove.index))
                              ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                                  _createElementVNode("strong", null, "餐位 " + _toDisplayString(stove.index) + " · " + _toDisplayString(dishName(customerAt(stove.index).dish_key)), 1),
                                  _createElementVNode("span", null, "耐心剩余 " + _toDisplayString(patience(customerAt(stove.index))) + " 秒", 1),
                                  _createVNode(_component_v_progress_linear, {
                                    "model-value": Math.min(100,patience(customerAt(stove.index))/(customerAt(stove.index).patience||60)*100),
                                    color: "success",
                                    height: "4",
                                    rounded: ""
                                  }, null, 8, ["model-value"])
                                ], 64))
                              : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                                  _createVNode(_component_v_icon, {
                                    icon: "mdi-seat-outline",
                                    size: "22"
                                  }),
                                  _createElementVNode("span", null, "餐位 " + _toDisplayString(stove.index) + " · 等待顾客", 1)
                                ], 64))
                        ], 2),
                        (stove.status==='idle')
                          ? (_openBlock(), _createBlock(_component_v_select, {
                              key: 0,
                              modelValue: selected[stove.index],
                              "onUpdate:modelValue": $event => ((selected[stove.index]) = $event),
                              items: dishOptions.value,
                              label: "选择菜品",
                              "aria-label": `灶台 ${stove.index} 菜品`,
                              disabled: blocked.value
                            }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "aria-label", "disabled"]))
                          : (_openBlock(), _createElementBlock("h4", _hoisted_23, _toDisplayString(dishName(stove.dish_key)), 1)),
                        (stove.dish_key)
                          ? (_openBlock(), _createElementBlock("p", _hoisted_24, _toDisplayString(recipeText(stove.dish_key)), 1))
                          : _createCommentVNode("", true),
                        _createElementVNode("div", _hoisted_25, [
                          (stove.status==='idle')
                            ? (_openBlock(), _createBlock(_component_v_btn, {
                                key: 0,
                                disabled: blocked.value || !selected[stove.index],
                                onClick: $event => (act('assign_dish',{station_index:stove.index,dish_key:selected[stove.index]}))
                              }, {
                                default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                                  _createTextVNode("选择菜品", -1)
                                ]))]),
                                _: 1
                              }, 8, ["disabled", "onClick"]))
                            : _createCommentVNode("", true),
                          (stove.status==='prepping')
                            ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                                _createVNode(_component_v_btn, {
                                  disabled: blocked.value,
                                  onClick: $event => (act('prepare',{station_index:stove.index}))
                                }, {
                                  default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                                    _createTextVNode("备齐食材与工具", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"]),
                                _createVNode(_component_v_btn, {
                                  disabled: blocked.value || !prepared(stove),
                                  onClick: $event => (act('cook',{station_index:stove.index}))
                                }, {
                                  default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                                    _createTextVNode("开始烹饪", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"]),
                                _createVNode(_component_v_btn, {
                                  color: "default",
                                  variant: "text",
                                  disabled: blocked.value,
                                  onClick: $event => (act('cancel',{station_index:stove.index}))
                                }, {
                                  default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
                                    _createTextVNode("取消", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"])
                              ], 64))
                            : _createCommentVNode("", true),
                          (stove.status==='cooking')
                            ? (_openBlock(), _createBlock(_component_v_chip, {
                                key: 2,
                                color: "#f59e0b",
                                "prepend-icon": "mdi-timer-sand"
                              }, {
                                default: _withCtx(() => [
                                  _createTextVNode("烹饪中 · " + _toDisplayString(remaining(stove.ready_at)) + " 秒", 1)
                                ]),
                                _: 2
                              }, 1024))
                            : _createCommentVNode("", true),
                          (stove.status==='ready')
                            ? (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                                _createVNode(_component_v_select, {
                                  modelValue: serveTargets[stove.index],
                                  "onUpdate:modelValue": $event => ((serveTargets[stove.index]) = $event),
                                  items: seatOptions(stove),
                                  label: "上菜餐位",
                                  class: "sr-full-width",
                                  disabled: blocked.value,
                                  "aria-label": `灶台 ${stove.index} 上菜餐位`
                                }, null, 8, ["modelValue", "onUpdate:modelValue", "items", "disabled", "aria-label"]),
                                _createVNode(_component_v_btn, {
                                  disabled: blocked.value || !serveTargets[stove.index],
                                  onClick: $event => (act('serve',{station_index:stove.index,customer_id:serveTargets[stove.index]}))
                                }, {
                                  default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                                    _createTextVNode("上菜", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"]),
                                _createVNode(_component_v_btn, {
                                  color: "default",
                                  disabled: blocked.value,
                                  onClick: $event => (askReturn(stove))
                                }, {
                                  default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                                    _createTextVNode("归位", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"]),
                                _createVNode(_component_v_btn, {
                                  color: "error",
                                  variant: "text",
                                  disabled: blocked.value,
                                  onClick: $event => (askDiscard(stove))
                                }, {
                                  default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                                    _createTextVNode("丢弃", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled", "onClick"])
                              ], 64))
                            : _createCommentVNode("", true)
                        ]),
                        (data.value.staff?.unlocked)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_26, [
                              (_openBlock(), _createElementBlock(_Fragment, null, _renderList(roles, (role) => {
                                return _createVNode(_component_v_btn, {
                                  key: role.key,
                                  "prepend-icon": role.icon,
                                  color: assigned(stove.index,role.key)?'success':'default',
                                  size: "x-small",
                                  disabled: blocked.value || (!assigned(stove.index,role.key) && !data.value.staff?.available?.[role.key]),
                                  onClick: $event => (act('update_staff_assignment',{station_index:stove.index,role:role.key,assigned:assigned(stove.index,role.key)?0:1}))
                                }, {
                                  default: _withCtx(() => [
                                    _createTextVNode(_toDisplayString(role.label) + " · " + _toDisplayString(assigned(stove.index,role.key)?'已上岗':'分配'), 1)
                                  ]),
                                  _: 2
                                }, 1032, ["prepend-icon", "color", "disabled", "onClick"])
                              }), 64))
                            ]))
                          : _createCommentVNode("", true)
                      ], 2))
                    }), 128))
                  ]),
                  (!view.value.kitchen?.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_27, [
                        _createVNode(_component_v_icon, {
                          icon: "mdi-storefront-outline",
                          size: "32"
                        }),
                        _cache[29] || (_cache[29] = _createElementVNode("p", null, "请先启用插件并刷新餐厅数据", -1))
                      ]))
                    : _createCommentVNode("", true),
                  _cache[30] || (_cache[30] = _createElementVNode("p", { class: "sr-hint" }, "选择菜品 → 备齐食材与工具 → 开始烹饪 → 上菜。刷新页面可继续厨房进度。", -1))
                ])
              ])
            ]))
          : _createCommentVNode("", true),
        (activeTab.value==='supplies')
          ? (_openBlock(), _createElementBlock("div", _hoisted_28, [
              _createElementVNode("section", _hoisted_29, [
                _createElementVNode("div", _hoisted_30, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-basket-outline",
                      size: "19"
                    }),
                    _cache[31] || (_cache[31] = _createTextVNode("食材商店与仓库", -1))
                  ]),
                  _cache[32] || (_cache[32] = _createElementVNode("span", { class: "sr-hint" }, "可用库存已扣除厨房预留", -1))
                ]),
                _createElementVNode("div", _hoisted_31, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.ingredients || [], (item) => {
                    return (_openBlock(), _createElementBlock("article", {
                      class: "sr-item",
                      key: item.key
                    }, [
                      _createElementVNode("h3", null, [
                        _createTextVNode(_toDisplayString(item.name), 1),
                        _createVNode(_component_v_chip, { color: "#f59e0b" }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(number(item.price)) + " 魔力 / 份", 1)
                          ]),
                          _: 2
                        }, 1024)
                      ]),
                      _createElementVNode("p", _hoisted_32, [
                        _createTextVNode(_toDisplayString(number(available(item.key))), 1),
                        _createElementVNode("span", null, " 可用 / " + _toDisplayString(number(data.value.inventory?.ingredients?.[item.key])) + " 总计", 1)
                      ]),
                      _createElementVNode("div", _hoisted_33, [
                        _createVNode(_component_v_text_field, {
                          modelValue: quantities[item.key],
                          "onUpdate:modelValue": $event => ((quantities[item.key]) = $event),
                          modelModifiers: { number: true },
                          type: "number",
                          min: "1",
                          max: "10000",
                          label: "数量",
                          "aria-label": `${item.name}购买数量`
                        }, null, 8, ["modelValue", "onUpdate:modelValue", "aria-label"]),
                        _createVNode(_component_v_btn, {
                          color: "#f59e0b",
                          disabled: blocked.value,
                          onClick: $event => (buy(item))
                        }, {
                          default: _withCtx(() => [...(_cache[33] || (_cache[33] = [
                            _createTextVNode("购买", -1)
                          ]))]),
                          _: 1
                        }, 8, ["disabled", "onClick"])
                      ])
                    ]))
                  }), 128)),
                  (!data.value.config?.ingredients?.length)
                    ? (_openBlock(), _createElementBlock("p", _hoisted_34, "暂无食材数据，请刷新餐厅"))
                    : _createCommentVNode("", true)
                ])
              ]),
              _createElementVNode("section", _hoisted_35, [
                _createElementVNode("div", _hoisted_36, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-book-open-page-variant-outline",
                      size: "19"
                    }),
                    _cache[34] || (_cache[34] = _createTextVNode("菜品手册", -1))
                  ])
                ]),
                _createElementVNode("div", _hoisted_37, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.dishes || [], (dish) => {
                    return (_openBlock(), _createElementBlock("article", {
                      key: dish.key,
                      class: "sr-item"
                    }, [
                      _createElementVNode("h3", null, [
                        _createTextVNode(_toDisplayString(dish.name), 1),
                        _createVNode(_component_v_chip, {
                          color: state.value.unlocked?.dishes?.includes(dish.key)?'success':'default'
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(state.value.unlocked?.dishes?.includes(dish.key)?'已解锁':`需 ${number(dish.unlock_popularity)} 欢迎值`), 1)
                          ]),
                          _: 2
                        }, 1032, ["color"])
                      ]),
                      _createElementVNode("p", null, _toDisplayString(dish.cook_time) + " 秒 · 售价 " + _toDisplayString(number(dish.sell_price ?? dish.price)) + " 魔力", 1),
                      _createElementVNode("p", _hoisted_38, _toDisplayString(recipeText(dish.key)), 1)
                    ]))
                  }), 128))
                ]),
                _createElementVNode("div", _hoisted_39, [
                  _cache[35] || (_cache[35] = _createElementVNode("span", { class: "sr-hint" }, "烹饪工具", -1)),
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.tools || [], (tool) => {
                    return (_openBlock(), _createBlock(_component_v_chip, {
                      key: tool.key,
                      color: data.value.inventory?.tools?.[tool.key]?'success':'default'
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(tool.name) + " · " + _toDisplayString(data.value.inventory?.tools?.[tool.key]?'已解锁':'未解锁'), 1)
                      ]),
                      _: 2
                    }, 1032, ["color"]))
                  }), 128))
                ])
              ])
            ]))
          : _createCommentVNode("", true),
        (activeTab.value==='staff')
          ? (_openBlock(), _createElementBlock("section", _hoisted_40, [
              _createElementVNode("div", _hoisted_41, [
                _createElementVNode("h3", null, [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-account-group-outline",
                    size: "19"
                  }),
                  _cache[36] || (_cache[36] = _createTextVNode("员工管理", -1))
                ])
              ]),
              _createElementVNode("div", _hoisted_42, [
                _cache[38] || (_cache[38] = _createElementVNode("p", { class: "sr-hint" }, "雇佣后在厨房分配到灶台，再开启“运行已雇员工”。每次雇佣 1 人，使用站点当前报价。", -1)),
                _createElementVNode("div", _hoisted_43, [
                  (_openBlock(), _createElementBlock(_Fragment, null, _renderList(roles, (role) => {
                    return _createElementVNode("article", {
                      key: role.key,
                      class: "sr-item"
                    }, [
                      _createElementVNode("h3", null, [
                        _createVNode(_component_v_icon, {
                          icon: role.icon,
                          color: "info"
                        }, null, 8, ["icon"]),
                        _createTextVNode(_toDisplayString(role.label), 1)
                      ]),
                      _createElementVNode("p", null, "已雇佣 " + _toDisplayString(data.value.staff?.inventory?.[role.key] || 0) + " / " + _toDisplayString(data.value.staff?.capacity?.[role.key] || 0) + " · 空闲 " + _toDisplayString(data.value.staff?.available?.[role.key] || 0), 1),
                      _createElementVNode("div", _hoisted_44, [
                        _createElementVNode("strong", null, "下一位 " + _toDisplayString(number(data.value.staff?.next_prices?.[role.key])) + " 魔力", 1),
                        _createVNode(_component_v_btn, {
                          color: "info",
                          disabled: blocked.value || !data.value.staff?.next_prices?.[role.key],
                          onClick: $event => (hire(role))
                        }, {
                          default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                            _createTextVNode("雇佣 1 人", -1)
                          ]))]),
                          _: 1
                        }, 8, ["disabled", "onClick"])
                      ])
                    ])
                  }), 64))
                ]),
                (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.config?.staff?.packages || [], (pkg, i) => {
                  return (_openBlock(), _createElementBlock("p", {
                    key: i,
                    class: "sr-hint"
                  }, _toDisplayString(number(pkg.threshold)) + " 欢迎值：厨师 +" + _toDisplayString(pkg.limits?.chef?.count || 0) + "，服务员 +" + _toDisplayString(pkg.limits?.server?.count || 0) + " " + _toDisplayString(pkg.unlocked?'· 已解锁':''), 1))
                }), 128))
              ])
            ]))
          : _createCommentVNode("", true),
        (activeTab.value==='visits')
          ? (_openBlock(), _createElementBlock("div", _hoisted_45, [
              _createElementVNode("section", _hoisted_46, [
                _createElementVNode("div", _hoisted_47, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-silverware-fork-knife",
                      size: "19"
                    }),
                    _cache[39] || (_cache[39] = _createTextVNode("下馆子 ", -1)),
                    _createVNode(_component_v_chip, { color: "#ec4899" }, {
                      default: _withCtx(() => [
                        _createTextVNode("今日 " + _toDisplayString(data.value.visits?.count || 0) + " / " + _toDisplayString(data.value.visits?.limit || 3), 1)
                      ]),
                      _: 1
                    })
                  ]),
                  _createVNode(_component_v_btn, {
                    color: "#ec4899",
                    variant: "text",
                    "prepend-icon": "mdi-tune-variant",
                    onClick: _cache[6] || (_cache[6] = $event => (emit('switch','config')))
                  }, {
                    default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                      _createTextVNode("设置名单与通知", -1)
                    ]))]),
                    _: 1
                  })
                ]),
                _createElementVNode("div", _hoisted_48, [
                  _createElementVNode("div", _hoisted_49, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-robot-outline",
                      color: "#ec4899",
                      size: "24"
                    }),
                    _createElementVNode("div", null, [
                      _createElementVNode("h3", null, "自动下馆子 · " + _toDisplayString(view.value.automation?.visit_enabled?'已开启':'已关闭'), 1),
                      _createElementVNode("p", _hoisted_50, _toDisplayString(view.value.automation?.visits?.message || '可指定最多 3 人；全部留空时每天随机到访 3 人。'), 1)
                    ])
                  ]),
                  (Object.keys(view.value.automation?.visits?.attempts || {}).length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_51, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(view.value.automation.visits.attempts, (attempt, name) => {
                          return (_openBlock(), _createElementBlock("div", {
                            key: name,
                            class: "sr-visit-result"
                          }, [
                            _createVNode(_component_v_icon, {
                              icon: "mdi-account-circle-outline",
                              color: "#ec4899",
                              size: "22"
                            }),
                            _createElementVNode("div", null, [
                              _createElementVNode("strong", null, _toDisplayString(attempt.username), 1),
                              _createElementVNode("p", _hoisted_52, _toDisplayString(attempt.message), 1)
                            ])
                          ]))
                        }), 128))
                      ]))
                    : _createCommentVNode("", true),
                  _createElementVNode("div", _hoisted_53, [
                    _createVNode(_component_v_text_field, {
                      modelValue: targetName.value,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((targetName).value = $event)),
                      modelModifiers: { trim: true },
                      maxlength: "64",
                      label: "餐馆主人用户名",
                      "aria-label": "餐馆主人用户名",
                      "prepend-inner-icon": "mdi-account-search-outline",
                      onKeydown: _cache[8] || (_cache[8] = _withKeys($event => (targetName.value && !busy.value && lookup()), ["enter"]))
                    }, null, 8, ["modelValue"]),
                    _createVNode(_component_v_btn, {
                      color: "#ec4899",
                      disabled: busy.value || !targetName.value,
                      onClick: lookup
                    }, {
                      default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                        _createTextVNode("查询", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_v_btn, {
                      color: "#8b5cf6",
                      disabled: busy.value,
                      onClick: recommend
                    }, {
                      default: _withCtx(() => [...(_cache[42] || (_cache[42] = [
                        _createTextVNode("随机推荐", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_v_btn, {
                      color: "#ec4899",
                      disabled: blocked.value || !targetName.value,
                      onClick: _cache[9] || (_cache[9] = $event => (visit(targetName.value)))
                    }, {
                      default: _withCtx(() => [...(_cache[43] || (_cache[43] = [
                        _createTextVNode("前往用餐", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"])
                  ]),
                  (view.value.automation?.active || view.value.automation?.enabled)
                    ? (_openBlock(), _createElementBlock("p", _hoisted_54, "后台托管中，可查询和推荐；手动到访请先在配置中暂停后台任务。"))
                    : _createCommentVNode("", true),
                  (recommendations.value.length)
                    ? (_openBlock(), _createElementBlock("div", _hoisted_55, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(recommendations.value, (item) => {
                          return (_openBlock(), _createElementBlock("article", {
                            key: item.username,
                            class: "sr-item"
                          }, [
                            _createElementVNode("h3", null, _toDisplayString(item.username), 1),
                            _createElementVNode("p", _hoisted_56, _toDisplayString(item.message || '可查询餐馆详情后前往'), 1),
                            _createVNode(_component_v_btn, {
                              color: "#ec4899",
                              disabled: blocked.value || item.can_visit===false,
                              onClick: $event => (visit(item.username))
                            }, {
                              default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                                _createTextVNode("前往用餐", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled", "onClick"])
                          ]))
                        }), 128))
                      ]))
                    : _createCommentVNode("", true)
                ])
              ]),
              _createElementVNode("section", _hoisted_57, [
                _createElementVNode("div", _hoisted_58, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-map-marker-check-outline",
                      size: "19"
                    }),
                    _cache[45] || (_cache[45] = _createTextVNode("今日到访", -1))
                  ])
                ]),
                _createElementVNode("div", _hoisted_59, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(data.value.visits?.records || [], (record, i) => {
                    return (_openBlock(), _createBlock(_component_v_chip, {
                      key: i,
                      size: "small",
                      color: "success",
                      "prepend-icon": "mdi-check-circle-outline"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(record.target_username), 1)
                      ]),
                      _: 2
                    }, 1024))
                  }), 128)),
                  (!data.value.visits?.records?.length)
                    ? (_openBlock(), _createElementBlock("p", _hoisted_60, "今天还没有到访记录"))
                    : _createCommentVNode("", true)
                ])
              ])
            ]))
          : _createCommentVNode("", true),
        (activeTab.value==='logs')
          ? (_openBlock(), _createElementBlock("div", _hoisted_61, [
              _createElementVNode("section", _hoisted_62, [
                _createElementVNode("div", _hoisted_63, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-chart-timeline-variant",
                      size: "19"
                    }),
                    _cache[46] || (_cache[46] = _createTextVNode("经营日志", -1))
                  ]),
                  _createVNode(_component_v_select, {
                    modelValue: logDays.value,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((logDays).value = $event)),
                    items: [{title:'全部记录',value:0},{title:'最近 7 天',value:7},{title:'最近 30 天',value:30}],
                    "aria-label": "日志日期范围",
                    class: "sr-log-filter"
                  }, null, 8, ["modelValue"])
                ]),
                _createElementVNode("div", _hoisted_64, [
                  _createElementVNode("p", _hoisted_65, "站点返回 " + _toDisplayString(data.value.logs?.length || 0) + " 条记录；筛选内净收益 " + _toDisplayString(number(filteredLogs.value.reduce((n,r)=>n+Number(r.net_earnings||0),0))) + " 魔力。", 1)
                ]),
                _createVNode(_component_v_table, {
                  density: "compact",
                  class: "sr-table"
                }, {
                  default: _withCtx(() => [
                    _cache[48] || (_cache[48] = _createElementVNode("thead", null, [
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
                      }), 128)),
                      (!filteredLogs.value.length)
                        ? (_openBlock(), _createElementBlock("tr", _hoisted_66, [...(_cache[47] || (_cache[47] = [
                            _createElementVNode("td", {
                              colspan: "5",
                              class: "sr-empty"
                            }, "暂无符合条件的经营记录", -1)
                          ]))]))
                        : _createCommentVNode("", true)
                    ])
                  ]),
                  _: 1
                })
              ]),
              _createElementVNode("section", _hoisted_67, [
                _createElementVNode("div", _hoisted_68, [
                  _createElementVNode("h3", null, [
                    _createVNode(_component_v_icon, {
                      icon: "mdi-history",
                      size: "19"
                    }),
                    _cache[49] || (_cache[49] = _createTextVNode("最近操作", -1))
                  ])
                ]),
                _createVNode(_component_v_table, {
                  density: "compact",
                  class: "sr-table"
                }, {
                  default: _withCtx(() => [
                    _cache[51] || (_cache[51] = _createElementVNode("thead", null, [
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
                          _createElementVNode("td", _hoisted_69, _toDisplayString(event.message), 1)
                        ]))
                      }), 128)),
                      (!view.value.events?.length)
                        ? (_openBlock(), _createElementBlock("tr", _hoisted_70, [...(_cache[50] || (_cache[50] = [
                            _createElementVNode("td", {
                              colspan: "3",
                              class: "sr-empty"
                            }, "暂无最近操作", -1)
                          ]))]))
                        : _createCommentVNode("", true)
                    ])
                  ]),
                  _: 1
                })
              ])
            ]))
          : _createCommentVNode("", true),
        _createVNode(_component_v_dialog, {
          "model-value": !!confirmation.value,
          "max-width": "460",
          "onUpdate:modelValue": _cache[11] || (_cache[11] = value=>!value && cancelConfirm()),
          "aria-labelledby": "sr-confirm-title"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card, {
              class: "sr-confirm-card",
              rounded: "lg"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, { id: "sr-confirm-title" }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(confirmation.value?.title), 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card_text, null, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(confirmation.value?.text), 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card_actions, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_spacer),
                    _createVNode(_component_v_btn, {
                      color: "default",
                      variant: "text",
                      onClick: cancelConfirm
                    }, {
                      default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
                        _createTextVNode("取消", -1)
                      ]))]),
                      _: 1
                    }),
                    _createVNode(_component_v_btn, {
                      color: "success",
                      variant: "tonal",
                      onClick: acceptConfirm
                    }, {
                      default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                        _createTextVNode("确认", -1)
                      ]))]),
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
        }, 8, ["model-value"])
      ]),
      _: 1
    })
  ]))
}
}

};

export { _sfc_main as default };

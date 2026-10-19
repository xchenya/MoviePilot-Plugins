<template>
  <section class="sr-app">
    <header class="sr-header">
      <div><span class="sr-eyebrow">SIQI · RESTAURANT</span><h2>思齐餐厅 <small>{{ statusLabel }}</small></h2><p>经营你的餐厅，照顾每一位顾客。</p></div>
      <div class="sr-actions"><button @click="refresh" :disabled="busy">刷新</button><button @click="emit('switch', 'config')">配置</button><button @click="emit('close')">关闭</button></div>
    </header>
    <div v-if="message" role="status" class="sr-notice" :class="{ 'sr-error': !ok }">{{ message }}</div>
    <div v-if="view.uncertain" class="sr-notice sr-error">上次站点操作结果不明，已暂停写入。请先刷新并核对网站。
      <button @click="resolveUncertain" :disabled="busy">已核对，解除锁定</button>
    </div>
    <div class="sr-stats">
      <article v-for="item in stats" :key="item.label"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></article>
    </div>
    <section class="sr-card sr-automation" aria-label="后台自动经营状态">
      <div class="sr-card-title"><h3>后台自动经营 · {{ view.automation?.enabled?'已开启':'已暂停' }}</h3><button @click="emit('switch','config')">{{ view.automation?.enabled?'暂停 / 调整托管':'设置自动经营' }}</button></div>
      <p>{{ view.automation?.enabled ? (view.automation.message || '等待后台首次检查') : '可在配置中开启每日自动经营。' }}</p>
      <p v-if="view.automation?.enabled" class="sr-muted">今日补货预算已占用 {{ number(view.automation.spent) }} / {{ number(view.automation.daily_budget) }} 魔力 · {{ view.automation.last_check ? `最近后台检查 ${new Date(view.automation.last_check*1000).toLocaleTimeString()}` : '尚未检查' }}。关闭本页面后继续运行。</p>
    </section>
    <div class="sr-toolbar">
      <button class="sr-primary" :disabled="blocked || state.session_status !== 'ready' || !state.customers_total" @click="startSession">开始今日经营</button>
      <label><input type="checkbox" v-model="runStaff" :disabled="blocked || !data.staff?.unlocked">运行已雇员工</label>
      <span>员工按同编号餐位服务。离开面板或标签页进入后台后暂停执行。</span>
    </div>
    <nav class="sr-tabs" aria-label="餐厅功能">
      <button v-for="tab in tabs" :key="tab.id" :class="{active:activeTab===tab.id}" @click="activeTab=tab.id">{{ tab.label }}</button>
    </nav>
    <template v-if="activeTab === 'kitchen'">
      <div class="sr-section-head"><h3>厨房与餐位</h3><span>排队 {{ state.queued_customers || 0 }} · 剩余 {{ state.customers_remaining ?? '—' }}</span></div>
      <p class="sr-muted">选择菜品 → 备齐食材与工具 → 开始烹饪 → 上菜。灶台进度保存在 MP 中，刷新页面可继续。</p>
      <div class="sr-kitchen-grid">
        <article class="sr-card" v-for="stove in view.kitchen || []" :key="stove.index">
          <div class="sr-card-title"><h3>灶台 {{ stove.index }}</h3><span class="sr-badge">{{ stoveStatus(stove) }}</span></div>
          <div class="sr-seat" :class="{occupied:customerAt(stove.index)}">
            <template v-if="cleaningLeft(stove.index)>0">🧹 餐位清理中 · {{ cleaningLeft(stove.index) }} 秒</template>
            <template v-else-if="customerAt(stove.index)">
              <strong>餐位 {{ stove.index }} · {{ dishName(customerAt(stove.index).dish_key) }}</strong>
              <span>耐心剩余 {{ patience(customerAt(stove.index)) }} 秒</span>
              <progress :value="patience(customerAt(stove.index))" :max="customerAt(stove.index).patience || 60"></progress>
            </template>
            <span v-else>餐位 {{ stove.index }} · 等待顾客</span>
          </div>
          <select v-if="stove.status==='idle'" v-model="selected[stove.index]" :disabled="blocked" :aria-label="`灶台 ${stove.index} 菜品`">
            <option value="">选择菜品</option><option v-for="dish in unlockedDishes" :key="dish.key" :value="dish.key">{{ dish.name }} · {{ dish.cook_time }} 秒</option>
          </select>
          <h4 v-else>{{ dishName(stove.dish_key) }}</h4>
          <p v-if="stove.dish_key" class="sr-muted">{{ recipeText(stove.dish_key) }}</p>
          <div class="sr-actions sr-wrap">
            <button v-if="stove.status==='idle'" :disabled="blocked || !selected[stove.index]" @click="act('assign_dish',{station_index:stove.index,dish_key:selected[stove.index]})">选择菜品</button>
            <template v-if="stove.status==='prepping'">
              <button :disabled="blocked" @click="act('prepare',{station_index:stove.index})">备齐食材与工具</button>
              <button class="sr-primary" :disabled="blocked || !prepared(stove)" @click="act('cook',{station_index:stove.index})">开始烹饪</button>
              <button :disabled="blocked" @click="act('cancel',{station_index:stove.index})">取消</button>
            </template>
            <span v-if="stove.status==='cooking'" class="sr-cooking">🔥 烹饪中 · {{ remaining(stove.ready_at) }} 秒</span>
            <template v-if="stove.status==='ready'">
              <select v-model="serveTargets[stove.index]" :disabled="blocked" :aria-label="`灶台 ${stove.index} 上菜餐位`">
                <option value="">选择上菜餐位</option><option v-for="c in matchingCustomers(stove)" :key="c.id" :value="c.id">餐位 {{ c.seat }} · {{ patience(c) }} 秒</option>
              </select>
              <button class="sr-primary" :disabled="blocked || !serveTargets[stove.index]" @click="act('serve',{station_index:stove.index,customer_id:serveTargets[stove.index]})">上菜</button>
              <button :disabled="blocked" @click="askReturn(stove)">归位</button>
              <button class="sr-danger" :disabled="blocked" @click="askDiscard(stove)">丢弃</button>
            </template>
          </div>
          <div v-if="data.staff?.unlocked" class="sr-staff-actions">
            <button v-for="role in roles" :key="role.key" :class="{'sr-selected': assigned(stove.index,role.key)}" :disabled="blocked || (!assigned(stove.index,role.key) && !data.staff?.available?.[role.key])" @click="act('update_staff_assignment',{station_index:stove.index,role:role.key,assigned:assigned(stove.index,role.key)?0:1})">{{ role.label }} · {{ assigned(stove.index,role.key)?'已上岗':'分配' }}</button>
          </div>
        </article>
      </div>
      <p v-if="!view.kitchen?.length" class="sr-empty">请先启用插件并刷新餐厅数据。</p>
    </template>
    <template v-if="activeTab === 'supplies'">
      <h3>食材商店与仓库</h3><p class="sr-muted">可用库存已扣除本插件厨房预留。购买前会显示本次魔力支出。</p>
      <div class="sr-grid">
        <article class="sr-card" v-for="item in data.config?.ingredients || []" :key="item.key">
          <h3>{{ item.name }}</h3><p>可用 {{ number(available(item.key)) }} <small>／总计 {{ number(data.inventory?.ingredients?.[item.key]) }}</small></p>
          <p>{{ number(item.price) }} 魔力 / 份</p>
          <div class="sr-actions"><input type="number" min="1" max="10000" v-model.number="quantities[item.key]" :aria-label="`${item.name}购买数量`"><button :disabled="blocked" @click="buy(item)">购买</button></div>
        </article>
      </div>
      <h3 class="sr-section-head">菜品手册</h3>
      <div class="sr-grid"><article v-for="dish in data.config?.dishes || []" :key="dish.key" class="sr-card">
        <h3>{{ dish.name }}</h3><p>{{ dish.cook_time }} 秒 · 售价 {{ number(dish.sell_price ?? dish.price) }} 魔力</p><p class="sr-muted">{{ recipeText(dish.key) }}</p>
        <span class="sr-badge">{{ state.unlocked?.dishes?.includes(dish.key)?'已解锁':`需 ${number(dish.unlock_popularity)} 欢迎值` }}</span>
      </article></div>
      <h3 class="sr-section-head">烹饪工具</h3><div class="sr-actions sr-wrap"><span v-for="tool in data.config?.tools || []" :key="tool.key" class="sr-badge">{{ tool.name }} · {{ data.inventory?.tools?.[tool.key]?'已解锁':'未解锁' }}</span></div>
    </template>
    <template v-if="activeTab === 'staff'">
      <h3>员工管理</h3><p class="sr-muted">雇佣后在厨房分配到灶台，再开启“运行已雇员工”。每次雇佣 1 人，价格取站点当前报价。</p>
      <div class="sr-grid"><article class="sr-card" v-for="role in roles" :key="role.key">
        <h3>{{ role.label }}</h3><p>已雇佣 {{ data.staff?.inventory?.[role.key] || 0 }} / {{ data.staff?.capacity?.[role.key] || 0 }} · 空闲 {{ data.staff?.available?.[role.key] || 0 }}</p>
        <p>下一位 {{ number(data.staff?.next_prices?.[role.key]) }} 魔力</p><button :disabled="blocked || !data.staff?.next_prices?.[role.key]" @click="hire(role)">雇佣 1 人</button>
      </article></div>
      <p v-for="(pkg,i) in data.config?.staff?.packages || []" :key="i">{{ number(pkg.threshold) }} 欢迎值：厨师 +{{ pkg.limits?.chef?.count || 0 }}，服务员 +{{ pkg.limits?.server?.count || 0 }} {{ pkg.unlocked?'✓':'' }}</p>
    </template>
    <template v-if="activeTab === 'visits'">
      <h3>下馆子 <small>今日 {{ data.visits?.count || 0 }} / {{ data.visits?.limit || 3 }}</small></h3>
      <section class="sr-card">
        <div class="sr-card-title"><h3>自动下馆子 · {{ view.automation?.visit_enabled?'已开启':'已关闭' }}</h3><button @click="emit('switch','config')">设置名单与通知</button></div>
        <p>{{ view.automation?.visits?.message || '可指定最多 3 人；全部留空时每天随机到访 3 人。' }}</p>
        <p v-for="(attempt,name) in view.automation?.visits?.attempts || {}" :key="name" class="sr-muted">{{ attempt.username }} · {{ attempt.message }}</p>
      </section>
      <div class="sr-actions sr-wrap"><input v-model.trim="targetName" maxlength="64" placeholder="输入餐馆主人用户名" aria-label="餐馆主人用户名"><button :disabled="busy || !targetName" @click="lookup">查询</button><button :disabled="busy" @click="recommend">随机推荐</button><button class="sr-primary" :disabled="blocked || !targetName" @click="visit(targetName)">前往用餐</button></div>
      <div class="sr-grid"><article v-for="item in recommendations" :key="item.username" class="sr-card"><h3>{{ item.username }}</h3><p>{{ item.message || '可查询餐馆详情后前往' }}</p><button :disabled="blocked || item.can_visit===false" @click="visit(item.username)">前往用餐</button></article></div>
      <h3 class="sr-section-head">今日到访</h3><p v-for="(record,i) in data.visits?.records || []" :key="i">{{ record.target_username }}</p>
    </template>
    <template v-if="activeTab === 'logs'">
      <div class="sr-section-head"><h3>经营日志</h3><label>最近 <select v-model.number="logDays"><option :value="0">全部</option><option :value="7">7 天</option><option :value="30">30 天</option></select></label></div>
      <p class="sr-muted">站点返回的 {{ data.logs?.length || 0 }} 条记录；筛选内净收益 {{ number(filteredLogs.reduce((n,r)=>n+Number(r.net_earnings||0),0)) }} 魔力。</p>
      <div class="sr-table-wrap"><table><thead><tr><th>日期</th><th>顾客完成 / 总数</th><th>欢迎值</th><th>净收益</th><th>流失</th></tr></thead><tbody><tr v-for="log in filteredLogs" :key="log.log_date"><td>{{ log.log_date }}</td><td>{{ log.customers_served }} / {{ log.customers_total }}</td><td>{{ number(log.popularity_change) }}</td><td>{{ number(log.net_earnings) }}</td><td>{{ log.details?.left || 0 }}</td></tr></tbody></table></div>
      <h3 class="sr-section-head">最近操作</h3><div class="sr-table-wrap"><table><thead><tr><th>时间</th><th>操作</th><th>结果</th></tr></thead><tbody><tr v-for="(event,i) in view.events || []" :key="i"><td>{{ new Date(event.time*1000).toLocaleString() }}</td><td>{{ actionLabels[event.action] || event.action }}</td><td>{{ event.message }}</td></tr></tbody></table></div>
    </template>
    <div v-if="confirmation" class="sr-overlay" role="presentation" @click.self="cancelConfirm">
      <section class="sr-dialog" role="dialog" aria-modal="true" aria-labelledby="sr-confirm-title"><h3 id="sr-confirm-title">{{ confirmation.title }}</h3><p>{{ confirmation.text }}</p><div class="sr-actions"><button @click="cancelConfirm">取消</button><button class="sr-primary" @click="acceptConfirm">确认</button></div></section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, onActivated, onDeactivated, reactive, ref } from 'vue'
import '../style.css'
const props = defineProps({ api: Object, pluginId: {type:String,default:'SiqiRestaurant'}, initialConfig: Object })
const emit = defineEmits(['switch','close'])
const view = ref({}), busy = ref(false), message = ref(''), ok = ref(true), runStaff = ref(false)
const selected = reactive({}), serveTargets = reactive({}), quantities = reactive({})
const targetName = ref(''), recommendations = ref([]), logDays = ref(0), activeTab = ref('kitchen')
const now = ref(Date.now()/1000), confirmation = ref(null)
let clockOffset=0, timer=null, clock=null, alive=false, confirmResolver=null
const data = computed(()=>view.value.restaurant || {}), state = computed(()=>data.value.state || {})
const blocked = computed(()=>busy.value || !!view.value.uncertain || !!view.value.automation?.enabled || !!view.value.automation?.active || !data.value.state)
const tabs = [{id:'kitchen',label:'厨房与餐位'},{id:'supplies',label:'食材与菜品'},{id:'staff',label:'员工'},{id:'visits',label:'下馆子'},{id:'logs',label:'经营日志'}]
const roles = [{key:'chef',label:'🧑‍🍳 厨师'},{key:'server',label:'💁 服务员'}]
const actionLabels = {purchase_ingredient:'购买食材',hire_staff:'雇佣员工',update_staff_assignment:'员工调度',start_session:'开始营业',visit_restaurant:'下馆子',serve_customer:'上菜',discard_dish:'丢弃菜品',customer_left:'顾客离席',resolve:'核对解锁',automation:'自动经营',auto_visit:'自动下馆子',notification:'通知'}
const number = n => Number(n || 0).toLocaleString()
const statusLabel = computed(()=>({ready:'准备营业',open:'营业中',closed:'已闭店'}[state.value.session_status] || '未连接'))
const stats = computed(()=>[{label:'魔力余额',value:number(data.value.user?.magic)},{label:'受欢迎值',value:number(state.value.popularity)},{label:'今日顾客',value:`${state.value.customers_served || 0} / ${state.value.customers_total || 0}`},{label:'今日净收益',value:number(state.value.net_earnings_today)},{label:'累计净收益',value:number(state.value.net_earnings_total)}])
const unlockedDishes = computed(()=>(data.value.config?.dishes || []).filter(d=>state.value.unlocked?.dishes?.includes(d.key)))
const filteredLogs = computed(()=>(data.value.logs || []).filter(l=>!logDays.value || Date.parse(`${l.log_date}T00:00:00+08:00`) >= now.value*1000-logDays.value*86400000))
const dish = key=>(data.value.config?.dishes || []).find(d=>d.key===key)
const dishName = key=>dish(key)?.name || key
const remaining = timestamp=>Math.max(0,Math.ceil(Number(timestamp)-now.value))
const patience = customer=>customer?.deadline?remaining(customer.deadline):Number(customer?.patience || 0)
const customerAt = index=>(state.value.customer_plan || []).find(c=>c.status==='waiting' && Number(c.seat)===index)
const cleaningLeft = index=>remaining(view.value.cleaning?.[String(index)] || 0)
const matchingCustomers = stove=>(state.value.customer_plan || []).filter(c=>c.status==='waiting' && c.seat && c.dish_key===stove.dish_key && patience(c)>0 && !cleaningLeft(c.seat))
function recipeText(key){const d=dish(key);if(!d)return '';return (d.ingredients||[]).map(i=>`${data.value.config?.ingredients?.find(x=>x.key===i.key)?.name || i.key} ×${i.quantity}`).join('、')+` · ${data.value.config?.tools?.find(t=>t.key===d.tool)?.name || d.tool}`}
function prepared(stove){const d=dish(stove.dish_key);return d && stove.tool_key===d.tool && d.ingredients.every(i=>Number(stove.ingredients[i.key]||0)>=Number(i.quantity))}
function available(key){return Math.max(0,Number(data.value.inventory?.ingredients?.[key]||0)-(view.value.kitchen||[]).reduce((n,s)=>n+Number(s.ingredients?.[key]||0),0))}
function stoveStatus(s){return {idle:'空闲',prepping:prepared(s)?'已备齐':'备菜中',cooking:'烹饪中',ready:'待上菜'}[s.status] || s.status}
function assigned(index,role){const a=data.value.staff?.assignments_map || data.value.staff?.assignments || {};const value=(Array.isArray(a)?a.find(x=>Number(x.station_index)===index):a[index])?.[role];return value===true || value===1 || value==='1'}
function unwrap(result){if(result?.restaurant || typeof result?.success==='boolean')return result;if(result?.data && typeof result.data.success==='boolean')return result.data;throw new Error('插件接口返回格式不正确')}
function update(result){if(!alive)return;view.value=result;clockOffset=(result.server_now || Date.now()/1000)-Date.now()/1000;now.value=Date.now()/1000+clockOffset;for(const s of result.kitchen||[]){selected[s.index]??='';const matches=matchingCustomers(s);if(!matches.some(c=>String(c.id)===String(serveTargets[s.index])))serveTargets[s.index]=matches.find(c=>Number(c.seat)===s.index)?.id || matches[0]?.id || ''}for(const item of result.restaurant?.config?.ingredients || [])quantities[item.key]??=1;if(result.uncertain || result.automation?.enabled)runStaff.value=false}
async function request(path,payload,verb='post',quiet=false){if(busy.value)return null;busy.value=true;try{const r=unwrap(await props.api[verb](`plugin/${props.pluginId}${path}`,payload));update(r);if(!quiet || !r.success){message.value=r.message || (r.success?'操作完成':'操作失败');ok.value=r.success}return r}catch(e){if(alive){message.value=e.message || '请求失败，请刷新后核对';ok.value=false;runStaff.value=false}return null}finally{busy.value=false}}
const act=(action,args={})=>request('/action',{action,args,request_id:(crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)})
const refresh=()=>request('/refresh',{})
function confirm(title,text){return new Promise(resolve=>{confirmation.value={title,text};confirmResolver=resolve})}
function cancelConfirm(){confirmation.value=null;confirmResolver?.(false);confirmResolver=null}
function acceptConfirm(){confirmation.value=null;confirmResolver?.(true);confirmResolver=null}
async function startSession(){if(await confirm('开始今日经营','每天只能开业一次，开业后顾客耐心开始倒计时。可先备菜，再开始经营。'))await act('start_session')}
async function buy(item){const q=Number(quantities[item.key]??1);if(!Number.isInteger(q)||q<1||q>10000){message.value='购买数量须为 1–10000 的整数';ok.value=false;return}if(await confirm('购买食材',`${item.name} × ${q}，当前报价合计 ${number(q*item.price)} 魔力。`))await act('purchase_ingredient',{ingredient_key:item.key,quantity:q,max_cost:q*Number(item.price)})}
async function hire(role){if(await confirm('雇佣员工',`雇佣 1 位${role.label}，当前报价 ${number(data.value.staff?.next_prices?.[role.key])} 魔力。`))await act('hire_staff',{role:role.key,quantity:1,max_cost:Number(data.value.staff?.next_prices?.[role.key])})}
async function askDiscard(s){if(await confirm('丢弃菜品',`丢弃「${dishName(s.dish_key)}」会按站点规则消耗食材，无售出收益。`))await act('discard',{station_index:s.index})}
async function askReturn(s){if(await confirm('归位灶台','与原网页一致，归位会提交丢弃菜品并消耗相应食材，无售出收益。'))await act('return_stove',{station_index:s.index})}
async function recommend(){const r=await act('list_visitable_restaurants');if(r?.success)recommendations.value=r.restaurants || []}
async function lookup(){const r=await act('inspect_restaurant_target',{target_username:targetName.value});if(r?.success)recommendations.value=r.candidate?[r.candidate]:[]}
async function visit(name){if(!await confirm('前往用餐',`前往 ${name} 的餐馆，将使用今日一次下馆子机会。`))return;let r=await act('visit_restaurant',{target_username:name});if(r?.requires_confirmation && await confirm('站点确认',r.message || '站点要求再次确认前往'))await act('visit_restaurant',{target_username:name,confirm:'yes'})}
async function resolveUncertain(){if(await confirm('核对后解锁','请确认已经核对网站的余额、库存、员工与顾客状态。解除后不会重发原请求；结果不明的成品将释放本地预留。'))await request('/resolve',{acknowledged:true})}
async function poll(){if(!alive)return;try{if(!document.hidden && !busy.value && !confirmation.value && data.value.state)await (view.value.automation?.enabled ? request('/state',undefined,'get',true) : request('/tick',{run_staff:runStaff.value},'post',true))}finally{if(alive)timer=setTimeout(poll,2000)}}
function start(){if(alive)return;alive=true;request('/state',undefined,'get',true);clock=setInterval(()=>{now.value=Date.now()/1000+clockOffset},500);timer=setTimeout(poll,2000)}
function stop(){alive=false;runStaff.value=false;clearTimeout(timer);clearInterval(clock);cancelConfirm()}
onMounted(start);onActivated(start);onDeactivated(stop);onUnmounted(stop)
</script>

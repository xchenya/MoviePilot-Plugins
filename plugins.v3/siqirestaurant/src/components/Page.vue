<template>
  <section class="sr-app sr-page">
    <v-defaults-provider :defaults="uiDefaults">
      <header class="sr-topbar">
        <div class="sr-topbar-left">
          <div class="sr-topbar-icon"><v-icon icon="mdi-silverware-fork-knife" size="24" /></div>
          <div class="sr-topbar-copy"><h2>思齐餐厅 <v-chip :color="state.session_status==='open'?'success':'default'">{{ statusLabel }}</v-chip></h2><p>{{ data.state ? (fastPolling ? '营业或烹饪中，每 2 秒更新状态' : '空闲中，每 60 秒更新状态') : '管理厨房、食材、员工与餐厅互动' }}</p></div>
        </div>
        <v-btn-group variant="tonal" density="compact" class="sr-topbar-actions">
          <v-btn color="success" aria-label="刷新" title="刷新" @click="refresh" :loading="busy" :disabled="busy"><v-icon icon="mdi-refresh" size="18" /><span>刷新</span></v-btn>
          <v-btn color="success" aria-label="配置" title="配置" @click="emit('switch','config')"><v-icon icon="mdi-cog-outline" size="18" /><span>配置</span></v-btn>
          <v-btn color="success" aria-label="关闭" title="关闭" @click="emit('close')"><v-icon icon="mdi-close" size="18" /><span>关闭</span></v-btn>
        </v-btn-group>
      </header>
      <v-alert v-if="message" :type="ok?'success':'error'" variant="tonal" density="compact" closable role="status" @click:close="message=''">{{ message }}</v-alert>
      <v-alert v-if="view.uncertain" type="warning" variant="tonal" density="compact"><div class="sr-alert-row"><span>上次站点操作结果不明，已暂停写入。请先刷新并核对网站。</span><v-btn color="warning" @click="resolveUncertain" :disabled="busy">已核对，解除锁定</v-btn></div></v-alert>
      <v-progress-linear v-if="busy && !data.state" indeterminate color="success" aria-label="读取餐厅" />
      <div class="sr-stats">
        <article v-for="item in stats" :key="item.label" class="sr-stat" :style="{'--sr-accent':item.accent}"><div class="sr-stat-icon"><v-icon :icon="item.icon" size="22" /></div><div><span>{{ item.label }}</span><strong>{{ data.state?item.value:'—' }}</strong></div></article>
      </div>
      <section class="sr-card sr-automation" aria-label="后台自动经营状态">
        <div class="sr-card-title sr-card-band"><h3><v-icon icon="mdi-robot-outline" size="19" color="success" />后台自动经营 <v-chip :color="view.automation?.enabled?'success':'default'">{{ view.automation?.enabled?'已开启':'已暂停' }}</v-chip></h3><v-btn variant="text" prepend-icon="mdi-tune-variant" @click="emit('switch','config')">{{ view.automation?.enabled?'暂停 / 调整托管':'设置自动经营' }}</v-btn></div>
        <div class="sr-card-body sr-automation-body">
          <div><p>{{ view.automation?.enabled ? (view.automation.message || '等待后台首次检查') : '可在配置中开启每日自动经营。' }}</p><p class="sr-hint">{{ view.automation?.last_check ? `最近检查 ${new Date(view.automation.last_check*1000).toLocaleTimeString()}` : '等待后台检查' }} · 关闭页面后继续运行</p></div>
          <div class="sr-budget-meter"><div><span>今日补货预算</span><strong>{{ number(view.automation?.spent) }} / {{ number(view.automation?.daily_budget) }}</strong></div><v-progress-linear :model-value="Math.min(100,Number(view.automation?.spent||0)/Math.max(1,Number(view.automation?.daily_budget||0))*100)" color="success" height="5" rounded aria-label="今日补货预算使用比例" /></div>
        </div>
      </section>
      <v-tabs v-model="activeTab" color="success" density="compact" show-arrows class="sr-tabs" aria-label="餐厅功能">
        <v-tab v-for="tab in tabs" :key="tab.id" :value="tab.id" :prepend-icon="tab.icon">{{ tab.label }}</v-tab>
      </v-tabs>
      <div v-if="activeTab==='kitchen'" class="sr-stack">
        <section class="sr-card">
          <div class="sr-card-title sr-card-band sr-band-brown"><h3><v-icon icon="mdi-stove" size="19" />厨房与餐位</h3><div class="sr-actions"><v-chip>排队 {{ state.queued_customers || 0 }}</v-chip><v-chip>剩余 {{ state.customers_remaining ?? '—' }}</v-chip></div></div>
          <div class="sr-card-body sr-stack">
            <div class="sr-toolbar"><v-btn prepend-icon="mdi-storefront-outline" :disabled="blocked || state.session_status!=='ready' || !state.customers_total" @click="startSession">开始今日经营</v-btn><v-switch v-model="runStaff" label="运行已雇员工" color="success" hide-details density="compact" :disabled="blocked || !data.staff?.unlocked" /><span class="sr-hint">{{ view.automation?.active || view.automation?.enabled?'后台托管中，手动操作已暂停':'员工按同编号餐位服务，仅在页面可见时执行' }}</span></div>
            <div class="sr-kitchen-grid">
              <article v-for="stove in view.kitchen || []" :key="stove.index" class="sr-stove" :class="`sr-stove-${stove.status}`">
                <div class="sr-card-title"><h3><v-icon icon="mdi-fire" size="18" :color="stove.status==='idle'?'#9e9e9e':'#f59e0b'" />灶台 {{ stove.index }}</h3><v-chip :color="stove.status==='ready'?'success':stove.status==='idle'?'default':'#f59e0b'">{{ stoveStatus(stove) }}</v-chip></div>
                <div class="sr-seat" :class="{occupied:customerAt(stove.index)}">
                  <template v-if="cleaningLeft(stove.index)>0"><v-icon icon="mdi-broom" size="20" />餐位清理中 · {{ cleaningLeft(stove.index) }} 秒</template>
                  <template v-else-if="customerAt(stove.index)"><strong>餐位 {{ stove.index }} · {{ dishName(customerAt(stove.index).dish_key) }}</strong><span>耐心剩余 {{ patience(customerAt(stove.index)) }} 秒</span><v-progress-linear :model-value="Math.min(100,patience(customerAt(stove.index))/(customerAt(stove.index).patience||60)*100)" color="success" height="4" rounded /></template>
                  <template v-else><v-icon icon="mdi-seat-outline" size="22" /><span>餐位 {{ stove.index }} · 等待顾客</span></template>
                </div>
                <v-select v-if="stove.status==='idle'" v-model="selected[stove.index]" :items="dishOptions" label="选择菜品" :aria-label="`灶台 ${stove.index} 菜品`" :disabled="blocked" />
                <h4 v-else>{{ dishName(stove.dish_key) }}</h4>
                <p v-if="stove.dish_key" class="sr-hint">{{ recipeText(stove.dish_key) }}</p>
                <div class="sr-actions sr-wrap">
                  <v-btn v-if="stove.status==='idle'" :disabled="blocked || !selected[stove.index]" @click="act('assign_dish',{station_index:stove.index,dish_key:selected[stove.index]})">选择菜品</v-btn>
                  <template v-if="stove.status==='prepping'"><v-btn :disabled="blocked" @click="act('prepare',{station_index:stove.index})">备齐食材与工具</v-btn><v-btn :disabled="blocked || !prepared(stove)" @click="act('cook',{station_index:stove.index})">开始烹饪</v-btn><v-btn color="default" variant="text" :disabled="blocked" @click="act('cancel',{station_index:stove.index})">取消</v-btn></template>
                  <v-chip v-if="stove.status==='cooking'" color="#f59e0b" prepend-icon="mdi-timer-sand">烹饪中 · {{ remaining(stove.ready_at) }} 秒</v-chip>
                  <template v-if="stove.status==='ready'"><v-select v-model="serveTargets[stove.index]" :items="seatOptions(stove)" label="上菜餐位" class="sr-full-width" :disabled="blocked" :aria-label="`灶台 ${stove.index} 上菜餐位`" /><v-btn :disabled="blocked || !serveTargets[stove.index]" @click="act('serve',{station_index:stove.index,customer_id:serveTargets[stove.index]})">上菜</v-btn><v-btn color="default" :disabled="blocked" @click="askReturn(stove)">归位</v-btn><v-btn color="error" variant="text" :disabled="blocked" @click="askDiscard(stove)">丢弃</v-btn></template>
                </div>
                <div v-if="data.staff?.unlocked" class="sr-staff-actions"><v-btn v-for="role in roles" :key="role.key" :prepend-icon="role.icon" :color="assigned(stove.index,role.key)?'success':'default'" size="x-small" :disabled="blocked || (!assigned(stove.index,role.key) && !data.staff?.available?.[role.key])" @click="act('update_staff_assignment',{station_index:stove.index,role:role.key,assigned:assigned(stove.index,role.key)?0:1})">{{ role.label }} · {{ assigned(stove.index,role.key)?'已上岗':'分配' }}</v-btn></div>
              </article>
            </div>
            <div v-if="!view.kitchen?.length" class="sr-empty"><v-icon icon="mdi-storefront-outline" size="32" /><p>请先启用插件并刷新餐厅数据</p></div>
            <p class="sr-hint">选择菜品 → 备齐食材与工具 → 开始烹饪 → 上菜。刷新页面可继续厨房进度。</p>
          </div>
        </section>
      </div>
      <div v-if="activeTab==='supplies'" class="sr-stack">
        <section class="sr-card"><div class="sr-card-title sr-card-band sr-band-orange"><h3><v-icon icon="mdi-basket-outline" size="19" />食材商店与仓库</h3><span class="sr-hint">可用库存已扣除厨房预留</span></div><div class="sr-card-body sr-grid">
          <article class="sr-item" v-for="item in data.config?.ingredients || []" :key="item.key"><h3>{{ item.name }}<v-chip color="#f59e0b">{{ number(item.price) }} 魔力 / 份</v-chip></h3><p class="sr-inventory-value">{{ number(available(item.key)) }}<span> 可用 / {{ number(data.inventory?.ingredients?.[item.key]) }} 总计</span></p><div class="sr-actions"><v-text-field v-model.number="quantities[item.key]" type="number" min="1" max="10000" label="数量" :aria-label="`${item.name}购买数量`" /><v-btn color="#f59e0b" :disabled="blocked" @click="buy(item)">购买</v-btn></div></article>
          <p v-if="!data.config?.ingredients?.length" class="sr-empty">暂无食材数据，请刷新餐厅</p>
        </div></section>
        <section class="sr-card"><div class="sr-card-title sr-card-band"><h3><v-icon icon="mdi-book-open-page-variant-outline" size="19" />菜品手册</h3></div><div class="sr-card-body sr-grid"><article v-for="dish in data.config?.dishes || []" :key="dish.key" class="sr-item"><h3>{{ dish.name }}<v-chip :color="state.unlocked?.dishes?.includes(dish.key)?'success':'default'">{{ state.unlocked?.dishes?.includes(dish.key)?'已解锁':`需 ${number(dish.unlock_popularity)} 欢迎值` }}</v-chip></h3><p>{{ dish.cook_time }} 秒 · 售价 {{ number(dish.sell_price ?? dish.price) }} 魔力</p><p class="sr-hint">{{ recipeText(dish.key) }}</p></article></div><div class="sr-tools"><span class="sr-hint">烹饪工具</span><v-chip v-for="tool in data.config?.tools || []" :key="tool.key" :color="data.inventory?.tools?.[tool.key]?'success':'default'">{{ tool.name }} · {{ data.inventory?.tools?.[tool.key]?'已解锁':'未解锁' }}</v-chip></div></section>
      </div>
      <section v-if="activeTab==='staff'" class="sr-card"><div class="sr-card-title sr-card-band sr-band-blue"><h3><v-icon icon="mdi-account-group-outline" size="19" />员工管理</h3></div><div class="sr-card-body sr-stack"><p class="sr-hint">雇佣后在厨房分配到灶台，再开启“运行已雇员工”。每次雇佣 1 人，使用站点当前报价。</p><div class="sr-staff-grid"><article v-for="role in roles" :key="role.key" class="sr-item"><h3><v-icon :icon="role.icon" color="info" />{{ role.label }}</h3><p>已雇佣 {{ data.staff?.inventory?.[role.key] || 0 }} / {{ data.staff?.capacity?.[role.key] || 0 }} · 空闲 {{ data.staff?.available?.[role.key] || 0 }}</p><div class="sr-card-title"><strong>下一位 {{ number(data.staff?.next_prices?.[role.key]) }} 魔力</strong><v-btn color="info" :disabled="blocked || !data.staff?.next_prices?.[role.key]" @click="hire(role)">雇佣 1 人</v-btn></div></article></div><p v-for="(pkg,i) in data.config?.staff?.packages || []" :key="i" class="sr-hint">{{ number(pkg.threshold) }} 欢迎值：厨师 +{{ pkg.limits?.chef?.count || 0 }}，服务员 +{{ pkg.limits?.server?.count || 0 }} {{ pkg.unlocked?'· 已解锁':'' }}</p></div></section>
      <div v-if="activeTab==='visits'" class="sr-stack">
        <section class="sr-card"><div class="sr-card-title sr-card-band sr-band-pink"><h3><v-icon icon="mdi-silverware-fork-knife" size="19" />下馆子 <v-chip color="#ec4899">今日 {{ data.visits?.count || 0 }} / {{ data.visits?.limit || 3 }}</v-chip></h3><v-btn color="#ec4899" variant="text" prepend-icon="mdi-tune-variant" @click="emit('switch','config')">设置名单与通知</v-btn></div><div class="sr-card-body sr-stack">
          <div class="sr-visit-status"><v-icon icon="mdi-robot-outline" color="#ec4899" size="24" /><div><h3>自动下馆子 · {{ view.automation?.visit_enabled?'已开启':'已关闭' }}</h3><p class="sr-hint">{{ view.automation?.visits?.message || '可指定最多 3 人；全部留空时每天随机到访 3 人。' }}</p></div></div>
          <div v-if="Object.keys(view.automation?.visits?.attempts || {}).length" class="sr-visit-results"><div v-for="(attempt,name) in view.automation.visits.attempts" :key="name" class="sr-visit-result"><v-icon icon="mdi-account-circle-outline" color="#ec4899" size="22" /><div><strong>{{ attempt.username }}</strong><p class="sr-hint">{{ attempt.message }}</p></div></div></div>
          <div class="sr-visit-search"><v-text-field v-model.trim="targetName" maxlength="64" label="餐馆主人用户名" aria-label="餐馆主人用户名" prepend-inner-icon="mdi-account-search-outline" @keydown.enter="targetName && !busy && lookup()" /><v-btn color="#ec4899" :disabled="busy || !targetName" @click="lookup">查询</v-btn><v-btn color="#8b5cf6" :disabled="busy" @click="recommend">随机推荐</v-btn><v-btn color="#ec4899" :disabled="blocked || !targetName" @click="visit(targetName)">前往用餐</v-btn></div>
          <p v-if="view.automation?.active || view.automation?.enabled" class="sr-hint">后台托管中，可查询和推荐；手动到访请先在配置中暂停后台任务。</p>
          <div v-if="recommendations.length" class="sr-grid"><article v-for="item in recommendations" :key="item.username" class="sr-item"><h3>{{ item.username }}</h3><p class="sr-hint">{{ item.message || '可查询餐馆详情后前往' }}</p><v-btn color="#ec4899" :disabled="blocked || item.can_visit===false" @click="visit(item.username)">前往用餐</v-btn></article></div>
        </div></section>
        <section class="sr-card"><div class="sr-card-title sr-card-band"><h3><v-icon icon="mdi-map-marker-check-outline" size="19" />今日到访</h3></div><div class="sr-card-body sr-actions sr-wrap"><v-chip v-for="(record,i) in data.visits?.records || []" :key="i" size="small" color="success" prepend-icon="mdi-check-circle-outline">{{ record.target_username }}</v-chip><p v-if="!data.visits?.records?.length" class="sr-hint">今天还没有到访记录</p></div></section>
      </div>
      <div v-if="activeTab==='logs'" class="sr-stack">
        <section class="sr-card"><div class="sr-card-title sr-card-band sr-band-blue"><h3><v-icon icon="mdi-chart-timeline-variant" size="19" />经营日志</h3><v-select v-model="logDays" :items="[{title:'全部记录',value:0},{title:'最近 7 天',value:7},{title:'最近 30 天',value:30}]" aria-label="日志日期范围" class="sr-log-filter" /></div><div class="sr-card-body"><p class="sr-hint">站点返回 {{ data.logs?.length || 0 }} 条记录；筛选内净收益 {{ number(filteredLogs.reduce((n,r)=>n+Number(r.net_earnings||0),0)) }} 魔力。</p></div><v-table density="compact" class="sr-table"><thead><tr><th>日期</th><th>顾客完成 / 总数</th><th>欢迎值</th><th>净收益</th><th>流失</th></tr></thead><tbody><tr v-for="log in filteredLogs" :key="log.log_date"><td>{{ log.log_date }}</td><td>{{ log.customers_served }} / {{ log.customers_total }}</td><td>{{ number(log.popularity_change) }}</td><td>{{ number(log.net_earnings) }}</td><td>{{ log.details?.left || 0 }}</td></tr><tr v-if="!filteredLogs.length"><td colspan="5" class="sr-empty">暂无符合条件的经营记录</td></tr></tbody></v-table></section>
        <section class="sr-card"><div class="sr-card-title sr-card-band"><h3><v-icon icon="mdi-history" size="19" />最近操作</h3></div><v-table density="compact" class="sr-table"><thead><tr><th>时间</th><th>操作</th><th>结果</th></tr></thead><tbody><tr v-for="(event,i) in view.events || []" :key="i"><td>{{ new Date(event.time*1000).toLocaleString() }}</td><td>{{ actionLabels[event.action] || event.action }}</td><td class="sr-event-message">{{ event.message }}</td></tr><tr v-if="!view.events?.length"><td colspan="3" class="sr-empty">暂无最近操作</td></tr></tbody></v-table></section>
      </div>
      <v-dialog :model-value="!!confirmation" max-width="460" @update:model-value="value=>!value && cancelConfirm()" aria-labelledby="sr-confirm-title">
        <v-card class="sr-confirm-card" rounded="lg"><v-card-title id="sr-confirm-title">{{ confirmation?.title }}</v-card-title><v-card-text>{{ confirmation?.text }}</v-card-text><v-card-actions><v-spacer /><v-btn color="default" variant="text" @click="cancelConfirm">取消</v-btn><v-btn color="success" variant="tonal" @click="acceptConfirm">确认</v-btn></v-card-actions></v-card>
      </v-dialog>
    </v-defaults-provider>
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
const fastPolling = computed(()=>state.value.session_status==='open' || (view.value.kitchen || []).some(stove=>stove.status==='cooking') || Object.keys(view.value.cleaning || {}).length>0)
const blocked = computed(()=>busy.value || !!view.value.uncertain || !!view.value.automation?.enabled || !!view.value.automation?.active || !data.value.state)
const uiDefaults = { VBtn: { size: 'small', variant: 'tonal', color: 'success' }, VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VSelect: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VChip: { size: 'x-small', variant: 'tonal' } }
const dishOptions = computed(()=>unlockedDishes.value.map(d=>({title:`${d.name} · ${d.cook_time} 秒`,value:d.key})))
const seatOptions = stove=>matchingCustomers(stove).map(c=>({title:`餐位 ${c.seat} · ${patience(c)} 秒`,value:c.id}))
const tabs = [{id:'kitchen',label:'厨房与餐位',icon:'mdi-stove'},{id:'supplies',label:'食材与菜品',icon:'mdi-basket-outline'},{id:'staff',label:'员工',icon:'mdi-account-tie-outline'},{id:'visits',label:'下馆子',icon:'mdi-silverware-fork-knife'},{id:'logs',label:'经营日志',icon:'mdi-text-box-outline'}]
const roles = [{key:'chef',label:'厨师',icon:'mdi-chef-hat'},{key:'server',label:'服务员',icon:'mdi-account-tie-outline'}]
const actionLabels = {purchase_ingredient:'购买食材',hire_staff:'雇佣员工',update_staff_assignment:'员工调度',start_session:'开始营业',visit_restaurant:'下馆子',serve_customer:'上菜',discard_dish:'丢弃菜品',customer_left:'顾客离席',resolve:'核对解锁',automation:'自动经营',auto_visit:'自动下馆子',notification:'通知'}
const number = n => Number(n || 0).toLocaleString()
const statusLabel = computed(()=>({ready:'准备营业',open:'营业中',closed:'已闭店'}[state.value.session_status] || '未连接'))
const stats = computed(()=>[{label:'魔力余额',icon:'mdi-auto-fix',accent:'245,158,11',value:number(data.value.user?.magic)},{label:'受欢迎值',icon:'mdi-heart-outline',accent:'236,72,153',value:number(state.value.popularity)},{label:'今日顾客',icon:'mdi-account-group-outline',accent:'34,197,94',value:`${state.value.customers_served || 0} / ${state.value.customers_total || 0}`},{label:'今日净收益',icon:'mdi-cash-plus',accent:'59,130,246',value:number(state.value.net_earnings_today)},{label:'累计净收益',icon:'mdi-chart-line',accent:'139,92,246',value:number(state.value.net_earnings_total)}])
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
async function request(path,payload,verb='post',quiet=false){if(busy.value)return null;busy.value=true;try{const r=unwrap(await props.api[verb](`plugin/${props.pluginId}${path}`,payload));update(r);if(!quiet || !r.success){message.value=r.message || (r.success?'操作完成':'操作失败');ok.value=r.success}return r}catch(e){if(alive){message.value=e.message || '请求失败，请刷新后核对';ok.value=false;runStaff.value=false}return null}finally{busy.value=false;schedule()}}
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
function clearTimers(){clearTimeout(timer);clearInterval(clock);timer=null;clock=null}
function schedule(){
  clearTimers()
  if(!alive || document.hidden)return
  timer=setTimeout(poll,fastPolling.value?2000:60000)
  // Only running kitchen tasks need a local countdown between responses.
  if(fastPolling.value)clock=setInterval(()=>{now.value=Date.now()/1000+clockOffset},500)
}
async function poll(){
  if(!alive)return
  if(document.hidden || busy.value || confirmation.value){schedule();return}
  if(!data.value.state || view.value.automation?.active || view.value.automation?.enabled)await request('/state',undefined,'get',true)
  else await request('/tick',{run_staff:runStaff.value},'post',true)
}
function visibilityChanged(){
  if(document.hidden){clearTimers();return}
  if(alive && !busy.value && !confirmation.value)request('/state',undefined,'get',true)
  else schedule()
}
function start(){if(alive)return;alive=true;document.addEventListener('visibilitychange',visibilityChanged);if(!document.hidden)request('/state',undefined,'get',true)}
function stop(){alive=false;runStaff.value=false;clearTimers();document.removeEventListener('visibilitychange',visibilityChanged);cancelConfirm()}
onMounted(start);onActivated(start);onDeactivated(stop);onUnmounted(stop)
</script>

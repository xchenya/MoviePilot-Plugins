<template>
  <section class="sq-app" aria-label="思齐收垃圾">
    <header class="sq-topbar">
      <div class="sq-heading"><div class="sq-brand"><v-icon icon="mdi-beach" size="24" /></div><div><h2>思齐收垃圾 <v-chip size="x-small" variant="tonal" :color="view.enabled ? '#27865d' : undefined">{{ view.enabled ? '已启用' : '已暂停' }}</v-chip></h2><p>沙滩清理与每日搬砖</p></div></div>
      <div class="sq-actions">
        <v-btn variant="tonal" size="small" aria-label="刷新面板" title="刷新面板（读取插件缓存）" :loading="loading" @click="refresh"><v-icon icon="mdi-refresh" size="18" /><span class="sq-button-label">刷新</span></v-btn>
        <v-btn variant="tonal" size="small" aria-label="配置" @click="emit('switch', 'config')"><v-icon icon="mdi-cog-outline" size="18" /><span class="sq-button-label">配置</span></v-btn>
        <v-btn variant="text" size="small" aria-label="关闭" @click="emit('close')"><v-icon icon="mdi-close" size="18" /></v-btn>
      </div>
    </header>
    <v-alert v-if="message" :type="messageType" variant="tonal" density="compact" closable role="status" @click:close="message = ''">{{ message }}</v-alert>
    <v-alert v-if="view.auth_blocked" type="warning" variant="tonal" density="compact">Cookie 已失效，自动任务已暂停。请更新配置后再运行。</v-alert>
    <v-progress-linear v-if="loading && !loaded" indeterminate color="#27865d" aria-label="读取面板" />

    <div class="sq-stats">
      <article v-for="item in metrics" :key="item.label" class="sq-stat" :style="{'--sq-accent': item.accent}">
        <div class="sq-stat-icon"><v-icon :icon="item.icon" size="22" /></div><div><p>{{ item.label }}</p><strong>{{ loaded ? item.value : '—' }}</strong></div>
      </article>
    </div>

    <section class="sq-card">
      <div class="sq-card-heading"><h3><v-icon icon="mdi-calendar-clock-outline" size="18" />任务状态</h3><v-btn color="#27865d" variant="tonal" size="small" :loading="starting || view.running" :disabled="!loaded || starting || view.running" prepend-icon="mdi-play" @click="runOnce">运行一次</v-btn></div>
      <div class="sq-task-grid">
        <article class="sq-task"><div class="sq-task-heading"><v-icon icon="mdi-trash-can-outline" color="#27865d" size="20" /><h4>沙滩清理</h4><v-chip size="x-small" variant="tonal">{{ view.schedule || '读取中' }}</v-chip></div><p class="sq-result">{{ stats.clean_result || '暂无执行记录' }}</p><div class="sq-next"><span>下次执行时间</span><strong>{{ view.beach_next || '—' }}</strong></div></article>
        <article class="sq-task"><div class="sq-task-heading"><v-icon icon="mdi-wall" color="#b66b2a" size="20" /><h4>每日搬砖</h4><v-chip size="x-small" variant="tonal" :color="view.auto_brick ? '#b66b2a' : undefined">{{ view.auto_brick ? '已开启' : '未开启' }}</v-chip></div><p class="sq-result">{{ view.brick_today_result || '今日暂无成功搬砖记录' }}</p><div class="sq-next"><span>下次执行时间</span><strong>{{ view.brick_next || '—' }}</strong></div></article>
      </div>
    </section>

    <section class="sq-card">
      <v-tabs v-model="tab" color="#27865d" density="compact" class="sq-tabs"><v-tab value="inventory"><v-icon icon="mdi-package-variant-closed" size="18" class="mr-2" />物品库存</v-tab><v-tab value="history"><v-icon icon="mdi-history" size="18" class="mr-2" />执行记录</v-tab></v-tabs>
      <div v-if="tab === 'inventory'" class="sq-card-body">
        <p class="sq-hint sq-stock-note">{{ stockNote }}</p>
        <div v-if="items.length" class="sq-inventory"><div v-for="item in items" :key="item.name" class="sq-item"><v-icon :icon="itemIcon(item.name)" size="20" color="#27865d" /><span>{{ item.name }}</span><strong>{{ number(item.count) }}</strong></div></div>
        <div v-else class="sq-empty"><v-icon icon="mdi-package-variant" size="32" /><p>{{ loaded ? '暂无库存数据，运行任务后自动更新' : '正在读取库存' }}</p></div>
      </div>
      <div v-else class="sq-history">
        <v-table density="compact" hover><thead><tr><th>执行时间</th><th>清理 / 搬砖</th><th>状态</th></tr></thead><tbody><tr v-for="(record, index) in history" :key="index"><td class="sq-time">{{ formatTime(record.time) }}</td><td><p>清理：{{ record.clean?.message || '未记录' }}</p><p>搬砖：{{ record.brick?.message || '未记录' }}</p></td><td><v-chip size="x-small" variant="tonal" :color="status(record.status).color">{{ status(record.status).label }}</v-chip></td></tr></tbody></v-table>
        <p v-if="!history.length" class="sq-empty">暂无执行记录</p>
      </div>
    </section>
    <footer class="sq-footer"><span>{{ view.running ? '任务运行中，结果将自动更新' : '等待期间不访问站点' }}</span><span>v{{ view.version || '2.5.0' }} · xchenya</span></footer>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({ api: Object, pluginId: { type: String, default: 'SiQiCleanBeach' } })
const emit = defineEmits(['switch', 'close'])
const data = ref({ stats: {}, inventory: {}, display: {} })
const loading = ref(false)
const loaded = ref(false)
const starting = ref(false)
const message = ref('')
const messageType = ref('info')
const tab = ref('inventory')
const view = computed(() => data.value.display || {})
const stats = computed(() => data.value.stats || {})
const inventory = computed(() => data.value.inventory || {})
const items = computed(() => Object.entries(inventory.value).map(([name, item]) => ({ name, count: item.count || 0 })).sort((a, b) => b.count - a.count))
const history = computed(() => [...(stats.value.history || [])].slice(-20).reverse())
const metrics = computed(() => [
  { label: '物品总数', value: number(items.value.reduce((sum, item) => sum + item.count, 0)), icon: 'mdi-package-variant-closed', accent: '39,134,93' },
  { label: '物品种类', value: number(items.value.length), icon: 'mdi-shape-outline', accent: '65,115,193' },
  { label: '今日搬砖', value: `${view.value.daily_bricks ?? '—'} / 50`, icon: 'mdi-wall', accent: '182,107,42' },
  { label: '砖块库存', value: inventory.value['砖块'] ? number(inventory.value['砖块'].count) : '—', icon: 'mdi-cube-outline', accent: '139,91,171' },
])
const stockNote = computed(() => !stats.value.last_update ? '等待首次库存同步' : `库存更新于 ${formatTime(stats.value.last_update)} · ${stats.value.inventory_refreshed ? '最近一轮已刷新' : '缓存，最近一轮未刷新'}`)
const apiGet = (path) => props.api.get(`plugin/${props.pluginId}${path}`)
const apiPost = (path, payload) => props.api.post(`plugin/${props.pluginId}${path}`, payload)
const number = (value) => Number(value || 0).toLocaleString('zh-CN')
function formatTime(value) {
  if (!value) return '—'
  const date = new Date(Number(value) * 1000)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('sv-SE', { timeZone: view.value.timezone || 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function itemIcon(name) {
  return ({ '砖块': 'mdi-wall', '木材': 'mdi-tree-outline', '塑料袋': 'mdi-shopping-outline', '瓶子': 'mdi-bottle-soda-outline', '螺丝': 'mdi-screw-flat-top', '旧电池': 'mdi-battery-outline', '破铜片': 'mdi-circle-multiple-outline', '木工件': 'mdi-hand-saw', '塑料件': 'mdi-pail-outline', '简易工具': 'mdi-tools', '能量碎片': 'mdi-lightning-bolt-outline', '魔丸胚胎': 'mdi-egg-outline', '魔丸': 'mdi-flask-outline', '蚯蚓': 'mdi-bug-outline' })[name] || 'mdi-package-variant'
}
function status(value) {
  return ({ completed: { label: '全部完成', color: '#27865d' }, partial: { label: '部分完成', color: '#9b680a' }, auth_failed: { label: '认证失败', color: '#bb3939' }, error: { label: '执行失败', color: '#bb3939' } })[value] || { label: '待核对', color: '#9b680a' }
}
let timer
let disposed = false
function scheduleRefresh() {
  clearTimeout(timer)
  if (!disposed && view.value.running && !document.hidden) timer = setTimeout(refresh, 3000)
}
async function refresh() {
  if (loading.value || disposed) return
  loading.value = true
  try {
    const result = await apiGet('/stats')
    if (!result?.success || !result.data?.stats || !result.data?.inventory) throw new Error('invalid response')
    data.value = result.data
    loaded.value = true
  } catch {
    message.value = '读取面板失败，请稍后点击刷新。'
    messageType.value = 'error'
  } finally {
    loading.value = false
    scheduleRefresh()
  }
}
async function runOnce() {
  if (starting.value || view.value.running || !loaded.value) return
  starting.value = true
  try {
    const result = await apiPost('/run')
    message.value = result?.message || '请刷新查看任务状态'
    messageType.value = result?.success ? 'info' : 'warning'
  } catch {
    message.value = '运行请求未能确认，请刷新核对任务状态。'
    messageType.value = 'warning'
  } finally {
    starting.value = false
    await refresh()
  }
}
function visibilityChanged() {
  clearTimeout(timer)
  if (!document.hidden) refresh()
}
onMounted(() => { refresh(); document.addEventListener('visibilitychange', visibilityChanged) })
onUnmounted(() => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibilityChanged) })
</script>

<style scoped src="../style.css"></style>

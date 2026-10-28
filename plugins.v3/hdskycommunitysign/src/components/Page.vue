<script setup>
import { computed, onMounted, ref } from 'vue'
import { connectionLabel, number, statusColor, statusLabel, time } from '../format.js'
import '../style.css'

const props = defineProps({ api: { type: Object, required: true }, pluginId: { type: String, required: true } })
const emit = defineEmits(['switch', 'close', 'action'])
const view = ref(null), busy = ref(''), message = ref(''), messageType = ref('info'), period = ref(7)
const stats = computed(() => view.value?.statistics || {})
const today = computed(() => stats.value.today || {})
const rows = computed(() => (stats.value.days || []).slice(0, period.value))

async function load() {
  if (busy.value) return
  busy.value = 'load'
  try {
    view.value = await props.api.get(`plugin/${props.pluginId}/state`)
    message.value = ''
    if (view.value.auth.cookie_configured) {
      const result = await props.api.post(`plugin/${props.pluginId}/auth`, { action: 'check' })
      view.value = result.state
      if (!result.success) { message.value = result.message; messageType.value = 'warning' }
    }
  }
  catch { message.value = '读取统计失败，请点击刷新重试。'; messageType.value = 'error' }
  finally { busy.value = '' }
}
async function sign() {
  if (busy.value) return
  busy.value = 'sign'
  try {
    const result = await props.api.post(`plugin/${props.pluginId}/sign`)
    view.value = result.state
    message.value = result.message
    messageType.value = result.success ? 'success' : 'warning'
    emit('action')
  } catch {
    message.value = '签到请求未完成，请刷新查看已保存结果；本次不会自动重发。'
    messageType.value = 'error'
    try { view.value = await props.api.get(`plugin/${props.pluginId}/state`) } catch { /* 保留现有统计 */ }
  } finally { busy.value = '' }
}
onMounted(load)
</script>

<template>
  <section class="hcs-app">
    <header class="hcs-header">
      <div><h2>每日签到统计</h2><p>天空社区 · {{ stats.uid ? `UID ${stats.uid}` : '请先登录社区账号' }}</p></div>
      <div class="hcs-actions">
        <v-btn color="primary" variant="tonal" :disabled="!!busy" :loading="busy === 'load'" @click="load">刷新余额与统计</v-btn>
        <v-btn color="primary" variant="tonal" :disabled="!!busy" @click="emit('switch')">配置</v-btn>
        <v-btn variant="text" @click="emit('close')">关闭</v-btn>
      </div>
    </header>
    <v-alert v-if="message" :type="messageType" variant="tonal" role="status">{{ message }}</v-alert>
    <v-alert v-if="view?.status.message" :type="view.status.success ? 'success' : 'info'" variant="tonal">{{ view.status.message }}</v-alert>
    <p v-if="view" class="hcs-hint">{{ connectionLabel(view.auth.connection_status) }} · {{ time(view.auth.connection_at) }}；上次查询余额 {{ number(view.auth.balance) }} 银元 · {{ time(view.auth.balance_at) }}</p>
    <v-alert v-if="view?.retry.pending" type="info" variant="tonal">已安排签到重试：已用 {{ view.retry.used }} / {{ view.retry.limit }} 次，下次 {{ time(view.retry.next_at) }}。结果未知时仅查询确认。</v-alert>
    <v-alert v-else-if="view?.retry.limit && view.retry.used >= view.retry.limit" type="warning" variant="tonal">自动重试次数已用完，请检查连接或重新登录后手动签到。</v-alert>

    <div class="hcs-summary">
      <article class="hcs-card"><p>今日签到 · {{ today.day || '北京时间' }}</p><strong>{{ statusLabel(today.status) }}</strong><v-chip v-if="view" :color="view.config.enabled ? 'success' : 'default'" size="small" variant="tonal">{{ view.config.enabled ? '插件已启用' : '插件未启用' }}</v-chip></article>
      <article class="hcs-card"><p>今日奖励</p><strong>{{ number(today.amount) }} <small>银元</small></strong><p>当前余额 {{ number(view?.auth.balance) }} 银元（只读查询，无需签到）</p></article>
      <article class="hcs-card"><p>近 30 天已签到</p><strong>{{ number(stats.completed_days) }} <small>天</small></strong><p>同一账号每天计一次</p></article>
      <article class="hcs-card"><p>近 30 天奖励合计</p><strong>{{ number(stats.reward_total) }} <small>银元</small></strong><p>{{ stats.unknown_reward_days ? `另有 ${stats.unknown_reward_days} 天奖励数值未知` : '按已确认的每日奖励汇总' }}</p></article>
    </div>

    <div class="hcs-actions">
      <v-btn color="primary" variant="flat" :disabled="!!busy || !view?.config.enabled || !view?.auth.cookie_configured" :loading="busy === 'sign'" @click="sign">立即签到</v-btn>
      <span class="hcs-hint">{{ !view?.config.enabled ? '在配置页启用插件并保存后可签到。' : '先查询社区今日状态，已签到会自动跳过提交。' }}</span>
    </div>
    <section class="hcs-card">
      <div class="hcs-card-title"><h3>每日明细</h3><v-btn-toggle v-model="period" mandatory density="compact" color="primary" variant="tonal"><v-btn :value="7">近 7 天</v-btn><v-btn :value="30">近 30 天</v-btn></v-btn-toggle></div>
      <p class="hcs-hint">按北京时间归档，仅统计当前账号。尚无记录表示未被插件记录，不能据此判断漏签。</p>
      <div v-if="rows.length" class="hcs-table-wrap">
        <table class="hcs-table"><thead><tr><th>日期</th><th>状态</th><th>奖励 / 银元</th><th>余额 / 银元</th><th>记录时间</th></tr></thead><tbody>
          <tr v-for="row in rows" :key="row.day"><td>{{ row.day }}</td><td><v-chip :color="statusColor(row.status)" size="small" variant="tonal">{{ statusLabel(row.status) }}</v-chip></td><td>{{ number(row.amount) }}</td><td>{{ number(row.balance) }}</td><td>{{ row.time ? time(row.time) : '—' }}</td></tr>
        </tbody></table>
      </div>
      <p v-else class="hcs-hint">登录后刷新即可查询余额与每日状态，无需先签到。</p>
    </section>
    <v-expansion-panels v-if="view?.history.length" variant="accordion"><v-expansion-panel elevation="0"><v-expansion-panel-title>最近操作记录</v-expansion-panel-title><v-expansion-panel-text><div class="hcs-stack"><p v-for="(row, index) in view.history" :key="index" class="hcs-hint">{{ time(row.time) }} · UID {{ row.uid || '—' }} · {{ row.message }}</p></div></v-expansion-panel-text></v-expansion-panel></v-expansion-panels>
  </section>
</template>

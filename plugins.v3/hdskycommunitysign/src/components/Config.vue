<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { connectionLabel, number, time } from '../format.js'
import '../style.css'

const props = defineProps({ api: { type: Object, required: true }, pluginId: { type: String, required: true } })
const emit = defineEmits(['switch', 'close'])
const config = reactive({ enabled: false, uid: '', use_proxy: false, user_agent: '', auto_sign: false, notify: true, cron: '0 8 * * *', retry_count: 3, retry_interval: 300 })
const view = ref(null), loaded = ref(false), busy = ref(''), message = ref(''), messageType = ref('info')
const code = ref(''), cookie = ref(''), now = ref(Date.now() / 1000)
const auth = computed(() => view.value?.auth || {})
const uidValid = computed(() => /^[1-9][0-9]{0,11}$/.test(config.uid.trim()))
const cooldown = after => Math.max(0, Math.ceil((after || 0) - now.value))
const sendWait = computed(() => cooldown(Math.max(auth.value.send_after || 0, auth.value.retry_after || 0)))
const loginWait = computed(() => cooldown(Math.max(auth.value.verify_after || 0, auth.value.retry_after || 0)))
const blocked = computed(() => !loaded.value || !!busy.value)
const retryValid = computed(() => Number.isInteger(config.retry_count) && config.retry_count >= 0 && config.retry_count <= 10
  && Number.isInteger(config.retry_interval) && config.retry_interval >= 60 && config.retry_interval <= 86400)
const defaults = { VTextField: { variant: 'outlined', density: 'compact', hideDetails: 'auto' }, VBtn: { variant: 'tonal', color: 'primary' } }
let timer

async function load() {
  busy.value = 'load'
  try {
    view.value = await props.api.get(`plugin/${props.pluginId}/state`)
    Object.assign(config, view.value.config)
    loaded.value = true
    message.value = ''
  } catch {
    message.value = '读取配置失败，请重试。'
    messageType.value = 'error'
  } finally { busy.value = '' }
}

async function perform(action) {
  if (blocked.value) return
  busy.value = action
  message.value = ''
  try {
    const payload = action === 'save' ? { ...config } : {
      action, uid: config.uid.trim(), use_proxy: config.use_proxy, user_agent: config.user_agent,
      ...(action === 'login' ? { code: code.value } : {}),
      ...(action === 'cookie' ? { cookie: cookie.value } : {}),
    }
    const result = await props.api.post(`plugin/${props.pluginId}/${action === 'save' ? 'config' : 'auth'}`, payload)
    view.value = result.state
    if (action === 'save' && result.success) Object.assign(config, result.state.config)
    now.value = Date.now() / 1000
    message.value = result.message
    messageType.value = result.success ? 'success' : 'warning'
  } catch {
    message.value = '操作请求未完成，请检查连接后重试；本次不会自动重发。'
    messageType.value = 'error'
    // 只读本地状态，恢复已保存的冷却；不重复发送验证码或登录请求。
    try { view.value = await props.api.get(`plugin/${props.pluginId}/state`) } catch { /* 保留现有状态 */ }
  } finally {
    if (action === 'login') code.value = ''
    if (action === 'cookie') cookie.value = ''
    busy.value = ''
  }
}

onMounted(() => { load(); timer = setInterval(() => { now.value = Date.now() / 1000 }, 1000) })
onBeforeUnmount(() => { clearInterval(timer); code.value = ''; cookie.value = '' })
</script>

<template>
  <section class="hcs-app">
    <v-defaults-provider :defaults="defaults">
      <header class="hcs-header">
        <div><h2>天空社区客户端签到</h2><p>登录与自动签到设置</p></div>
        <div class="hcs-actions">
          <v-btn :disabled="!!busy" @click="emit('switch')">每日统计</v-btn>
          <v-btn :disabled="blocked || !retryValid" :loading="busy === 'save'" @click="perform('save')">保存设置</v-btn>
          <v-btn variant="text" @click="emit('close')">关闭</v-btn>
        </div>
      </header>
      <v-alert v-if="message" :type="messageType" variant="tonal" role="status">{{ message }}</v-alert>
      <v-progress-linear v-if="busy === 'load'" indeterminate color="primary" aria-label="读取配置" />
      <v-btn v-if="!loaded && !busy" @click="load">重新读取</v-btn>

      <section class="hcs-card">
        <div class="hcs-card-title"><h3>社区登录</h3><v-chip :color="auth.verified ? 'success' : 'default'" size="small" variant="tonal">{{ auth.verified ? '已登录' : auth.cookie_configured ? '会话待验证' : '未登录' }}</v-chip></div>
        <p class="hcs-hint">填写 UID 后直接获取验证码并登录，无需保存或关闭页面。</p>
        <p v-if="auth.uid" class="hcs-account">{{ auth.display_name || '社区账号' }} · UID {{ auth.uid }}<span>上次验证 {{ time(auth.checked_at) }}</span></p>
        <div class="hcs-login-row">
          <v-text-field v-model="config.uid" label="HDSky UID" aria-label="HDSky UID" inputmode="numeric" maxlength="12" :disabled="blocked" autocomplete="off" />
          <v-btn :disabled="blocked || !uidValid || sendWait > 0" :loading="busy === 'send'" @click="perform('send')">{{ sendWait ? `${sendWait} 秒后可重发` : '发送验证码' }}</v-btn>
        </div>
        <div class="hcs-login-row">
          <v-text-field v-model="code" label="站内信六位验证码" aria-label="站内信六位验证码" type="password" inputmode="numeric" maxlength="6" autocomplete="one-time-code" :disabled="blocked" @keydown.enter="!blocked && uidValid && /^\d{6}$/.test(code) && auth.pending_uid === config.uid.trim() && !loginWait && perform('login')" />
          <v-btn :disabled="blocked || !uidValid || !/^\d{6}$/.test(code) || auth.pending_uid !== config.uid.trim() || loginWait > 0" :loading="busy === 'login'" @click="perform('login')">{{ loginWait ? `${loginWait} 秒后可登录` : '登录' }}</v-btn>
        </div>
        <div class="hcs-actions"><v-btn :disabled="blocked || !auth.cookie_configured || cooldown(auth.retry_after) > 0" :loading="busy === 'check'" @click="perform('check')">检测 Cookie 与站点连通性</v-btn><span class="hcs-hint">检测已保存的 Cookie，只读查询，不执行签到。</span></div>
        <p class="hcs-hint">{{ connectionLabel(auth.connection_status) }} · {{ time(auth.connection_at) }}<br>上次查询余额 {{ number(auth.balance) }} 银元 · {{ time(auth.balance_at) }}</p>
      </section>

      <section class="hcs-card">
        <h3>自动签到</h3>
        <div class="hcs-switches">
          <v-switch v-model="config.enabled" label="启用插件" aria-label="启用插件" color="primary" hide-details :disabled="blocked" />
          <v-switch v-model="config.auto_sign" label="每日定时签到" aria-label="每日定时签到" color="primary" hide-details :disabled="blocked" />
          <v-switch v-model="config.notify" label="发送结果通知" aria-label="发送结果通知" color="primary" hide-details :disabled="blocked" />
        </div>
        <v-text-field v-model="config.cron" label="签到 Cron" aria-label="签到 Cron" hint="默认每天 08:00，执行时区跟随 MP。" persistent-hint :disabled="blocked" />
        <div class="hcs-login-row">
          <v-text-field v-model.number="config.retry_count" type="number" min="0" max="10" step="1" label="签到重试次数" aria-label="签到重试次数" hint="0 关闭，最多 10 次；不含首次签到。" persistent-hint :disabled="blocked" />
          <v-text-field v-model.number="config.retry_interval" type="number" min="60" max="86400" step="1" label="重试间隔（秒）" aria-label="重试间隔（秒）" hint="60–86400 秒；遇到限流会等待冷却结束。" persistent-hint :disabled="blocked" />
        </div>
        <p class="hcs-hint">失败后按间隔自动重试，手动签到同样适用。结果未知时只查询状态；Cookie 失效停止重试。任务由 MP 管理，每 30 秒检查一次到期计划。</p>
        <v-alert v-if="loaded && !retryValid" type="warning" variant="tonal">重试次数须为 0–10 的整数，间隔须为 60–86400 秒的整数。</v-alert>
        <p class="hcs-hint">自动签到设置在点击“保存设置”后生效。</p>
      </section>

      <v-expansion-panels variant="accordion">
        <v-expansion-panel elevation="0">
          <v-expansion-panel-title>手动 Cookie 与连接设置</v-expansion-panel-title>
          <v-expansion-panel-text>
            <div class="hcs-stack">
              <p class="hcs-hint">也可使用 hdsky.supertimi.de 社区的 Cookie 登录。UID 可留空，填写时会核对账号；此处不使用 hdsky.me 主站 Cookie。</p>
              <v-text-field v-model="cookie" label="社区 Cookie" aria-label="社区 Cookie" type="password" autocomplete="new-password" :disabled="blocked" />
              <v-btn :disabled="blocked || !cookie.trim() || cooldown(auth.retry_after) > 0" :loading="busy === 'cookie'" @click="perform('cookie')">验证并保存 Cookie</v-btn>
              <v-switch v-model="config.use_proxy" label="使用 MP 代理" aria-label="使用 MP 代理" color="primary" hide-details :disabled="blocked" />
              <v-text-field v-model="config.user_agent" label="User-Agent" aria-label="User-Agent" :disabled="blocked" />
              <p class="hcs-hint">登录操作会应用当前 UID 和连接设置。验证码与手动 Cookie 输入在提交后清空。</p>
            </div>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-defaults-provider>
  </section>
</template>

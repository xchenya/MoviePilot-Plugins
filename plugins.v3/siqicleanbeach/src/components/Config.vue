<template>
  <section class="sq-app" aria-label="思齐收垃圾配置">
    <header class="sq-topbar"><div class="sq-heading"><div class="sq-brand"><v-icon icon="mdi-cog-outline" size="24" /></div><div><h2>思齐收垃圾 · 配置</h2><p>管理清理、搬砖与运行通知</p></div></div><div class="sq-actions"><v-btn variant="tonal" size="small" aria-label="状态页" @click="emit('switch', 'page')"><v-icon icon="mdi-view-dashboard-outline" size="18" /><span class="sq-button-label">状态页</span></v-btn><v-btn color="#27865d" variant="tonal" size="small" prepend-icon="mdi-content-save-outline" :loading="saving" :disabled="!loaded || saving" @click="saveConfig">保存</v-btn><v-btn variant="text" size="small" aria-label="关闭" @click="emit('close')"><v-icon icon="mdi-close" size="18" /></v-btn></div></header>
    <v-alert v-if="message" :type="messageType" density="compact" variant="tonal" closable role="status" @click:close="message = ''">{{ message }}<v-btn v-if="!loaded && !loading" variant="text" size="small" @click="loadConfig">重新加载</v-btn></v-alert>
    <v-progress-linear v-if="loading" indeterminate color="#27865d" aria-label="读取配置" />
    <fieldset class="sq-form" :disabled="!loaded || saving">
      <section class="sq-card"><div class="sq-card-heading"><h3><v-icon icon="mdi-toggle-switch-outline" size="18" color="#27865d" />基础设置</h3></div><div class="sq-switch-grid sq-card-body"><label v-for="item in switches" :key="item.key" class="sq-switch" :class="{'sq-switch-active': config[item.key]}" :style="{'--sq-accent': item.accent}"><div><v-icon :icon="item.icon" size="20" /><span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span></div><v-switch v-model="config[item.key]" :color="item.color" :aria-label="item.label" :disabled="!loaded || saving" density="compact" hide-details /></label></div></section>
      <div class="sq-config-grid">
        <section class="sq-card"><div class="sq-card-heading"><h3><v-icon icon="mdi-trash-can-outline" size="18" color="#27865d" />沙滩清理</h3></div><div class="sq-fields"><v-select v-model="config.schedule_mode" :items="modes" label="定时模式" density="compact" variant="outlined" hide-details /><p class="sq-hint" v-if="config.schedule_mode === 'auto'">按两小时冷却自动安排，到期后约 15 秒执行；等待期间不访问站点。</p><v-text-field v-if="config.schedule_mode === 'cron'" v-model="config.cron" label="清理 Cron 表达式" placeholder="5 */2 * * *" density="compact" variant="outlined" hint="例如 5 */2 * * *，每两小时的第 5 分钟" persistent-hint /><v-text-field v-if="config.schedule_mode === 'interval'" v-model.number="config.interval_minutes" label="执行间隔（分钟）" type="number" min="1" density="compact" variant="outlined" hint="兼容旧版配置，推荐使用按站点冷却" persistent-hint /></div></section>
        <section class="sq-card"><div class="sq-card-heading"><h3><v-icon icon="mdi-wall" size="18" color="#b66b2a" />每日搬砖</h3><v-switch v-model="config.auto_brick" color="#b66b2a" aria-label="自动搬砖" :disabled="!loaded || saving" density="compact" hide-details /></div><div class="sq-fields"><v-text-field v-model="config.brick_cron" :disabled="!config.auto_brick" label="搬砖独立 Cron（可选）" placeholder="0 10,16 * * *" clearable density="compact" variant="outlined" hint="留空沿用原调度；示例为每天 10 点、16 点" persistent-hint /><v-text-field v-model.number="config.brick_retry_limit" :disabled="!config.auto_brick" label="失败重试次数" type="number" min="0" max="10" density="compact" variant="outlined" hint="默认 1 次，0 关闭；写入结果不确定时不重发" persistent-hint /><p class="sq-hint">每日上限 50 块，按服务端零点重置。Cron 使用 MoviePilot 时区。</p></div></section>
      </div>
      <section class="sq-card"><div class="sq-card-heading"><h3><v-icon icon="mdi-cookie-outline" size="18" color="#9b680a" />站点连接</h3></div><div class="sq-fields"><v-text-field v-model="config.cookie" :type="showCookie ? 'text' : 'password'" label="思齐 Cookie" autocomplete="off" density="compact" variant="outlined" :append-inner-icon="showCookie ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" @click:append-inner="showCookie = !showCookie" hint="留空自动读取 MoviePilot 站点管理中的思齐 Cookie" persistent-hint /><p class="sq-hint">保存后立即运行仅执行一次，随后自动关闭。</p></div></section>
    </fieldset>
    <footer class="sq-footer"><span>v2.5.0 · xchenya</span><v-btn variant="text" size="small" :disabled="!loaded || saving" :loading="saving" @click="saveConfig">保存配置</v-btn></footer>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'

const props = defineProps({ api: Object, pluginId: { type: String, default: 'SiQiCleanBeach' }, initialConfig: { type: Object, default: () => ({}) } })
const emit = defineEmits(['switch', 'close', 'config-updated'])
const config = reactive({ enabled: false, notify: true, run_once: false, schedule_mode: 'auto', cron: '1 */2 * * *', interval_minutes: 121, auto_brick: false, brick_cron: '', brick_retry_limit: 1, cookie: '' })
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const showCookie = ref(false)
const message = ref('')
const messageType = ref('info')
const modes = [{ title: '按站点冷却（推荐）', value: 'auto' }, { title: '固定时间（Cron）', value: 'cron' }, { title: '旧版固定间隔', value: 'interval' }]
const switches = [
  { key: 'enabled', label: '启用插件', description: '开启后台定时任务', icon: 'mdi-power-plug-outline', accent: '39,134,93', color: '#27865d' },
  { key: 'notify', label: '运行通知', description: '通过 MP 发送任务结果', icon: 'mdi-bell-outline', accent: '65,115,193', color: '#4173c1' },
  { key: 'run_once', label: '保存后运行一次', description: '运行后自动关闭此开关', icon: 'mdi-play-circle-outline', accent: '139,91,171', color: '#8b5bab' },
]
const apiGet = (path) => props.api.get(`plugin/${props.pluginId}${path}`)
const apiPost = (path, payload) => props.api.post(`plugin/${props.pluginId}${path}`, payload)
function applyConfig(value) {
  for (const key of Object.keys(config)) if (Object.hasOwn(value, key)) config[key] = value[key]
}
function validConfig(value) {
  return typeof value?.enabled === 'boolean' && modes.some(mode => mode.value === value.schedule_mode)
}
async function loadConfig() {
  loading.value = true
  loaded.value = false
  try {
    const result = await apiGet('/config')
    if (!validConfig(result)) throw new Error('invalid config')
    applyConfig(result)
    loaded.value = true
    message.value = ''
  } catch {
    message.value = '配置读取失败，请重新加载后再保存。'
    messageType.value = 'error'
  } finally { loading.value = false }
}
async function saveConfig() {
  if (!loaded.value || saving.value) return
  saving.value = true
  try {
    const result = await apiPost('/config', { ...config, brick_cron: config.brick_cron || '' })
    if (result?.success !== false && (result?.success !== true || !validConfig(result.config))) {
      message.value = '保存结果未能确认，请重新加载核对。'
      messageType.value = 'error'
      loaded.value = false
      return
    }
    if (result.success === false) {
      message.value = result?.message || '配置未保存，请稍后重试。'
      messageType.value = 'error'
      return
    }
    applyConfig(result.config)
    emit('config-updated', result.config)
    message.value = result.message || '配置已保存'
    messageType.value = 'success'
  } catch (error) {
    const status = error?.response?.status ?? error?.status
    message.value = status === 422 ? '设置格式不正确，请检查 Cron、间隔与重试次数后再保存。' : '保存结果未能确认，请重新加载核对。'
    messageType.value = 'error'
    if (status !== 422) loaded.value = false
  } finally { saving.value = false }
}
onMounted(loadConfig)
</script>

<style scoped src="../style.css"></style>

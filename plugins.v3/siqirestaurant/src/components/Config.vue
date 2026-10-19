<template>
  <section class="sr-app sr-config">
    <v-defaults-provider :defaults="fieldDefaults">
      <header class="sr-topbar">
        <div class="sr-topbar-left">
          <div class="sr-topbar-icon"><v-icon icon="mdi-cog-outline" size="24" /></div>
          <div class="sr-topbar-copy"><h2>思齐餐厅 · 配置</h2><p>管理自动经营、下馆子与运行通知</p></div>
        </div>
        <v-btn-group variant="tonal" density="compact" class="sr-topbar-actions">
          <v-btn color="success" aria-label="返回餐厅" title="返回餐厅" @click="emit('switch','page')"><v-icon icon="mdi-view-dashboard-outline" size="18" /><span>餐厅</span></v-btn>
          <v-btn color="success" aria-label="保存配置" title="保存配置" @click="save" :loading="saving" :disabled="saving || !loaded"><v-icon icon="mdi-content-save-outline" size="18" /><span>保存</span></v-btn>
          <v-btn color="success" aria-label="关闭" title="关闭" @click="emit('close')"><v-icon icon="mdi-close" size="18" /><span>关闭</span></v-btn>
        </v-btn-group>
      </header>
      <v-alert v-if="message" :type="messageType" variant="tonal" density="compact" closable role="status" @click:close="message=''">{{ message }}</v-alert>
      <v-progress-linear v-if="!loaded && !message" indeterminate color="success" aria-label="读取配置" />
      <section v-for="group in switchGroups" :key="group.title" class="sr-card sr-config-card">
        <div class="sr-card-title"><h3><v-icon :icon="group.icon" :color="group.color" size="18" />{{ group.title }}</h3></div>
        <div class="sr-switch-grid">
          <div v-for="item in group.items" :key="item.key" class="sr-switch-item" :class="{'sr-switch-active':config[item.key]}" :style="{'--sr-accent':item.accent}">
            <div class="sr-switch-copy"><v-icon :icon="item.icon" size="20" /><div><label :for="`sr-${item.key}`">{{ item.label }}</label><p>{{ item.desc }}</p></div></div>
            <v-switch :id="`sr-${item.key}`" v-model="config[item.key]" :aria-label="item.label" :color="item.color" :disabled="!loaded" hide-details density="compact" />
          </div>
        </div>
      </section>
      <section class="sr-card sr-config-card">
        <div class="sr-card-title"><h3><v-icon icon="mdi-tune-variant" color="info" size="18" />经营参数</h3><v-chip size="x-small" variant="tonal" color="info">北京时间</v-chip></div>
        <div class="sr-form-grid">
          <v-text-field v-model="config.start_time" label="每日开业时间" type="time" prepend-inner-icon="mdi-clock-outline" />
          <v-text-field v-model.number="config.daily_budget" label="每日采购预算（魔力）" type="number" min="0" max="1000000" step="1" prepend-inner-icon="mdi-basket-outline" />
          <v-text-field v-model.number="config.magic_reserve" label="最低保留魔力" type="number" min="0" max="1000000000" step="1" prepend-inner-icon="mdi-shield-check-outline" />
        </div>
        <p class="sr-hint">错过开业时间会补开；关闭页面后继续运行。采购预算每日重置，保存设置与重启不会清零。</p>
      </section>
      <section class="sr-card sr-config-card">
        <div class="sr-card-title"><h3><v-icon icon="mdi-account-group-outline" color="#ec4899" size="18" />下馆子名单</h3><v-chip size="x-small" variant="tonal" color="#ec4899">{{ targets.some(t=>t.trim())?'指定用户':'随机 3 人' }}</v-chip></div>
        <div class="sr-form-grid sr-visit-fields">
          <v-text-field v-for="(_,i) in targets" :key="i" v-model.trim="targets[i]" :label="`用户名 ${i+1}（选填）`" :aria-label="`下馆子用户名 ${i+1}`" maxlength="64" placeholder="留空可随机" prepend-inner-icon="mdi-account-outline" />
        </div>
        <p class="sr-hint">全部留空时，每天随机选择 3 位不同用户；填写后只到访名单中的用户，空位不补人。不可到访的用户会跳过并记录原因。</p>
        <p class="sr-hint">沿用开业时间，可单独开启下馆子。已用次数会扣除，重启不会重复到访；开启后按原站“一键下馆子”规则确认到访，为对方增加顾客。</p>
      </section>
      <v-expansion-panels class="sr-expansions" variant="accordion" multiple>
        <v-expansion-panel elevation="0">
          <v-expansion-panel-title><div class="sr-expansion-heading"><v-icon icon="mdi-cookie-outline" size="18" color="#f59e0b" /><strong>连接与凭据</strong><div class="sr-connection-status"><v-chip size="x-small" :color="config.site_configured?'success':'default'">{{ !loaded?'读取中':config.site_configured?'站点已关联':'站点未关联' }}</v-chip><v-chip size="x-small" :color="config.cookie_configured?'success':'warning'">{{ !loaded?'读取中':config.cookie_configured?'Cookie 已配置':'Cookie 未配置' }}</v-chip></div></div></v-expansion-panel-title>
          <v-expansion-panel-text>
            <div class="sr-stack">
              <p class="sr-hint">优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent；未关联时，可先在 MP 添加思齐站点。</p>
              <v-text-field v-model="cookie" label="手动 Cookie（选填）" type="password" autocomplete="new-password" prepend-inner-icon="mdi-key-outline" placeholder="仅在需要覆盖站点 Cookie 时填写" hint="留空保留现有配置，已保存的凭据不会回显。" persistent-hint />
              <v-checkbox v-model="clearCookie" label="清除插件内手动 Cookie，改用站点管理" color="warning" density="compact" hide-details />
            </div>
          </v-expansion-panel-text>
        </v-expansion-panel>
        <v-expansion-panel elevation="0">
          <v-expansion-panel-title><div class="sr-expansion-heading"><v-icon icon="mdi-information-outline" size="18" color="info" /><strong>托管与通知说明</strong></div></v-expansion-panel-title>
          <v-expansion-panel-text><ul class="sr-guide">
            <li>使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。</li>
            <li>开业前检查食材缺口和预算；补货后的魔力余额不低于最低保留值。</li>
            <li>通知汇总经营与下馆子结果，并提示预算不足、结果不明等异常；同类每天最多一次，不逐单推送。</li>
            <li>手动经营、雇佣与下馆子需先关闭两个后台任务开关。建议不要同时使用网页和插件经营同一餐厅。</li>
          </ul></v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
      <footer class="sr-config-footer"><span class="sr-hint">调整完成后保存生效</span><v-btn prepend-icon="mdi-content-save-outline" @click="save" :loading="saving" :disabled="saving || !loaded">保存配置</v-btn></footer>
    </v-defaults-provider>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import '../style.css'
const props=defineProps({api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object})
const emit=defineEmits(['switch','close','config-updated'])
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000,auto_visit:false,visit_targets:[],notify:false})
const fieldDefaults = { VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto', color: 'success' }, VBtn: { size: 'small', variant: 'tonal', color: 'success' } }
const switchGroups = [
  { title: '基础设置', icon: 'mdi-toggle-switch-outline', color: '#22c55e', items: [
    { key: 'enabled', label: '启用插件', desc: '开启餐厅管理与后台服务', icon: 'mdi-power-plug', color: '#22c55e', accent: '34,197,94' },
    { key: 'notify', label: '发送运行通知', desc: '通过 MP 通知渠道推送结果与异常', icon: 'mdi-bell-outline', color: '#3b82f6', accent: '59,130,246' },
    { key: 'use_proxy', label: '使用系统代理', desc: '使用 MP 已配置的代理连接站点', icon: 'mdi-lan-connect', color: '#8b5cf6', accent: '139,92,246' }
  ] },
  { title: '自动化策略', icon: 'mdi-robot-outline', color: '#f59e0b', items: [
    { key: 'auto_enabled', label: '后台自动经营', desc: '每日开业、并行烹饪与及时上菜', icon: 'mdi-chef-hat', color: '#f59e0b', accent: '245,158,11' },
    { key: 'auto_purchase', label: '自动补足食材', desc: '按实际订单补货，遵守预算上限', icon: 'mdi-basket-outline', color: '#22c55e', accent: '34,197,94' },
    { key: 'auto_visit', label: '自动下馆子', desc: '经营结束后到访，每日最多 3 人', icon: 'mdi-silverware-fork-knife', color: '#ec4899', accent: '236,72,153' }
  ] }
]
const targets=ref(['','',''])
const cookie=ref(''),clearCookie=ref(false),message=ref(''),messageType=ref('info'),saving=ref(false),loaded=ref(false)
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');loaded.value=true}catch(e){message.value=e.message || '读取配置失败';messageType.value='error'}})
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,auto_visit:config.auto_visit,visit_targets:targets.value,notify:config.notify,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;messageType.value=r.success?'success':'error';if(r.success){Object.assign(config,r.config);targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');cookie.value='';clearCookie.value=false;emit('config-updated',r.config)}}catch(e){message.value=e.message || '保存失败';messageType.value='error'}finally{saving.value=false}}
</script>

<template>
  <section class="sr-app sr-config">
    <header class="sr-header"><div><span class="sr-eyebrow">SIQI · RESTAURANT</span><h2>餐厅设置</h2></div><button @click="emit('switch','page')">返回餐厅</button></header>
    <p class="sr-muted">优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent。后台自动经营由 MP 定时任务执行，关闭插件页面后仍会继续。</p>
    <p v-if="message" role="status" class="sr-notice">{{ message }}</p>
    <div class="sr-card">
      <label><input type="checkbox" v-model="config.enabled">启用插件</label>
      <label><input type="checkbox" v-model="config.use_proxy">使用 MoviePilot 系统代理</label>
      <hr>
      <label><input type="checkbox" v-model="config.auto_enabled">后台自动经营（每日开业、烹饪、上菜）</label>
      <label>每日开业时间（北京时间，错过后补开）<input type="time" v-model="config.start_time"></label>
      <label><input type="checkbox" v-model="config.auto_purchase">按实际订单自动补足缺少的食材</label>
      <label>每日采购预算（魔力）<input type="number" min="0" max="1000000" step="1" v-model.number="config.daily_budget"></label>
      <label>补货后至少保留魔力<input type="number" min="0" max="1000000000" step="1" v-model.number="config.magic_reserve"></label>
      <p class="sr-muted">托管使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。开业前检查预算能否覆盖保守估计的食材缺口。不会自动扩招员工、丢弃成品或下馆子；这些仍可暂停托管后手动操作。</p>
      <p class="sr-muted">保存并启用后，到达开业时间会立即开始。采购预算按北京时间每日重置，保存设置和重启不会清零。已发送的请求会完成；关闭托管后不会继续下一步。</p>
      <p>站点配置：{{ config.site_configured?'已找到思齐':'未找到，可先在 MP 添加思齐站点' }} · Cookie：{{ config.cookie_configured?'已配置':'未配置' }}</p>
      <label>手动 Cookie（选填，留空保留现有配置）<input v-model="cookie" type="password" autocomplete="new-password" placeholder="仅在需要覆盖站点 Cookie 时填写"></label>
      <label><input v-model="clearCookie" type="checkbox">清除插件内手动 Cookie，改用站点管理</label>
      <p class="sr-muted">Cookie 只由 MP 后端发往 https://si-qi.xyz；接口不回显凭据。建议不要同时使用网页和插件经营同一餐厅，两端厨房进度相互独立。</p>
      <div class="sr-actions"><button class="sr-primary" @click="save" :disabled="saving || !loaded">保存配置</button><button @click="emit('close')">关闭</button></div>
    </div>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import '../style.css'
const props=defineProps({api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object})
const emit=defineEmits(['switch','close','config-updated'])
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000})
const cookie=ref(''),clearCookie=ref(false),message=ref(''),saving=ref(false),loaded=ref(false)
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));loaded.value=true}catch(e){message.value=e.message || '读取配置失败'}})
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;if(r.success){Object.assign(config,r.config);cookie.value='';clearCookie.value=false;emit('config-updated',r.config)}}catch(e){message.value=e.message || '保存失败'}finally{saving.value=false}}
</script>

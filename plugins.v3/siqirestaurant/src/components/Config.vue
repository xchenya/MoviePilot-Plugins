<template>
  <section class="sr-app sr-config">
    <header class="sr-header"><div><span class="sr-eyebrow">SIQI · RESTAURANT</span><h2>餐厅设置</h2></div><button @click="emit('switch','page')">返回餐厅</button></header>
    <p class="sr-muted">优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent。当前版本为手动经营面板，没有后台定时任务。</p>
    <p v-if="message" role="status" class="sr-notice">{{ message }}</p>
    <div class="sr-card">
      <label><input type="checkbox" v-model="config.enabled">启用插件</label>
      <label><input type="checkbox" v-model="config.use_proxy">使用 MoviePilot 系统代理</label>
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
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false})
const cookie=ref(''),clearCookie=ref(false),message=ref(''),saving=ref(false),loaded=ref(false)
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));loaded.value=true}catch(e){message.value=e.message || '读取配置失败'}})
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;if(r.success){Object.assign(config,r.config);cookie.value='';clearCookie.value=false;emit('config-updated',r.config)}}catch(e){message.value=e.message || '保存失败'}finally{saving.value=false}}
</script>

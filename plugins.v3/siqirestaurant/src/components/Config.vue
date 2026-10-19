<template>
  <section class="sr-app sr-config">
    <header class="sr-header sr-config-header">
      <div>
        <span class="sr-eyebrow">SIQI · RESTAURANT</span>
        <h2>餐厅设置</h2>
        <p>安排每日经营，让餐厅按你的节奏运转。</p>
      </div>
      <button @click="emit('switch','page')">返回餐厅</button>
    </header>

    <p v-if="message" role="status" class="sr-notice">{{ message }}</p>

    <label class="sr-config-master sr-setting">
      <span class="sr-setting-copy"><strong>启用插件</strong><small>开启餐厅管理与后台服务</small></span>
      <span class="sr-switch"><input type="checkbox" v-model="config.enabled"><span aria-hidden="true"></span></span>
    </label>

    <div class="sr-config-grid">
      <section class="sr-card sr-config-panel">
        <div class="sr-config-panel-head"><h3>自动经营</h3><span class="sr-badge">北京时间</span></div>
        <label class="sr-setting">
          <span class="sr-setting-copy"><strong>后台自动经营</strong><small>每日开业、烹饪与上菜</small></span>
          <span class="sr-switch"><input type="checkbox" v-model="config.auto_enabled"><span aria-hidden="true"></span></span>
        </label>
        <label class="sr-field">
          <span>每日开业时间</span>
          <input type="time" v-model="config.start_time">
          <small>错过时间会补开，关闭插件页面后仍会继续经营。</small>
        </label>
      </section>

      <section class="sr-card sr-config-panel">
        <div class="sr-config-panel-head"><h3>食材与预算</h3><span class="sr-badge">魔力</span></div>
        <label class="sr-setting">
          <span class="sr-setting-copy"><strong>自动补足食材</strong><small>只采购实际订单缺少的食材</small></span>
          <span class="sr-switch"><input type="checkbox" v-model="config.auto_purchase"><span aria-hidden="true"></span></span>
        </label>
        <div class="sr-budget-fields">
          <label class="sr-field"><span>每日采购预算</span><input type="number" min="0" max="1000000" step="1" v-model.number="config.daily_budget"></label>
          <label class="sr-field"><span>最低保留魔力</span><input type="number" min="0" max="1000000000" step="1" v-model.number="config.magic_reserve"></label>
        </div>
        <p class="sr-config-help">预算每日重置，保存设置与重启不会清零。</p>
      </section>

      <section class="sr-card sr-config-panel">
        <div class="sr-config-panel-head"><h3>自动下馆子</h3><span class="sr-badge">每日最多 3 人</span></div>
        <label class="sr-setting">
          <span class="sr-setting-copy"><strong>自动下馆子</strong><small>经营结束后，按名单到访其他餐馆</small></span>
          <span class="sr-switch"><input type="checkbox" v-model="config.auto_visit"><span aria-hidden="true"></span></span>
        </label>
        <div class="sr-visit-fields">
          <label v-for="(_, i) in targets" :key="i" class="sr-field"><span>用户名 {{ i+1 }}</span><input v-model.trim="targets[i]" maxlength="64" :aria-label="`下馆子用户名 ${i+1}`" placeholder="选填"></label>
        </div>
        <p class="sr-config-help">全部留空：每天随机选择 3 位不同用户。填写后只到访名单中的用户，空位不补人。不可到访的用户会跳过并记录原因。</p>
        <p class="sr-config-help">沿用每日开业时间；也可单独开启下馆子。已用次数会扣除，重启不会重复到访。开启即按原站“一键下馆子”规则确认到访，为对方增加顾客。</p>
      </section>

      <section class="sr-card sr-config-panel">
        <div class="sr-config-panel-head"><h3>消息通知</h3><span class="sr-badge">MoviePilot</span></div>
        <label class="sr-setting">
          <span class="sr-setting-copy"><strong>发送运行通知</strong><small>通过 MP 已配置的通知渠道发送</small></span>
          <span class="sr-switch"><input type="checkbox" v-model="config.notify"><span aria-hidden="true"></span></span>
        </label>
        <p class="sr-config-help">汇总今日经营与下馆子结果，提示预算不足、写入结果不明等异常。同类通知每天最多一次，逐次上菜和补货不会推送。</p>
      </section>
    </div>

    <details class="sr-config-details">
      <summary>
        <span class="sr-summary-copy"><strong>连接与凭据</strong><small>站点管理、代理与手动 Cookie</small></span>
        <span class="sr-connection-status">
          <span class="sr-badge" :class="{'sr-status-ready':loaded && config.site_configured}">{{ !loaded?'读取中':config.site_configured?'站点已关联':'站点未关联' }}</span>
          <span class="sr-badge" :class="{'sr-status-ready':loaded && config.cookie_configured,'sr-status-warning':loaded && !config.cookie_configured}">{{ !loaded?'读取中':config.cookie_configured?'Cookie 已配置':'Cookie 未配置' }}</span>
        </span>
      </summary>
      <div class="sr-details-body">
        <p class="sr-config-help">优先使用 MP 站点管理中的思齐 Cookie 和 User-Agent；未关联时，可先在 MP 添加思齐站点。</p>
        <label class="sr-setting">
          <span class="sr-setting-copy"><strong>使用 MoviePilot 系统代理</strong><small>通过 MP 中已配置的代理连接站点</small></span>
          <span class="sr-switch"><input type="checkbox" v-model="config.use_proxy"><span aria-hidden="true"></span></span>
        </label>
        <label class="sr-field"><span>手动 Cookie <small>选填</small></span><input v-model="cookie" type="password" autocomplete="new-password" placeholder="仅在需要覆盖站点 Cookie 时填写"><small>留空保留现有配置，已保存的凭据不会回显。</small></label>
        <label class="sr-clear-cookie"><input v-model="clearCookie" type="checkbox">清除插件内手动 Cookie，改用站点管理</label>
        <p class="sr-config-help">Cookie 只由 MP 后端发往 https://si-qi.xyz。</p>
      </div>
    </details>

    <details class="sr-config-details sr-config-guide">
      <summary><span class="sr-summary-copy"><strong>托管说明</strong><small>调度方式与操作注意事项</small></span></summary>
      <div class="sr-details-body">
        <ul>
          <li>使用所有已解锁灶台，遵守烹饪和清理计时，优先处理耐心将耗尽的订单。</li>
          <li>开业前检查预算能否覆盖保守估计的食材缺口；补货后余额不低于最低保留魔力。</li>
          <li>保存并启用后，到达开业时间会立即开始。关闭托管后，已发送的请求会完成，但不会继续下一步。</li>
          <li>扩招员工、丢弃成品与手动下馆子需先关闭两个后台任务开关。</li>
          <li>建议不要同时使用网页和插件经营同一餐厅，两端厨房进度相互独立。</li>
        </ul>
      </div>
    </details>

    <footer class="sr-config-footer">
      <span class="sr-config-help">{{ loaded?'调整完成后保存生效':'正在读取配置…' }}</span>
      <div class="sr-actions"><button @click="emit('close')">关闭</button><button class="sr-primary" @click="save" :disabled="saving || !loaded">{{ saving?'保存中…':'保存配置' }}</button></div>
    </footer>
  </section>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue'
import '../style.css'
const props=defineProps({api:Object,pluginId:{type:String,default:'SiqiRestaurant'},initialConfig:Object})
const emit=defineEmits(['switch','close','config-updated'])
const config=reactive({enabled:false,use_proxy:false,cookie_configured:false,site_configured:false,auto_enabled:false,start_time:"08:00",auto_purchase:true,daily_budget:5000,magic_reserve:10000,auto_visit:false,visit_targets:[],notify:false})
const targets=ref(['','',''])
const cookie=ref(''),clearCookie=ref(false),message=ref(''),saving=ref(false),loaded=ref(false)
onMounted(async()=>{try{Object.assign(config,await props.api.get(`plugin/${props.pluginId}/config`));targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');loaded.value=true}catch(e){message.value=e.message || '读取配置失败'}})
async function save(){saving.value=true;try{const r=await props.api.post(`plugin/${props.pluginId}/config`,{enabled:config.enabled,use_proxy:config.use_proxy,auto_enabled:config.auto_enabled,start_time:config.start_time,auto_purchase:config.auto_purchase,daily_budget:config.daily_budget,magic_reserve:config.magic_reserve,auto_visit:config.auto_visit,visit_targets:targets.value,notify:config.notify,cookie:cookie.value,clear_cookie:clearCookie.value});message.value=r.message;if(r.success){Object.assign(config,r.config);targets.value=[0,1,2].map(i=>config.visit_targets?.[i] || '');cookie.value='';clearCookie.value=false;emit('config-updated',r.config)}}catch(e){message.value=e.message || '保存失败'}finally{saving.value=false}}
</script>

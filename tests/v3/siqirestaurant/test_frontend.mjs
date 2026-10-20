// Mount the real compiled Vue components against a synthetic MP API in jsdom.
import assert from 'node:assert/strict'
import { mock } from 'node:test'
import { createRequire, registerHooks } from 'node:module'
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../../../', import.meta.url))
const plugin = path.join(root, 'plugins.v3/siqirestaurant')
const require = createRequire(path.join(plugin, 'package.json'))
const { JSDOM } = require('jsdom')
const { parse, compileScript } = require('@vue/compiler-sfc')
const dom = new JSDOM('<!doctype html><div id="app"></div>', {url:'https://mp.test/',pretendToBeVisual:true})
for (const key of ['window','document','Element','SVGElement','HTMLElement','Node','Event','ShadowRoot','Document']) {
  globalThis[key] = dom.window[key]
}
// Mount MoviePilot's real Vuetify controls; Node only skips stylesheet loading.
registerHooks({ load(url, context, nextLoad) {
  if (url.endsWith('.css')) return { format: 'module', source: 'export default {}', shortCircuit: true }
  return nextLoad(url, context)
} })
window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })
globalThis.visualViewport = undefined
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window)
globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window)
globalThis.getComputedStyle = window.getComputedStyle.bind(window)
const { createVuetify } = await import(pathToFileURL(require.resolve('vuetify')).href)
const components = await import(pathToFileURL(require.resolve('vuetify/components')).href)
const directives = await import(pathToFileURL(require.resolve('vuetify/directives')).href)
// MP registers VCronField globally; stub only its host boundary in this isolated mount.
const installUi = app => app.use(createVuetify({ components, directives })).component('VCronField', {
  props:['modelValue'], emits:['update:modelValue'],
  render(){return h('input', {'aria-label':'执行时间（Cron）', value:this.modelValue, onInput:e=>this.$emit('update:modelValue', e.target.value)})}
})
const { createApp, nextTick, h } = await import(pathToFileURL(require.resolve('vue')).href)
const output = mkdtempSync(path.join(plugin,'.ui-test-'))
let app
const realTimeout = globalThis.setTimeout
const settle = async()=>{for(let i=0;i<5;i++){await new Promise(r=>realTimeout(r,0));await nextTick()}}
const click = async text=>{
  const b=[...document.querySelectorAll('button')].find(b=>(b.textContent.trim()===text || b.getAttribute('aria-label')===text))
  assert(b,`missing button: ${text}`);assert(!b.disabled,`disabled button: ${text}`)
  b.click();await settle()
}
async function component(name){
  const file=path.join(plugin,`src/components/${name}.vue`)
  const source=readFileSync(file,'utf8').replace("import '../style.css'",'')
  const {descriptor}=parse(source,{filename:file})
  const compiled=compileScript(descriptor,{id:`test-${name}`,inlineTemplate:true})
  const target=path.join(output,`${name}.mjs`);writeFileSync(target,compiled.content)
  return (await import(pathToFileURL(target).href)).default
}
const restaurant={user:{magic:1000},state:{session_status:'ready',customers_total:3,unlocked:{dishes:['egg'],stations:1},customer_plan:[]},
  config:{ingredients:[{key:'egg',name:'鸡蛋',price:12}],tools:[{key:'wok',name:'炒锅'}],
    dishes:[{key:'egg',name:'炒鸡蛋',tool:'wok',cook_time:4,price:80,ingredients:[{key:'egg',quantity:2}]}]},
  inventory:{ingredients:{egg:20},tools:{wok:1}},staff:{unlocked:true,available:{chef:1,server:1}},logs:[]}
const response=()=>({success:true,message:'完成',restaurant:structuredClone(restaurant),kitchen:[{index:1,status:'idle',dish_key:'',ingredients:{}}],server_now:Date.now()/1000,cleaning:{},events:[]})
const calls=[]
const api={get:async()=>response(),post:async(url,payload)=>{calls.push({url,payload});return response()}}
try {
  app=createApp(await component('Page'),{api,pluginId:'SiqiRestaurant_test'});installUi(app).mount('#app');await settle()
  assert(document.body.textContent.includes('1,000'))
  assert.equal(document.querySelector('input[type="checkbox"]').checked,false)
  await click('食材与菜品')
  const quantity=document.querySelector('input[type="number"]');quantity.value='3';quantity.dispatchEvent(new Event('input',{bubbles:true}));await settle()
  await click('购买');assert(document.querySelector('[role="dialog"]').textContent.includes('36 魔力'))
  assert.equal(calls.length,0)
  await click('取消');assert.equal(calls.length,0)
  await click('购买');await click('确认')
  assert.equal(calls.length,1)
  assert.equal(calls[0].url,'plugin/SiqiRestaurant_test/action')
  assert.equal(calls[0].payload.action,'purchase_ingredient')
  assert.deepEqual(calls[0].payload.args,{ingredient_key:'egg',quantity:3,max_cost:36})
  assert(calls[0].payload.request_id.length>=8)
  await click('下馆子')
  const target=document.querySelector('input[aria-label="餐馆主人用户名"]');target.value='fixture-user';target.dispatchEvent(new Event('input',{bubbles:true}));await settle()
  api.post=async(url,payload)=>{calls.push({url,payload});return {...response(),success:false,requires_confirmation:true,message:'站点要求额外确认'}}
  await click('前往用餐');await click('确认')
  assert.equal(calls.filter(c=>c.payload.action==='visit_restaurant').length,1)
  assert(document.querySelector('[role="dialog"]').textContent.includes('额外确认'))
  assert.equal(calls.at(-1).payload.args.confirm,undefined)
  await click('取消')
  app.unmount();app=null;document.querySelector('#app').innerHTML=''
  const configCalls=[]
  const configApi={get:async()=>({enabled:true,use_proxy:false,cookie_configured:true,site_configured:true}),
    post:async(url,payload)=>{configCalls.push(payload);return {success:true,message:'已保存',config:{...payload,run_once:false,cookie:undefined,cookie_configured:true,site_configured:true}}}}
  app=createApp(await component('Config'),{api:configApi});installUi(app).mount('#app');await settle()
  await click('连接与凭据站点已关联Cookie 已配置')
  const password=document.querySelector('input[type=password]');assert.equal(password.value,'')
  await click('保存配置');assert.equal(configCalls.length,1);assert.equal(configCalls[0].cookie,'')
  assert.equal(document.querySelectorAll('button[aria-label="保存配置"]').length,1)
  assert(!document.querySelector('.sr-config-footer button'))
  assert.equal(configCalls[0].cron,'0 8 * * *')
  const cronInput=document.querySelector('input[aria-label="执行时间（Cron）"]')
  cronInput.value='0 8,12,18 * * *';cronInput.dispatchEvent(new Event('input',{bubbles:true}))
  document.querySelector('input[aria-label="保存后运行一次"]').click();await settle()
  await click('保存配置')
  assert.equal(configCalls.at(-1).cron,'0 8,12,18 * * *')
  assert.equal(configCalls.at(-1).run_once,true)
  assert.equal(document.querySelector('input[aria-label="保存后运行一次"]').checked,false)
  assert.equal(configCalls[0].auto_enabled,false)
  assert.equal(configCalls[0].daily_budget,5000)
  assert.equal(configCalls[0].magic_reserve,10000)
  const autoBox=document.querySelector('input[aria-label="后台自动经营"]')
  autoBox.click();await settle()
  await click('保存配置');assert.equal(configCalls.at(-1).auto_enabled,true)
  assert.equal(configCalls.at(-1).auto_visit,false)
  assert.equal(configCalls.at(-1).notify,false)
  assert.equal(document.querySelectorAll('.sr-visit-fields input').length,3)
  for (const [i,input] of [...document.querySelectorAll('.sr-visit-fields input')].entries()) {
    input.value=['Alice','Bob','Carol'][i];input.dispatchEvent(new Event('input',{bubbles:true}))
    input.dispatchEvent(new Event('change',{bubbles:true}))
  }
  for(const label of ['自动下馆子','发送运行通知']){
    const box=document.querySelector(`input[aria-label="${label}"]`)
    box.click()
  }
  await settle();await click('保存配置')
  assert.deepEqual(configCalls.at(-1).visit_targets,['Alice','Bob','Carol'])
  assert.equal(configCalls.at(-1).auto_visit,true)
  assert.equal(configCalls.at(-1).notify,true)
  assert.equal(document.querySelector('.sr-visit-fields input').value,'Alice')
  app.unmount();app=null;document.querySelector('#app').innerHTML=''
  const autoApi={get:async()=>({...response(),automation:{enabled:true,spent:48,daily_budget:5000,message:'后台正在烹饪'}}),post:async()=>{throw new Error('unexpected page write')}}
  app=createApp(await component('Page'),{api:autoApi});installUi(app).mount('#app');await settle()
  assert(document.body.textContent.includes('后台正在烹饪'))
  assert([...document.querySelectorAll('button')].find(b=>b.textContent==='开始今日经营').disabled)
  assert(document.querySelector('input[type="checkbox"]').disabled)
  await click('下馆子')
  assert(![...document.querySelectorAll('button')].find(b=>b.textContent==='随机推荐').disabled)
  assert(document.body.textContent.includes('设置名单与通知'))
  app.unmount();app=null;document.querySelector('#app').innerHTML=''

  // Advance real component timers without waiting a minute or touching a live site.
  mock.timers.enable({apis:['setTimeout','setInterval','Date'],now:1792380000000})
  let current=response(), hidden=false, pollCalls=[]
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>hidden})
  const pollingApi={get:async url=>{pollCalls.push(url);return structuredClone(current)},
    post:async url=>{pollCalls.push(url);return structuredClone(current)}}
  const advance=async ms=>{mock.timers.tick(ms);await settle()}
  app=createApp(await component('Page'),{api:pollingApi});installUi(app).mount('#app');await settle()
  assert.equal(pollCalls.length,1)
  assert(document.body.textContent.includes('每 60 秒更新状态'))
  await advance(59000);assert.equal(pollCalls.length,1,'unopened restaurant must stay quiet')
  await advance(1000);assert.equal(pollCalls.at(-1),'plugin/SiqiRestaurant/tick');assert.equal(pollCalls.length,2)
  current.restaurant.state.session_status='closed'
  await click('刷新');pollCalls=[]
  await advance(59000);assert.equal(pollCalls.length,0,'closed restaurant must stay quiet')
  await advance(1000);assert.equal(pollCalls.length,1)
  // A manual action/read switches the interval immediately instead of waiting out the old idle timer.
  current.restaurant.state.session_status='open'
  await click('刷新');pollCalls=[]
  assert(document.body.textContent.includes('每 2 秒更新状态'))
  await advance(2000);assert.equal(pollCalls.length,1)
  current.restaurant.state.session_status='ready'
  current.kitchen[0].status='cooking';current.kitchen[0].ready_at=Date.now()/1000+10
  await click('刷新');pollCalls=[]
  await advance(2000);assert.equal(pollCalls.length,1,'pre-opening cooking needs timely ticks')
  current.kitchen[0].status='ready'
  await advance(2000);pollCalls=[]
  await advance(59000);assert.equal(pollCalls.length,0,'finished cooking returns to idle polling')
  await advance(1000);assert.equal(pollCalls.length,1)
  current.cleaning={'1':Date.now()/1000+10}
  await click('刷新');pollCalls=[]
  await advance(2000);assert.equal(pollCalls.length,1,'cleaning countdown needs timely ticks')
  current.cleaning={};current.automation={enabled:false,active:true,visit_enabled:true}
  await click('刷新');pollCalls=[]
  await advance(60000);assert.deepEqual(pollCalls,['plugin/SiqiRestaurant/state'],'visit-only automation is read-only')
  hidden=true;document.dispatchEvent(new Event('visibilitychange'));pollCalls=[]
  await advance(120000);assert.equal(pollCalls.length,0,'hidden page must stop polling')
  hidden=false;document.dispatchEvent(new Event('visibilitychange'));await settle()
  assert.deepEqual(pollCalls,['plugin/SiqiRestaurant/state'],'returning to the page refreshes immediately')
  app.unmount();app=null;pollCalls=[]
  await advance(120000);assert.equal(pollCalls.length,0,'unmounted page must release timers')
  mock.timers.reset()
  console.log('PASS: idle/closed 60s polling; active/cooking/cleaning 2s polling; transitions; hidden/resume/unmount; visit-only read-only polling')
  console.log('PASS: compiled Page/Config mounting; namespaced API; purchase budget confirmation/cancel; site visit confirmation; masked cookie settings')
} finally {app?.unmount();mock.timers.reset();dom.window.close();rmSync(output,{recursive:true,force:true})}

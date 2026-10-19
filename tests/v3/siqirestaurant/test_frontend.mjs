// Mount the real compiled Vue components against a synthetic MP API in jsdom.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../../../', import.meta.url))
const plugin = path.join(root, 'plugins.v3/siqirestaurant')
const require = createRequire(path.join(plugin, 'package.json'))
const { JSDOM } = require('jsdom')
const { parse, compileScript } = require('@vue/compiler-sfc')
const dom = new JSDOM('<!doctype html><div id="app"></div>', {url:'https://mp.test/',pretendToBeVisual:true})
for (const key of ['window','document','Element','SVGElement','HTMLElement','Node','Event']) {
  globalThis[key] = dom.window[key]
}
const { createApp, nextTick } = await import(pathToFileURL(require.resolve('vue')).href)
const output = mkdtempSync(path.join(plugin,'.ui-test-'))
let app
const settle = async()=>{for(let i=0;i<5;i++){await new Promise(r=>setTimeout(r,0));await nextTick()}}
const click = async text=>{
  const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text)
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
  app=createApp(await component('Page'),{api,pluginId:'SiqiRestaurant_test'});app.mount('#app');await settle()
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
    post:async(url,payload)=>{configCalls.push(payload);return {success:true,message:'已保存',config:{enabled:true,use_proxy:false,cookie_configured:true,site_configured:true}}}}
  app=createApp(await component('Config'),{api:configApi});app.mount('#app');await settle()
  const password=document.querySelector('input[type=password]');assert.equal(password.value,'')
  await click('保存配置');assert.equal(configCalls.length,1);assert.equal(configCalls[0].cookie,'')
  assert.equal(configCalls[0].auto_enabled,false)
  assert.equal(configCalls[0].daily_budget,5000)
  assert.equal(configCalls[0].magic_reserve,10000)
  const autoBox=[...document.querySelectorAll('label')].find(l=>l.textContent.includes('后台自动经营')).querySelector('input')
  autoBox.checked=true;autoBox.dispatchEvent(new Event('change',{bubbles:true}));await settle()
  await click('保存配置');assert.equal(configCalls.at(-1).auto_enabled,true)
  app.unmount();app=null;document.querySelector('#app').innerHTML=''
  const autoApi={get:async()=>({...response(),automation:{enabled:true,spent:48,daily_budget:5000,message:'后台正在烹饪'}}),post:async()=>{throw new Error('unexpected page write')}}
  app=createApp(await component('Page'),{api:autoApi});app.mount('#app');await settle()
  assert(document.body.textContent.includes('后台正在烹饪'))
  assert([...document.querySelectorAll('button')].find(b=>b.textContent==='开始今日经营').disabled)
  assert(document.querySelector('input[type="checkbox"]').disabled)
  console.log('PASS: compiled Page/Config mounting; namespaced API; purchase budget confirmation/cancel; site visit confirmation; masked cookie settings')
} finally {app?.unmount();dom.window.close();rmSync(output,{recursive:true,force:true})}

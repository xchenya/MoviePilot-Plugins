// Exercise the actual Vue/Vuetify components against MoviePilot's injected API boundary.
import assert from 'node:assert/strict'
import { createRequire, registerHooks } from 'node:module'
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const plugin = fileURLToPath(new URL('../../../plugins.v3/hdskycommunitysign/', import.meta.url))
const require = createRequire(path.join(plugin, 'package.json'))
const { JSDOM } = require('jsdom')
const { parse, compileScript } = require('@vue/compiler-sfc')
const dom = new JSDOM('<!doctype html><div id="app"></div>', { url: 'https://mp.test/', pretendToBeVisual: true })
for (const key of ['window', 'document', 'Element', 'SVGElement', 'HTMLElement', 'Node', 'Event', 'ShadowRoot', 'Document']) globalThis[key] = dom.window[key]
registerHooks({ load(url, context, nextLoad) {
  if (url.endsWith('.css')) return { format: 'module', source: 'export default {}', shortCircuit: true }
  return nextLoad(url, context)
} })
window.matchMedia = query => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
globalThis.requestAnimationFrame = window.requestAnimationFrame.bind(window)
globalThis.cancelAnimationFrame = window.cancelAnimationFrame.bind(window)
globalThis.getComputedStyle = window.getComputedStyle.bind(window)
globalThis.CSS = dom.window.CSS || { supports: () => false }
globalThis.visualViewport = undefined
const { createVuetify } = await import(pathToFileURL(require.resolve('vuetify')).href)
const components = await import(pathToFileURL(require.resolve('vuetify/components')).href)
const directives = await import(pathToFileURL(require.resolve('vuetify/directives')).href)
const { createApp, nextTick } = await import(pathToFileURL(require.resolve('vue')).href)
const output = mkdtempSync(path.join(plugin, 'src/components/.ui-test-'))
let app, checks = 0
const settle = async () => { for (let i = 0; i < 6; i++) { await new Promise(r => setTimeout(r, 0)); await nextTick() } }
const button = text => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text)
async function click(text) {
  const element = button(text)
  assert(element, `missing button: ${text}`)
  assert(!element.disabled, `disabled button: ${text}`)
  element.click(); await settle()
}
async function input(label, value) {
  const element = document.querySelector(`input[aria-label="${label}"]`)
  assert(element, `missing field: ${label}`)
  element.value = value
  element.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}
async function mount(name, api) {
  app?.unmount()
  document.querySelector('#app').innerHTML = ''
  const file = path.join(plugin, `src/components/${name}.vue`)
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file })
  const compiled = compileScript(descriptor, { id: `test-${name}`, inlineTemplate: true })
  // Preserve the component's relative imports when compiling the template for Node.
  const target = path.join(output, `${name}.mjs`)
  writeFileSync(target, compiled.content.replaceAll("'../format.js'", "'../../format.js'").replaceAll("'../style.css'", "'../../style.css'"))
  const component = (await import(pathToFileURL(target).href)).default
  app = createApp(component, { api, pluginId: 'HdskyCommunitySign_clone' })
  app.use(createVuetify({ components, directives })).mount('#app')
  await settle()
}
const state = () => ({
  config: { enabled: false, uid: '123', use_proxy: false, user_agent: 'HDSkyWindows/0.6.0-rc.1', auto_sign: false, notify: true, cron: '0 8 * * *' },
  auth: { uid: '', pending_uid: '', cookie_configured: false, verified: false, send_after: 0, verify_after: 0, retry_after: 0 },
  status: { success: false, message: '' },
  statistics: { uid: '123', completed_days: 2, reward_total: 40, unknown_reward_days: 1,
    today: { day: '2026-10-27', status: 'success', amount: 20, balance: 120 },
    days: Array.from({ length: 30 }, (_, i) => ({ day: `fixture-${i}`, status: i ? 'unrecorded' : 'success', amount: i ? null : 20, balance: i ? null : 120 })) },
  history: [],
})
try {
  let current = state(), calls = []
  let api = {
    get: async url => { calls.push({ url, method: 'get' }); return structuredClone(current) },
    post: async (url, payload) => {
      calls.push({ url, payload: structuredClone(payload), method: 'post' })
      if (payload.action === 'send') current.auth = { ...current.auth, pending_uid: '123', send_after: Date.now() / 1000 + 60 }
      if (payload.action === 'login') current.auth = { ...current.auth, uid: '123', pending_uid: '', cookie_configured: true, verified: true }
      if (url.endsWith('/config')) current.config = { ...payload }
      return { success: true, message: payload.action === 'login' ? '登录成功' : '已完成', state: structuredClone(current) }
    },
  }
  await mount('Config', api)
  assert(button('登录').disabled)
  await input('签到 Cron', '0 9 * * *')
  await click('发送验证码')
  assert.equal(calls.at(-1).url, 'plugin/HdskyCommunitySign_clone/auth')
  assert.equal(calls.at(-1).payload.action, 'send')
  assert(!calls.some(c => c.url.endsWith('/config')))
  assert(button('60 秒后可重发').disabled)
  checks++
  await input('站内信六位验证码', '012345')
  await click('登录')
  assert.equal(calls.at(-1).payload.code, '012345')
  assert(!('cookie' in calls.at(-1).payload))
  assert.equal(document.querySelector('input[aria-label="站内信六位验证码"]').value, '')
  assert(document.body.textContent.includes('登录成功'))
  assert(document.body.textContent.includes('已登录'))
  assert.equal(document.querySelector('input[aria-label="签到 Cron"]').value, '0 9 * * *', 'login must preserve unsaved settings')
  assert.equal(calls.filter(c => c.method === 'post').length, 2)
  checks++
  await click('保存设置')
  assert.equal(calls.at(-1).url, 'plugin/HdskyCommunitySign_clone/config')
  assert.equal(calls.at(-1).payload.cron, '0 9 * * *')
  assert(!('code' in calls.at(-1).payload))
  checks++

  api.post = async () => ({ success: false, message: 'Cron 无效', state: structuredClone(current) })
  await input('签到 Cron', 'invalid')
  await click('保存设置')
  assert.equal(document.querySelector('input[aria-label="签到 Cron"]').value, 'invalid', 'a validation error must retain the edit for correction')
  checks++

  // A fast double click must issue one write even before Vue updates disabled props.
  current = state(); calls = []
  let finish
  api.post = (url, payload) => { calls.push({ url, payload }); return new Promise(resolve => { finish = resolve }) }
  await mount('Config', api)
  button('发送验证码').click(); button('发送验证码').click()
  await settle()
  assert.equal(calls.filter(c => c.payload?.action === 'send').length, 1)
  finish({ success: true, message: '已发送', state: current }); await settle()
  checks++

  current = state(); current.auth.pending_uid = '123'; calls = []
  api.post = async (url, payload) => { calls.push({ url, payload }); throw new Error('private-cookie 012345') }
  await mount('Config', api)
  await input('站内信六位验证码', '012345')
  await click('登录')
  assert.equal(calls.filter(c => c.payload?.action === 'login').length, 1)
  assert.equal(document.querySelector('input[aria-label="站内信六位验证码"]').value, '')
  assert(!document.body.textContent.includes('private-cookie'))
  assert(!document.body.textContent.includes('012345'))
  assert.equal(calls.filter(c => c.method === 'get').length, 2, 'recover local cooldown without replaying login')
  checks++

  await click('手动 Cookie 与连接设置')
  await input('社区 Cookie', 'hdsky_portal_session=private-cookie')
  await click('验证并保存 Cookie')
  assert.equal(calls.at(-2).payload.action, 'cookie')
  assert(!('code' in calls.at(-2).payload))
  assert.equal(document.querySelector('input[aria-label="社区 Cookie"]').value, '')
  checks++

  await mount('Config', { get: async () => { throw new Error('offline') } })
  assert(button('保存设置').disabled)
  assert(button('发送验证码').disabled)
  assert(button('重新读取'))
  checks++

  current = state(); current.config.enabled = true; current.auth.cookie_configured = true; calls = []
  api = {
    get: async url => { calls.push({ url, method: 'get' }); return structuredClone(current) },
    post: async url => { calls.push({ url, method: 'post' }); return { success: true, message: '今日已签到', state: structuredClone(current) } },
  }
  await mount('Page', api)
  assert(document.body.textContent.includes('另有 1 天奖励数值未知'))
  assert(document.body.textContent.includes('奖励合计40'))
  assert.equal(document.querySelectorAll('tbody tr').length, 7)
  await click('近 30 天')
  assert.equal(document.querySelectorAll('tbody tr').length, 30)
  assert(document.querySelector('tbody').textContent.includes('尚无记录'))
  checks++
  await click('刷新统计')
  assert(!calls.some(c => c.method === 'post'))
  await click('立即签到')
  assert.equal(calls.at(-1).url, 'plugin/HdskyCommunitySign_clone/sign')
  assert.equal(calls.filter(c => c.method === 'post').length, 1)
  checks++

  current.config.enabled = false
  await mount('Page', api)
  assert(button('立即签到').disabled)
  assert(document.body.textContent.includes('启用插件并保存'))
  checks++
  console.log(`PASS: ${checks} frontend interaction scenarios (direct login, cooldown, duplicate clicks, errors, secrets, unsaved settings, account statistics, clone API, sign enablement)`)
} finally {
  app?.unmount()
  dom.window.close()
  rmSync(output, { recursive: true, force: true })
}

import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const plugin = path.join(root, 'plugins.v3/siqicleanbeach')
const require = createRequire(path.join(plugin, 'package.json'))
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc')
const configKeys = ['enabled', 'notify', 'run_once', 'schedule_mode', 'cron', 'interval_minutes', 'auto_brick', 'brick_cron', 'brick_retry_limit', 'cookie']

function config(overrides = {}) {
  return { enabled: true, notify: true, run_once: false, schedule_mode: 'auto', cron: '1 */2 * * *', interval_minutes: 121, auto_brick: true, brick_cron: '0 10,16 * * *', brick_retry_limit: 1, cookie: '', ...overrides }
}

function stats(running = false) {
  return { success: true, data: {
    stats: { daily_bricks: 50, inventory_refreshed: false, last_update: Date.UTC(2026, 9, 19, 2, 15) / 1000, clean_result: '收集5个垃圾', history: [
      { time: 100, clean: { message: '收集3个垃圾' }, brick: { message: '搬砖完成' }, status: 'completed' },
      { time: 200, clean: { message: '沙滩冷却中' }, brick: { message: '正常等待' }, status: 'completed' },
    ] },
    inventory: { '木材': { count: 10 }, '砖块': { count: 2051 } },
    display: { enabled: true, auto_brick: true, running, timezone: 'Asia/Shanghai', daily_bricks: 50, brick_today_result: '10:00 搬砖50块' },
  } }
}

function harness(name, api, initialConfig = {}) {
  const source = fs.readFileSync(path.join(plugin, 'src/components', name + '.vue'), 'utf8')
  const { descriptor } = parse(source)
  const script = descriptor.scriptSetup.content.split('\n').filter(line => !line.startsWith('import ')).join('\n')
  const mounted = []
  const unmounted = []
  const events = []
  const timers = new Map()
  const listeners = new Map()
  let nextTimer = 0
  const document = { hidden: false, addEventListener: (event, callback) => listeners.set(event, callback), removeEventListener: (event, callback) => { if (listeners.get(event) === callback) listeners.delete(event) } }
  const bindings = name === 'Config'
    ? 'config, loading, loaded, saving, message, messageType, loadConfig, saveConfig'
    : 'data, loading, loaded, starting, message, messageType, view, stats, items, history, metrics, stockNote, refresh, runOnce, formatTime, itemIcon'
  const state = new Function('reactive', 'ref', 'computed', 'onMounted', 'onUnmounted', 'defineProps', 'defineEmits', 'setTimeout', 'clearTimeout', 'document', script + '\nreturn {' + bindings + '}')(
    value => value,
    value => ({ value }),
    getter => ({ get value() { return getter() } }),
    callback => mounted.push(callback),
    callback => unmounted.push(callback),
    () => ({ api, pluginId: 'SiQiCleanBeach_custom', initialConfig }),
    () => (...args) => events.push(args),
    (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id },
    id => timers.delete(id), document,
  )
  return { state, events, timers, document, listeners,
    async mount() { for (const callback of mounted) await callback(); await settle() },
    unmount() { for (const callback of unmounted) callback() },
    async tick() { const [id, timer] = timers.entries().next().value; timers.delete(id); await timer.callback(); await settle() },
  }
}

async function settle() { for (let i = 0; i < 8; i++) await Promise.resolve() }

for (const name of ['Config', 'Page']) {
  test(name + ' compiles with the host Vue component contract', () => {
    const filename = path.join(plugin, 'src/components', name + '.vue')
    const { descriptor, errors } = parse(fs.readFileSync(filename, 'utf8'), { filename })
    assert.deepEqual(errors, [])
    const script = compileScript(descriptor, { id: name })
    const template = compileTemplate({ source: descriptor.template.content, filename, id: name, compilerOptions: { bindingMetadata: script.bindings } })
    assert.deepEqual(template.errors, [])
  })
}

test('Config mounts with one cache GET for the active instance and ignores stale initial configuration', async () => {
  const calls = []
  const current = config({ brick_cron: '0 11,17 * * *', brick_retry_limit: 3, _stats: { history: ['private'] } })
  const h = harness('Config', {
    get: async url => { calls.push(['GET', url]); return current },
    post: async () => assert.fail('mount must not write'),
  }, config({ enabled: false, brick_cron: '0 10,16 * * *', cookie: 'stale-cookie' }))
  assert.equal(h.state.loaded.value, false)
  await h.mount()
  assert.deepEqual(calls, [['GET', 'plugin/SiQiCleanBeach_custom/config']])
  assert.equal(h.state.config.brick_cron, '0 11,17 * * *')
  assert.equal(h.state.config.brick_retry_limit, 3)
  assert.equal(h.state.config.cookie, '')
  assert.equal('_stats' in h.state.config, false)
  assert.equal(h.state.loaded.value, true)
})

test('failed or malformed Config reads cannot save fallback defaults', async () => {
  for (const get of [async () => { throw new Error('offline') }, async () => ({ enabled: true, schedule_mode: 'unknown' }), async () => ({ success: false })]) {
    let writes = 0
    const h = harness('Config', { get, post: async () => { writes++ } }, config())
    await h.mount()
    await h.state.saveConfig()
    assert.equal(h.state.loaded.value, false)
    assert.equal(writes, 0)
    assert.match(h.state.message.value, /重新加载/)
    assert.equal(h.state.messageType.value, 'error')
  }
})

test('Config sends only editable fields and adopts the canonical saved config before emitting config-updated', async () => {
  const calls = []
  const canonical = config({ run_once: false, brick_cron: '', interval_minutes: 5 })
  const h = harness('Config', {
    get: async () => config({ _stats: { secret: 'internal' }, brick_success: { daily: 50 }, site_auto_check_minutes: 10 }),
    post: async (url, body) => { calls.push([url, structuredClone(body)]); return { success: true, config: canonical, message: '已保存' } },
  })
  await h.mount()
  h.state.config.run_once = true
  h.state.config.brick_cron = null
  await h.state.saveConfig()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'plugin/SiQiCleanBeach_custom/config')
  assert.deepEqual(Object.keys(calls[0][1]).sort(), [...configKeys].sort())
  assert.equal(calls[0][1].run_once, true)
  assert.equal(calls[0][1].brick_cron, '')
  assert.equal(h.state.config.run_once, false)
  assert.equal(h.state.config.interval_minutes, 5)
  assert.deepEqual(h.events, [['config-updated', canonical]])
  assert.equal(h.state.messageType.value, 'success')
})

test('an unconfirmed Config save blocks a second write until a fresh read', async () => {
  for (const result of [new Error('connection lost after write'), { success: true }, { success: true, config: {} }]) {
    let writes = 0
    const h = harness('Config', {
      get: async () => config(),
      post: async () => { writes++; if (result instanceof Error) throw result; return result },
    })
    await h.mount()
    await h.state.saveConfig()
    assert.equal(h.state.loaded.value, false)
    assert.equal(h.state.saving.value, false)
    assert.match(h.state.message.value, /重新加载/)
    await h.state.saveConfig()
    assert.equal(writes, 1)
    assert.deepEqual(h.events, [])
    await h.state.loadConfig()
    assert.equal(h.state.loaded.value, true)
    await h.state.saveConfig()
    assert.equal(writes, 2)
  }
})

test('a confirmed Config validation failure can be corrected without reloading', async () => {
  let writes = 0
  const h = harness('Config', {
    get: async () => config(),
    post: async () => { writes++; return { success: false, message: 'Cron 不正确' } },
  })
  await h.mount()
  await h.state.saveConfig()
  assert.equal(h.state.loaded.value, true)
  assert.equal(h.state.message.value, 'Cron 不正确')
  assert.deepEqual(h.events, [])
  await h.state.saveConfig()
  assert.equal(writes, 2)
})

test('HTTP 422 Config validation failures remain editable and can be corrected without reloading', async () => {
  for (const error of [{ response: { status: 422 } }, { status: 422 }]) {
    let writes = 0
    const h = harness('Config', {
      get: async () => config(),
      post: async (url, body) => { writes++; if (writes === 1) throw error; return { success: true, config: config(body) } },
    })
    await h.mount()
    h.state.config.brick_cron = 'invalid cron'
    await h.state.saveConfig()
    assert.equal(h.state.loaded.value, true)
    assert.equal(h.state.saving.value, false)
    assert.match(h.state.message.value, /Cron.*间隔.*重试次数/)
    assert.equal(h.state.messageType.value, 'error')
    assert.deepEqual(h.events, [])
    h.state.config.brick_cron = '0 10,16 * * *'
    await h.state.saveConfig()
    assert.equal(writes, 2)
    assert.equal(h.state.loaded.value, true)
    assert.equal(h.state.messageType.value, 'success')
    assert.equal(h.events.length, 1)
  }
})

test('Config cannot submit the same pending save twice', async () => {
  let writes = 0
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  const h = harness('Config', { get: async () => config(), post: async () => { writes++; return pending } })
  await h.mount()
  const saving = h.state.saveConfig()
  await h.state.saveConfig()
  assert.equal(writes, 1)
  assert.equal(h.state.saving.value, true)
  finish({ success: true, config: config() })
  await saving
  assert.equal(h.state.saving.value, false)
})

test('Page mount and refresh only read cached stats, with brick inventory and separate historical results', async () => {
  const calls = []
  const h = harness('Page', {
    get: async url => { calls.push(['GET', url]); return stats() },
    post: async () => assert.fail('viewing cached data must not write'),
  })
  await h.mount()
  await h.state.refresh()
  assert.deepEqual(calls, [['GET', 'plugin/SiQiCleanBeach_custom/stats'], ['GET', 'plugin/SiQiCleanBeach_custom/stats']])
  assert.deepEqual(h.state.items.value, [{ name: '砖块', count: 2051 }, { name: '木材', count: 10 }])
  assert.equal(h.state.metrics.value.find(item => item.label === '砖块库存').value, '2,051')
  assert.equal(h.state.itemIcon('砖块'), 'mdi-wall')
  assert.equal(h.state.history.value[0].clean.message, '沙滩冷却中')
  assert.equal(h.state.history.value[1].brick.message, '搬砖完成')
  assert.equal(h.state.view.value.brick_today_result, '10:00 搬砖50块')
  assert.match(h.state.stockNote.value, /缓存/)
  assert.equal(h.state.formatTime(stats().data.stats.last_update), '2026-10-19 10:15')
  assert.equal(h.timers.size, 0)
})

test('Page shows an unknown daily brick count when the server-day display value has expired', async () => {
  const cached = stats()
  cached.data.display.daily_bricks = null
  const h = harness('Page', {
    get: async () => cached,
    post: async () => assert.fail('expired daily status must not trigger a task'),
  })
  await h.mount()
  assert.equal(h.state.stats.value.daily_bricks, 50)
  assert.equal(h.state.metrics.value.find(item => item.label === '今日搬砖').value, '— / 50')
  assert.equal(h.state.metrics.value.find(item => item.label === '砖块库存').value, '2,051')
})

test('Page does not retry an uncertain manual run and checks the outcome with one GET', async () => {
  const calls = []
  const h = harness('Page', {
    get: async url => { calls.push(['GET', url]); return stats() },
    post: async url => { calls.push(['POST', url]); throw new Error('response lost') },
  })
  await h.mount()
  await h.state.runOnce()
  await settle()
  assert.deepEqual(calls, [['GET', 'plugin/SiQiCleanBeach_custom/stats'], ['POST', 'plugin/SiQiCleanBeach_custom/run'], ['GET', 'plugin/SiQiCleanBeach_custom/stats']])
  assert.match(h.state.message.value, /未能确认/)
  assert.equal(h.state.starting.value, false)
  assert.equal(h.timers.size, 0)
})

test('Page blocks concurrent run requests until the first response is received', async () => {
  let writes = 0
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  const h = harness('Page', {
    get: async () => stats(),
    post: async () => { writes++; return pending },
  })
  await h.state.runOnce()
  assert.equal(writes, 0)
  await h.mount()
  const running = h.state.runOnce()
  await h.state.runOnce()
  assert.equal(writes, 1)
  assert.equal(h.state.starting.value, true)
  finish({ success: true, message: '任务已启动' })
  await running
  assert.equal(h.state.starting.value, false)
})

test('Page polling while running uses GET only and stops while hidden or unmounted', async () => {
  const calls = []
  const h = harness('Page', {
    get: async url => { calls.push(['GET', url]); return stats(true) },
    post: async () => assert.fail('polling must not submit a task'),
  })
  await h.mount()
  assert.equal(h.timers.size, 1)
  assert.equal([...h.timers.values()][0].delay, 3000)
  await h.tick()
  assert.equal(calls.length, 2)
  await h.state.runOnce()
  assert.equal(calls.length, 2)
  h.document.hidden = true
  h.listeners.get('visibilitychange')()
  assert.equal(h.timers.size, 0)
  h.document.hidden = false
  h.listeners.get('visibilitychange')()
  await settle()
  assert.equal(calls.length, 3)
  assert.equal(h.timers.size, 1)
  h.unmount()
  assert.equal(h.timers.size, 0)
  assert.equal(h.listeners.size, 0)
  await h.state.refresh()
  assert.equal(calls.length, 3)
  assert.ok(calls.every(([method, url]) => method === 'GET' && url === 'plugin/SiQiCleanBeach_custom/stats'))
})

test('Page retains a previously loaded cache when refresh returns malformed data', async () => {
  let reads = 0
  const h = harness('Page', {
    get: async () => ++reads === 1 ? stats() : { success: true },
    post: async () => assert.fail('invalid reads must not trigger a task'),
  })
  await h.mount()
  await h.state.refresh()
  assert.equal(h.state.loaded.value, true)
  assert.equal(h.state.items.value[0].name, '砖块')
  assert.equal(h.state.items.value[0].count, 2051)
  assert.equal(h.state.messageType.value, 'error')
})

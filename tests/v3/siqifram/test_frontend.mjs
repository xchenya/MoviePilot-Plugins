import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const plugin = path.join(root, 'plugins.v3/siqifram')
const require = createRequire(path.join(plugin, 'package.json'))
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc')

for (const name of ['Config', 'Page']) {
  const filename = path.join(plugin, 'src/components', name + '.vue')
  const source = fs.readFileSync(filename, 'utf8')
  test(name + ' compiles and sends requests to the active instance', async () => {
    const { descriptor, errors } = parse(source, { filename })
    assert.deepEqual(errors, [])
    const script = compileScript(descriptor, { id: name })
    const template = compileTemplate({
      source: descriptor.template.content, filename, id: name,
      compilerOptions: { bindingMetadata: script.bindings },
    })
    assert.deepEqual(template.errors, [])
    const calls = []
    const props = { pluginId: 'SiqiFram_work', api: {
      get: async (...args) => { calls.push(args); return { success: true, seeds: [1] } },
      post: async (...args) => { calls.push(args); return { success: false, uncertain: true } },
    } }
    const helpers = source.split('\n').filter(line =>
      line.startsWith('const apiGet =') || line.startsWith('const apiPost =')).join('\n')
    const { apiGet, apiPost } = new Function('props', helpers + '\nreturn { apiGet, apiPost }')(props)
    assert.deepEqual(await apiGet('/data'), { success: true, seeds: [1] })
    assert.deepEqual(await apiPost('/plant', { land_id: 1 }), { success: false, uncertain: true })
    assert.deepEqual(calls, [
      ['plugin/SiqiFram_work/data'], ['plugin/SiqiFram_work/plant', { land_id: 1 }],
    ])
  })
}

test('batch sale stops after an uncertain write', async () => {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Page.vue'), 'utf8')
  const method = 'async function confirmSellAll()' + source
    .split('async function confirmSellAll()')[1].split('async function steal()')[0]
  let calls = 0
  let refreshes = 0
  const notices = []
  const loading = { value: false }
  const dialog = { value: true }
  const run = new Function('apiPost', 'sellAllItems', 'loading', 'show',
    'showSellConfirmDialog', 'refresh', method + '; return confirmSellAll')(
      async () => { calls++; return { success: false, uncertain: true, message: '结果不明' } },
      { value: [{ seed_id: 1, quantity: 2 }, { seed_id: 2, quantity: 3 }] },
      loading, (...args) => notices.push(args), dialog, () => refreshes++,
    )
  await run()
  assert.equal(calls, 1)
  assert.equal(refreshes, 1)
  assert.deepEqual(notices, [['结果不明', 'error']])
  assert.equal(loading.value, false)
  assert.equal(dialog.value, false)
})

test('manual steal keeps maturity visible and disables unselected crops', () => {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Page.vue'), 'utf8')
  const helpers = source.split('\n').filter(line => [
    'function isStealPlotReady(', 'function isStealablePlot(', 'function stealPlotClass(',
  ].some(prefix => line.startsWith(prefix))).join('\n')
  const { isStealablePlot, stealPlotClass } = new Function('nowSec',
    helpers + '\nreturn { isStealablePlot, stealPlotClass }')(() => 100)
  const mature = { seed_id: 91, is_ready: 1, steal_allowed: false }
  assert.equal(isStealablePlot(mature), false)
  assert.equal(stealPlotClass(mature).ready, true)
  assert.equal(stealPlotClass(mature).stealable, false)
  assert.equal(isStealablePlot({ ...mature, steal_allowed: true }), true)
  assert.equal(isStealablePlot({ ...mature, steal_allowed: undefined }), false)
  assert.equal(isStealablePlot({ seed_id: 91, harvest_time: 200, steal_allowed: true }), false)
})

function configHarness(api, initialConfig = {}) {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Config.vue'), 'utf8')
  const { descriptor } = parse(source)
  const script = descriptor.scriptSetup.content.split('\n')
    .filter(line => !line.startsWith('import ')).join('\n')
  return new Function('reactive', 'ref', 'onMounted', 'defineProps', 'defineEmits',
    'setTimeout', 'clearTimeout', script + '\nreturn { config, stealConfig, seedOptions, seedError, configLoaded, stealLoaded, loadConfig, loadSeeds, loadStealConfig, saveConfig, saveStealConfig }')(
      value => value, value => ({ value }), () => {},
      () => ({ api, pluginId: 'SiqiFram', initialConfig }), () => () => {},
      () => 0, () => {},
    )
}

test('planting seed list keeps all crops and unlock status, separate steal save cannot change it', async () => {
  const posts = []
  const api = {
    get: async url => {
      if (url.endsWith('/steal-config')) return { auto_steal: true, steal_crops: ['萝卜'] }
      if (url.endsWith('/config')) return { seed_id: '120', ai_available: false, auto_steal: true, steal_crops: ['萝卜'] }
      assert.ok(url.endsWith('/seeds'))
      return { success: true, seeds: [
        { id: 91, name: '萝卜', unlock_harvest: 0 },
        { id: 120, name: '樱桃', unlock_harvest: 40 },
        { id: 200, name: '西瓜', unlock_harvest: 100 },
      ], user_stats: { total_harvest: 50 } }
    },
    post: async (url, data) => { posts.push([url, structuredClone(data)]); return { success: true, config: data } },
  }
  const state = configHarness(api, { seed_id: '120', steal_crops: ['萝卜'] })
  await Promise.all([state.loadConfig(), state.loadSeeds(), state.loadStealConfig()])
  assert.deepEqual(state.seedOptions.value.map(s => [s.value, s.locked]),
    [['91', false], ['120', false], ['200', true]])
  assert.equal(state.config.seed_id, '120')
  assert.equal('steal_crops' in state.config, false)
  assert.equal('auto_steal' in state.config, false)
  state.stealConfig.steal_crops = ['玉米', '樱桃']
  await state.saveStealConfig()
  state.stealConfig.steal_crops = []
  await state.saveStealConfig()
  await state.saveConfig()
  assert.deepEqual(posts.slice(0, 2), [
    ['plugin/SiqiFram/steal-config', { auto_steal: true, steal_crops: ['玉米', '樱桃'] }],
    ['plugin/SiqiFram/steal-config', { auto_steal: true, steal_crops: [] }],
  ])
  assert.equal(posts[2][0], 'plugin/SiqiFram/config')
  assert.equal(posts[2][1].seed_id, '120')
  assert.equal('steal_crops' in posts[2][1], false)
  assert.equal(state.config.seed_id, '120')
})

test('seed read errors stay visible without a fake radish option or default overwrite', async () => {
  const posts = []
  const state = configHarness({
    get: async url => {
      if (url.endsWith('/steal-config')) return { auto_steal: false, steal_crops: ['玉米'] }
      if (url.endsWith('/config')) return { seed_id: '120' }
      throw new Error('站点读取失败')
    },
    post: async (url, data) => { posts.push([url, data]); return { success: true, config: data } },
  })
  await Promise.all([state.loadConfig(), state.loadSeeds(), state.loadStealConfig()])
  assert.deepEqual(state.seedOptions.value, [])
  assert.equal(state.seedError.value, '站点读取失败')
  await state.saveStealConfig()
  assert.equal(state.config.seed_id, '120')
  assert.ok(posts.every(([url, data]) => url.endsWith('/steal-config') && !('seed_id' in data)))
})

test('failed configuration reads cannot save frontend fallback defaults', async () => {
  let writes = 0
  const state = configHarness({
    get: async () => { throw new Error('连接失败') },
    post: async () => { writes++; return { success: true } },
  }, { seed_id: '120' })
  await Promise.all([state.loadConfig(), state.loadStealConfig()])
  await state.saveConfig()
  await state.saveStealConfig()
  assert.equal(writes, 0)
  assert.equal(state.config.seed_id, '120')
})

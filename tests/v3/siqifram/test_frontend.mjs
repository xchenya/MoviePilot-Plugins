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

test('crop choices are saved as a subset and clearing all stays empty', async () => {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Config.vue'), 'utf8')
  const options = source.split('\n').find(line => line.startsWith('const stealCropOptions ='))
  assert.deepEqual(new Function(options + '; return stealCropOptions')(),
    ['萝卜', '西红柿', '玉米', '茄子', '蘑菇', '樱桃'])
  const method = 'async function saveConfig()' + source.split('async function saveConfig()')[1]
    .split('onMounted(')[0]
  const posts = []
  const config = { steal_crops: ['萝卜', '樱桃'], harvest_delay_minutes: 2 }
  const run = new Function('config', 'saving', 'apiPost', 'emit', 'show',
    method + '; return saveConfig')(config, { value: false },
      async (url, data) => { posts.push([url, data]); return { success: true, config: data } },
      () => {}, () => {})
  await run()
  config.steal_crops = []
  await run()
  assert.deepEqual(posts.map(([, data]) => data.steal_crops), [['萝卜', '樱桃'], []])
})

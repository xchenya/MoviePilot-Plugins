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

test('steal card renders the server pause deadline and clears it when the quota is available again', () => {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Page.vue'), 'utf8')
  const template = source.match(/<div class="neu-action-desc" role="status"[^>]*>.*?<\/div>/)[0]
  const { compile } = require('@vue/compiler-dom')
  const render = new Function('Vue', compile(template, { mode: 'function' }).code)(require('vue'))
  const farm = { can_steal: true, steal_paused_until: '2026-10-21 00:00:00' }
  assert.equal(render({ farm }).children, '今日偷菜已用完，暂停至 2026-10-21 00:00:00')
  farm.steal_paused_until = null
  assert.equal(render({ farm }).children, '按当日剩余可偷数量寻找所选作物')
  assert.match(source, /:disabled="!farm\.can_steal"/)
})

function configHarness(api, initialConfig = {}) {
  const source = fs.readFileSync(path.join(plugin, 'src/components/Config.vue'), 'utf8')
  const { descriptor } = parse(source)
  const script = descriptor.scriptSetup.content.split('\n')
    .filter(line => !line.startsWith('import ')).join('\n')
  return new Function('reactive', 'ref', 'onMounted', 'defineProps', 'defineEmits',
    'setTimeout', 'clearTimeout', script + '\nreturn { config, stealConfig, seedOptions, seedError, seedCached, seedLoading, configLoaded, stealLoaded, stealSaving, stealStatus, stealStatusType, loadConfig, loadSeeds, loadStealConfig, saveConfig, saveStealConfig }')(
      value => value, value => ({ value }), () => {},
      () => ({ api, pluginId: 'SiqiFram', initialConfig }), () => () => {},
      () => 0, () => {},
    )
}

test('planting seed list keeps all crops and unlock status, separate steal Cron save cannot change planting settings', async () => {
  const posts = []
  const api = {
    get: async url => {
      if (url.endsWith('/steal-config')) return { auto_steal: true, steal_crops: ['萝卜'], steal_cron: '*/20 * * * *' }
      if (url.endsWith('/config')) return { seed_id: '120', cron: '0 */4 * * *', ai_available: false, auto_steal: true, steal_crops: ['萝卜'], steal_cron: '*/20 * * * *' }
      assert.ok(url.endsWith('/seeds'))
      return { success: true, seeds: [
        { id: 91, name: '萝卜', unlock_harvest: 0 },
        { id: 120, name: '樱桃', unlock_harvest: 40 },
        { id: 200, name: '西瓜', unlock_harvest: 100 },
      ], user_stats: { total_harvest: 50 } }
    },
    post: async (url, data) => { posts.push([url, structuredClone(data)]); return { success: true, config: data } },
  }
  const state = configHarness(api, { seed_id: '120', steal_crops: ['萝卜'], steal_cron: '*/30 * * * *' })
  assert.equal('steal_cron' in state.config, false)
  assert.equal(state.stealConfig.steal_cron, '*/30 * * * *')
  await Promise.all([state.loadConfig(), state.loadSeeds(), state.loadStealConfig()])
  assert.deepEqual(state.seedOptions.value.map(s => [s.value, s.locked]),
    [['91', false], ['120', false], ['200', true]])
  assert.equal(state.config.seed_id, '120')
  assert.equal('steal_crops' in state.config, false)
  assert.equal('auto_steal' in state.config, false)
  assert.equal('steal_cron' in state.config, false)
  assert.equal(state.stealConfig.steal_cron, '*/20 * * * *')
  state.stealConfig.steal_crops = ['玉米', '樱桃']
  state.stealConfig.steal_cron = '*/10 * * * *'
  await state.saveStealConfig()
  state.stealConfig.steal_crops = []
  await state.saveStealConfig()
  await state.saveConfig()
  assert.equal(posts.length, 3)
  assert.deepEqual(posts.slice(0, 2), [
    ['plugin/SiqiFram/steal-config', { auto_steal: true, steal_crops: ['玉米', '樱桃'], steal_cron: '*/10 * * * *' }],
    ['plugin/SiqiFram/steal-config', { auto_steal: true, steal_crops: [], steal_cron: '*/10 * * * *' }],
  ])
  assert.equal(posts[2][0], 'plugin/SiqiFram/config')
  assert.equal(posts[2][1].seed_id, '120')
  assert.equal(posts[2][1].cron, '0 */4 * * *')
  assert.equal('steal_crops' in posts[2][1], false)
  assert.equal('auto_steal' in posts[2][1], false)
  assert.equal('steal_cron' in posts[2][1], false)
  assert.equal(state.config.seed_id, '120')
  assert.equal(state.config.cron, '0 */4 * * *')
})

test('legacy steal configuration defaults to an independent fifteen minute Cron', async () => {
  const posts = []
  const state = configHarness({
    get: async () => ({ auto_steal: true, steal_crops: ['茄子'] }),
    post: async (url, data) => { posts.push([url, structuredClone(data)]); return { success: true, config: data } },
  })
  assert.equal(state.stealConfig.steal_cron, '*/15 * * * *')
  await state.loadStealConfig()
  assert.equal(state.stealConfig.steal_cron, '*/15 * * * *')
  await state.saveStealConfig()
  assert.deepEqual(posts, [
    ['plugin/SiqiFram/steal-config', { auto_steal: true, steal_crops: ['茄子'], steal_cron: '*/15 * * * *' }],
  ])
})

test('save and run waits for saved steal settings, prevents duplicate clicks, and preserves planting settings', async () => {
  const posts = []
  let finishSave
  let finishRun
  const state = configHarness({
    get: async () => ({ auto_steal: false, steal_crops: ['茄子'], steal_cron: '*/15 * * * *' }),
    post: (url, data) => {
      posts.push([url, structuredClone(data)])
      return new Promise(resolve => {
        if (url.endsWith('/steal-config')) finishSave = resolve
        else finishRun = resolve
      })
    },
  }, { seed_id: '120', cron: '0 */4 * * *', cookie: 'unchanged' })
  await state.loadStealConfig()
  const planting = structuredClone(state.config)
  const running = state.saveStealConfig(true)
  assert.equal(state.stealSaving.value, true)
  assert.equal(state.stealStatus.value, '正在保存偷菜设置…')
  await state.saveStealConfig(true)
  await state.saveStealConfig()
  assert.deepEqual(posts, [
    ['plugin/SiqiFram/steal-config', { auto_steal: false, steal_crops: ['茄子'], steal_cron: '*/15 * * * *' }],
  ])
  finishSave({ success: true, config: posts[0][1] })
  await Promise.resolve()
  assert.equal(state.stealStatus.value, '偷菜设置已保存，正在运行一次偷菜…')
  assert.equal(state.stealSaving.value, true)
  assert.deepEqual(posts.map(([url]) => url), ['plugin/SiqiFram/steal-config', 'plugin/SiqiFram/steal'])
  assert.equal(posts[1][1], undefined)
  await state.saveStealConfig(true)
  await state.saveStealConfig()
  assert.equal(posts.length, 2)
  finishRun({ success: true, message: '偷菜完成：成功 2 个，获得 50 魔力' })
  await running
  assert.equal(state.stealStatus.value, '偷菜设置已保存；偷菜完成：成功 2 个，获得 50 魔力')
  assert.equal(state.stealStatusType.value, 'success')
  assert.equal(state.stealSaving.value, false)
  assert.equal(state.stealConfig.auto_steal, false)
  assert.deepEqual(state.config, planting)
  const source = fs.readFileSync(path.join(plugin, 'src/components/Config.vue'), 'utf8')
  assert.match(source, /role="status" aria-live="polite">\{\{ stealStatus \}\}/)
})

test('save and run never executes when saving fails or its outcome is unknown', async () => {
  for (const response of [{ success: false, message: 'Cron 格式无效' }, new Error('保存连接中断')]) {
    const posts = []
    const state = configHarness({
      get: async () => ({ auto_steal: true, steal_crops: ['萝卜'] }),
      post: async url => {
        posts.push(url)
        if (response instanceof Error) throw response
        return response
      },
    })
    await state.loadStealConfig()
    await state.saveStealConfig(true)
    assert.deepEqual(posts, ['plugin/SiqiFram/steal-config'])
    assert.match(state.stealStatus.value, response instanceof Error ? /保存连接中断/ : /Cron 格式无效/)
    assert.equal(state.stealStatusType.value, 'error')
    assert.equal(state.stealSaving.value, false)
  }
})

test('run failures and uncertain outcomes keep the saved state and report the real result without retrying', async () => {
  const cases = [
    [{ success: false, message: '未找到所选范围内的成熟作物' }, '偷菜设置已保存，但运行失败：未找到所选范围内的成熟作物'],
    [{ success: false, uncertain: true, message: '请求超时，结果不明' }, '偷菜设置已保存；执行结果不明：请求超时，结果不明'],
    [new Error('连接中断'), '偷菜设置已保存，但未能确认偷菜执行结果：连接中断'],
  ]
  for (const [result, expected] of cases) {
    const posts = []
    const state = configHarness({
      get: async () => ({ auto_steal: false, steal_crops: ['玉米'] }),
      post: async (url, data) => {
        posts.push(url)
        if (url.endsWith('/steal-config')) return { success: true, config: data }
        if (result instanceof Error) throw result
        return result
      },
    })
    await state.loadStealConfig()
    await state.saveStealConfig(true)
    assert.deepEqual(posts, ['plugin/SiqiFram/steal-config', 'plugin/SiqiFram/steal'])
    assert.equal(state.stealStatus.value, expected)
    assert.equal(state.stealStatusType.value, 'error')
    assert.equal(state.stealSaving.value, false)
    assert.deepEqual(state.stealConfig.steal_crops, ['玉米'])
  }
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
  await state.saveStealConfig(true)
  assert.equal(writes, 0)
  assert.equal(state.config.seed_id, '120')
})

test('opening with a cached catalog sends no site refresh; explicit refresh preserves the selection', async () => {
  const calls = []
  const state = configHarness({ get: async url => {
    calls.push(url)
    return { success: true, cached: !url.includes('?'),
      seeds: [{ id: 120, name: '樱桃', unlock_harvest: 40 }],
      user_stats: { total_harvest: url.includes('?') ? 50 : 20 } }
  } }, { seed_id: '120' })
  await state.loadSeeds()
  assert.equal(state.seedCached.value, true)
  assert.equal(state.seedOptions.value[0].locked, true)
  assert.deepEqual(calls, ['plugin/SiqiFram/seeds'])
  await state.loadSeeds(true)
  assert.equal(state.seedCached.value, false)
  assert.equal(state.seedOptions.value[0].locked, false)
  assert.equal(state.config.seed_id, '120')
  assert.deepEqual(calls, ['plugin/SiqiFram/seeds', 'plugin/SiqiFram/seeds?refresh=true'])
})

test('a missing cache triggers only one refresh and does not overwrite the planting seed', async () => {
  const calls = []
  const state = configHarness({ get: async url => {
    calls.push(url)
    return url.includes('?') ? { success: true, cached: false, seeds: [{ id: 91, name: '萝卜' }] }
      : { success: false, needs_refresh: true }
  } }, { seed_id: '120' })
  await state.loadSeeds()
  assert.deepEqual(calls, ['plugin/SiqiFram/seeds', 'plugin/SiqiFram/seeds?refresh=true'])
  assert.equal(state.config.seed_id, '120')
  assert.deepEqual(state.seedOptions.value.map(s => s.value), ['91'])
})

test('busy refresh keeps the loaded catalog and distinguishes reading from farming without retrying', async () => {
  let refreshes = 0
  let reason = '数据读取中'
  const state = configHarness({ get: async url => {
    if (url.includes('?')) { refreshes++; return { success: false, message: reason + '，请稍后重试' } }
    return { success: true, cached: true, seeds: [{ id: 120, name: '樱桃' }] }
  } }, { seed_id: '120' })
  await state.loadSeeds()
  const options = structuredClone(state.seedOptions.value)
  for (reason of ['数据读取中', '农场任务执行中']) {
    await state.loadSeeds(true)
    assert.equal(state.seedError.value, reason + '，请稍后重试')
    assert.deepEqual(state.seedOptions.value, options)
    assert.equal(state.seedCached.value, true)
    assert.equal(state.seedLoading.value, false)
    assert.equal(state.config.seed_id, '120')
  }
  assert.equal(refreshes, 2)
})

test('refresh cannot be started twice and a saved Cookie change clears the old account list', async () => {
  let finish
  let requests = 0
  let posts = 0
  const pending = new Promise(resolve => { finish = resolve })
  const state = configHarness({
    get: async url => {
      if (url.endsWith('/config')) return { seed_id: '120', cookie: '' }
      requests++
      if (requests > 1) {
        assert.deepEqual(state.seedOptions.value, [])
        return { success: false, message: '新账号读取失败' }
      }
      return pending
    },
    post: async (url, data) => { posts++; return { success: true, config: data } },
  })
  await state.loadConfig()
  const loading = state.loadSeeds(true)
  await state.loadSeeds(true)
  assert.equal(requests, 1)
  assert.equal(state.seedLoading.value, true)
  await state.saveConfig()
  assert.equal(posts, 0)
  finish({ success: true, seeds: [{ id: 120, name: '樱桃' }] })
  await loading
  state.config.cookie = 'session=changed'
  state.seedOptions.value = [{ value: 'old-account' }]
  await state.saveConfig()
  assert.equal(requests, 2)
  assert.equal(posts, 1)
  assert.deepEqual(state.seedOptions.value, [])
  assert.equal(state.seedError.value, '新账号读取失败')
  assert.equal(state.config.seed_id, '120')
})

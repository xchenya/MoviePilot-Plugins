import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const pythonSource = [
  'import importlib.util, json, sys',
  'from pathlib import Path',
  'spec=importlib.util.spec_from_file_location("native_helper_auth",Path(sys.argv[1])/"plugins.v3/hdskydicebetnatural/helper_auth.py")',
  'm=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)',
  'form,defaults=m.login_form("HdskyDiceBetNatural_instance",m.HelperAuthState())',
  'print(json.dumps({"form":form,"defaults":defaults,"import":m.click_handler("import")}))',
].join('\n')
const generated = spawnSync(process.env.PYTHON || 'python', ['-c', pythonSource, root], { encoding: 'utf8' })
assert.equal(generated.status, 0, generated.stderr)
const fixture = JSON.parse(generated.stdout), nodes = []
function collect(node) { nodes.push(node); for (const child of node.content || []) collect(child) }
collect(fixture.form)
const handlers = Object.fromEntries(nodes.filter(n => n.props?.onClick).map(n => [n.props.text, n.props.onClick]))
const model = () => ({ ...fixture.defaults, site_id: 49, helper_uid: '123', helper_email: 'u@example.test',
  helper_code: '012345', bet_amount: 500, helper_cookie: '', helper_refresh_token: '' })
// Same function/model binding as MP FormRender.parseProps; window is the test host.
const invoke = (handler, form, api) => new Function('model', 'event', 'window',
  'with(model) { return (' + handler + ')(event); }')(form, {}, { MoviePilotAPI: api })

test('configuration buttons do not submit the outer form', () => {
  for (const label of ['发送验证码', '登录', '刷新登录状态']) assert.ok(handlers[label])
  for (const button of nodes.filter(n => n.component === 'VBtn')) assert.equal(button.props.type, 'button')
  const inputs = nodes.filter(n => n.component === 'VTextField')
  assert.deepEqual(inputs.map(n => n.props.model), ['helper_uid', 'helper_email', 'helper_code'])
  assert.equal(inputs[2].props.type, 'password')
})

test('send and login use instance endpoint without saving/reloading the draft', async () => {
  const form = model(), calls = []
  const api = { async post(path, body) {
    calls.push({ path, body }); assert.equal(form.helper_busy, true)
    return { success: true, message: body.action === 'send' ? '已发送' : '登录成功' }
  } }
  await invoke(handlers['发送验证码'], form, api)
  assert.equal(form.helper_login_message, '已发送')
  await invoke(handlers['登录'], form, api)
  assert.equal(form.helper_login_message, '登录成功')
  assert.equal(form.helper_code, ''); assert.equal(form.helper_busy, false); assert.equal(form.bet_amount, 500)
  assert.equal(calls.length, 2)
  assert.ok(calls.every(c => c.path === 'plugin/HdskyDiceBetNatural_instance/helper/auth'))
  assert.equal(calls[0].body.action, 'send'); assert.equal(calls[0].body.code, undefined)
  assert.equal(calls[1].body.code, '012345'); assert.equal(calls[1].body.site_id, 49)
  assert.ok(calls.every(c => !('bet_amount' in c.body)))
})

test('busy state prevents double clicks', async () => {
  const form = model(); let finish, calls = 0
  const api = { post() { calls++; return new Promise(resolve => { finish = resolve }) } }
  const first = invoke(handlers['发送验证码'], form, api)
  await invoke(handlers['发送验证码'], form, api)
  assert.equal(calls, 1); finish({ success: true, message: '已发送' }); await first
})

test('timeout clears code, releases buttons, does not replay and offers status check', async () => {
  const form = model(); let calls = 0
  await invoke(handlers['登录'], form, { post() { calls++; throw new Error('private body') } })
  assert.equal(calls, 1); assert.equal(form.helper_code, ''); assert.equal(form.helper_busy, false)
  assert.equal(form.helper_login_type, 'warning')
  assert.match(form.helper_login_message, /刷新登录状态/); assert.doesNotMatch(form.helper_login_message, /private body/)
})

test('business errors remain on the configuration page', async () => {
  const form = model()
  await invoke(handlers['登录'], form, { async post() { return { success: false, message: '验证码过期' } } })
  assert.equal(form.helper_login_type, 'warning'); assert.equal(form.helper_login_message, '验证码过期')
})

test('manual inputs are cleared before the authenticated request', async () => {
  const form = model(); form.helper_cookie = 'access-private'; form.helper_refresh_token = 'refresh-private'
  await invoke(fixture.import, form, { async post(path, body) {
    assert.equal(form.helper_cookie, ''); assert.equal(form.helper_refresh_token, '')
    assert.equal(body.access_token, 'access-private'); assert.equal(body.refresh_token, 'refresh-private')
    assert.equal(body.action, 'import'); assert.ok(path.endsWith('/helper/auth'))
    return { success: true, message: '已保存' }
  } })
})

test('missing frontend client restores the form without reading browser credentials', async () => {
  const form = model(); await invoke(handlers['登录'], form, null)
  assert.equal(form.helper_busy, false); assert.equal(form.helper_code, ''); assert.equal(form.helper_login_type, 'warning')
})

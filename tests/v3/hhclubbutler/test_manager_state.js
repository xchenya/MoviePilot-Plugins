/* Full page initialization with inert DOM, storage and HTTP; no live browser/data. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.resolve(__dirname, '../../../plugins.v3/hhclubbutler/__init__.py'), 'utf8');
const manager = source.split('def _build_rescue_panel_html(')[1].split('<script>')[1].split('</script>')[0];
const monthly = source.split('def _build_monthly_stats_html(')[1].split('<script>')[1].split('</script>')[0];
new vm.Script(manager);
new vm.Script(monthly);

function fixture() {
  const nodes = {}, attributes = {}, memory = {};
  const get = id => nodes[id] ||= {
    id, style: {}, dataset: {}, hidden: false,
    classList: {add() {}, remove() {}, toggle() {}},
    querySelector: () => get('note'), querySelectorAll: () => [], focus() {}, addEventListener() {},
  };
  return {
    nodes, get, context: {
      console, Promise, Date, Math, AbortController,
      setTimeout: (fn, delay) => delay === 3000 ? setTimeout(fn, 0) : 0,
      clearTimeout, setInterval: () => 0, clearInterval() {},
      window: {crypto: {}, closed: false},
      document: {
        getElementById: get, querySelectorAll: () => [], addEventListener() {},
        body: {style: {}, setAttribute: (key, value) => attributes[key] = value,
               getAttribute: key => attributes[key]},
      },
      localStorage: {getItem: () => null, setItem() {}},
      sessionStorage: {getItem: key => memory[key] || null, setItem: (key, value) => memory[key] = value,
                       removeItem: key => delete memory[key]},
      fetch: () => {throw new Error('Live network forbidden');},
    },
  };
}

(async () => {
  const {context: c, get} = fixture();
  // Keep all initialization/handler definitions. Exclude only startup I/O.
  vm.runInNewContext(manager.slice(0, manager.lastIndexOf('buildHead();load(false);resumePendingDelete();')), c);
  assert.notEqual(c.sel, get('themeSel'), 'selection state must remain independent of theme SELECT');
  c.seeds = [{seed_id: 51999, title: 'Release', size: 8},
             {seed_id: -909512442331, title: 'Unfinished', source: 'downloader', size: 3}];
  c.filtered = c.seeds;
  c.buildHead();
  get('chkAll').checked = true;
  get('chkAll').onchange();
  assert.equal(c.sel['51999'], true);
  assert.equal(c.sel['-909512442331'], true);
  assert.equal(get('seln').textContent, 2);
  get('themeSel').value = 'light';
  get('themeSel').onchange();
  assert.equal(c.sel['51999'], true, 'theme changes must preserve selection');

  const record = {id: 'audit-request-1234', item: {targets: [{downloader: 'QB', hash: 'a'.repeat(40)}]}};
  let posts = 0;
  c.fetchJson = async () => {posts++; return {success: true};};
  c.pollDeleteStatus = async () => ({status: 'unknown', message: 'mock interrupted status query'});
  c.load = () => {};
  c.savePending(record);
  assert.equal(await c.followDeletion(record, false), 'uncertain');
  assert.equal(c.readPending().id, record.id, 'unknown status must retain the original request');
  await c.doDel([record.item]);
  assert.equal(posts, 0, 'pending uncertainty cannot submit another deletion');
  c.pollDeleteStatus = async () => ({status: 'resolved', message: 'Only sent hashes were reconciled'});
  assert.equal(await c.followDeletion(record, true), 'resolved');
  assert.equal(c.readPending(), null);

  const {context: stats} = fixture();
  const urls = [];
  stats.fetch = async url => {
    urls.push(url);
    return {ok: true, json: async () => urls.length === 1 ? {loading: true} : {
      loading: false, labels: [], bean: [], pt: [], notes: [], records: [], fetch_state: 'ok',
    }};
  };
  vm.runInNewContext(monthly.replace('loadData(false);', ''), stats);
  await stats.loadData(true);
  assert.equal(urls.length, 2);
  assert(urls[0].endsWith('?refresh=1'));
  assert(!urls[1].includes('refresh='), 'polling must not repeatedly force a new settlement job');
  assert.equal(stats.statsLoading, false);
  console.log('PASS: full manager state, all-selection, theme isolation, persistent unknown request and short settlement polling');
})().catch(error => {console.error(error); process.exitCode = 1;});

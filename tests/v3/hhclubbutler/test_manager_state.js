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

  c.seeds = [{seed_id: 51999, title: 'Shared title', size: 8, candidates: []},
             {seed_id: -909512442331, title: 'Shared title', source: 'downloader', size: 3}];
  c.sel['-909512442331'] = true;
  assert(c.cellVal({k: 'c_sid'}, c.seeds[1]).includes('未关联站点种子 ID'));
  assert.notEqual(c.cellVal({k: 'c_sid'}, c.seeds[1]), '下载器');
  c.forgetVerifiedItem({seed_id: -909512442331, title: 'Shared title'});
  assert.equal(c.seeds.length, 1, 'confirmed downloader-only deletion removes the row');
  assert.equal(c.seeds[0].seed_id, 51999, 'the same title must not erase a site eligibility row');
  assert.equal(c.sel['-909512442331'], undefined);
  c.forgetVerifiedItem({seed_id: 51999, title: 'Shared title'});
  assert.equal(c.seeds.length, 1, 'site eligibility remains after its downloader tasks are removed');

  c.dlSel = {QB: true};
  c.seeds = Array.from({length: 9}, (_, i) => ({seed_id: i + 1, title: 'Release ' + i, size: 1,
    candidates: [{downloader: 'QB', hash: String(i).repeat(40), match_type: 'exact'}]}));
  c.seeds[0].candidates.push({downloader: 'QB', hash: 'b'.repeat(40), match_type: 'translated'},
    {downloader: 'TR', hash: 'a'.repeat(40), match_type: 'exact'}, c.seeds[0].candidates[0]);
  c.filtered = c.seeds;
  c.renderFooter();
  assert.equal(get('visibleCount').textContent, 9);
  assert.equal(get('linkedTaskCount').textContent, 10, 'QB hashes count separately from groups and TR');
  c.filtered.push({seed_id: 10, title: 'Uncertain', match_status: 'ambiguous',
    candidates: [{downloader: 'QB', hash: 'e'.repeat(40), match_type: 'exact'}]});
  c.renderFooter();
  assert.equal(get('linkedTaskCount').textContent, 10, 'ambiguous candidates are not confirmed tasks');

  const record = {id: 'audit-request-1234', item: {targets: [{downloader: 'QB', hash: 'a'.repeat(40)}]}};
  let posts = 0, refreshes = [];
  c.fetchJson = async () => {posts++; return {success: true};};
  c.pollDeleteStatus = async () => ({status: 'unknown', message: 'mock interrupted status query'});
  c.load = async (force, clients) => refreshes.push({force, clients: Array.from(clients || [])});
  c.savePending(record);
  assert.equal(await c.followDeletion(record, false), 'uncertain');
  assert.equal(c.readPending().id, record.id, 'unknown status must retain the original request');
  await c.doDel([record.item]);
  assert.equal(posts, 0, 'pending uncertainty cannot submit another deletion');
  c.pollDeleteStatus = async () => ({status: 'resolved', message: 'Only sent hashes were reconciled'});
  assert.equal(await c.followDeletion(record, true), 'resolved');
  assert.equal(c.readPending(), null);
  assert.deepEqual(refreshes, [{force: true, clients: ['QB']}]);

  refreshes = [];
  c.pollDeleteStatus = async () => ({status: 'verified', removed_count: 1});
  const groups = [1, 2].map(i => ({seed_id: i, title: 'Release ' + i,
    targets: [{downloader: 'QB', hash: String(i).repeat(40)}]}));
  await c.doDel(groups);
  assert.equal(posts, 2);
  assert.deepEqual(refreshes, [{force: true, clients: ['QB']}], 'batch refreshes QB once after all groups');
  refreshes = [];
  c.pollDeleteStatus = async () => ({status: 'uncertain', removed_count: 0});
  await c.doDel(groups);
  assert.equal(posts, 3, 'partial or unknown results stop the remaining groups');
  assert.deepEqual(refreshes, [{force: true, clients: ['QB']}]);
  await c.doDel(groups);
  assert.equal(posts, 3, 'a new click cannot resubmit an uncertain deletion');
  c.clearPending();
  refreshes = [];
  c.pollDeleteStatus = async () => ({status: 'verified', removed_count: 1});
  await c.doDel([groups[0], {...groups[1], targets: [{downloader: 'TR', hash: 'c'.repeat(40)}]}]);
  assert.equal(posts, 5);
  assert.deepEqual(refreshes, [{force: true, clients: ['QB', 'TR']}], 'multi-client batches refresh the union once');

  const {context: list, get: listGet} = fixture();
  vm.runInNewContext(manager.slice(0, manager.lastIndexOf('buildHead();load(false);resumePendingDelete();')), list);
  const reads = [];
  list.fetch = async url => {
    reads.push(new URL(url, 'https://fixture.invalid'));
    return {ok: true, json: async () => reads.length === 1 ? {success: true, loading: true} :
      {success: true, data: []}};
  };
  await list.load(true, ['QB']);
  assert.equal(reads.length, 2);
  assert.equal(reads[0].searchParams.get('refresh'), '1');
  assert.equal(reads[1].searchParams.get('refresh'), null);
  reads.forEach(url => assert.deepEqual(JSON.parse(url.searchParams.get('downloaders')), ['QB']));
  list.fetch = async () => ({ok: false, status: 503});
  await list.load(true, ['QB']);
  list.fetch = async url => {
    assert.deepEqual(JSON.parse(new URL(url, 'https://fixture.invalid').searchParams.get('downloaders')), ['QB']);
    return {ok: true, json: async () => ({success: true, data: []})};
  };
  await listGet('retryLoad').onclick();

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
  console.log('PASS: manager selection, truthful IDs/counts, removed rows, scoped batch refresh/poll/retry, pending guards and settlement polling');
})().catch(error => {console.error(error); process.exitCode = 1;});

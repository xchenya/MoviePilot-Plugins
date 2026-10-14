/* Regression: cross-seed picker must identify one task by hash, not a title. */
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const src = fs.readFileSync(
  path.resolve(__dirname, "../../../plugins.v3/hhclubbutler/__init__.py"),
  "utf8"
);
const a = src.indexOf("var copyPickerResolve=null,copyPickerChoice=null;");
const b = src.indexOf("function openDeleteDialog(items){", a);
assert(a >= 0 && b > a, "picker script not found in management page");
const js = src.slice(a, b);
function el(tag = "div") {
  return {
    tag, children: [], disabled: false, hidden: false,
    textContent: "", checked: false,
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren() { this.children = []; },
    focus() {}, onclick: null,
  };
}
const ids = {
  hhCopyOverlay: el(), hhCopyList: el(),
  hhCopyDesc: el(), hhCopyTitle: el(),
  hhCloseCopies: el("button"), hhChooseCopy: el("button"),
};
const shown = [];
const doc = {
  getElementById(id) { assert(ids[id], "missing UI element " + id); return ids[id]; },
  createElement(tag) { return el(tag); },
  addEventListener() {},
};
const ctx = { document: doc, Promise, showToast: (message) => shown.push(message) };
vm.runInNewContext(js, ctx, { timeout: 1000 });

(async function main() {
  const seed = {
    title: "Same release",
    candidates: [
      { downloader:"Transmission", hash:"a".repeat(40), hash_short:"aaaaaaaaaaaa",
        can_remove:true, trusted_tracker:true, tracker:"tracker.hhanclub.net", completed:true },
      { downloader:"Transmission", hash:"b".repeat(40), hash_short:"bbbbbbbbbbbb",
        can_remove:true, trusted_tracker:false, tracker:"tracker.otherpt.example", completed:true },
      { downloader:"qBittorrent", hash:"", hash_short:"",
        can_remove:false, trusted_tracker:false, tracker:"unknown", completed:false },
    ],
  };
  const pending = ctx.openCopyPicker(seed);
  assert.equal(ids.hhCopyOverlay.hidden, false);
  assert.equal(ids.hhCopyList.children.length, 3);
  assert.equal(ids.hhChooseCopy.disabled, true, "must not choose implicitly");
  assert.equal(ids.hhCopyList.children[2].children[0].disabled, true);
  ids.hhCopyList.children[1].children[0].onchange();
  assert.equal(ids.hhChooseCopy.disabled, false);
  ids.hhChooseCopy.onclick();
  const selected = await pending;
  assert.equal(selected.downloader, "Transmission");
  assert.equal(selected.hash, "b".repeat(40));
  assert.equal(ids.hhCopyOverlay.hidden, true);

  const cancelled = ctx.openCopyPicker(seed);
  ids.hhCloseCopies.onclick();
  assert.equal(await cancelled, null);
  assert.equal(ids.hhCopyOverlay.hidden, true);
  assert.equal(shown.length, 0);
  console.log("PASS: cross-seed task picker requires explicit hash, honours disabled tasks and cancellation");
})().catch(e => { console.error(e); process.exitCode = 1; });

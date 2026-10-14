/* Browser-free regression of the new delete-all cross-seed workflow. */
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const src=fs.readFileSync(
 path.resolve(__dirname,"../../../plugins.v3/hhclubbutler/__init__.py"),"utf8");
assert(!src.includes('id="hhCopyOverlay"'),"old single-hash picker must be removed");

const a=src.indexOf("function groupFromSeed(seed){");
const b=src.indexOf('document.getElementById("btnDel").onclick=delSel;',a);
assert(a>=0&&b>a,"new group JS must exist");

const ids={};
function getId(id){
 if(!ids[id])ids[id]={hidden:false,disabled:false,textContent:"",
  focus(){},querySelector(){return getId("note")}};
 return ids[id];
}
const actions=[];
const context={
 Promise,console,setTimeout,clearTimeout,
 dialogResolve:null,
 deletionBusy:false,
 seeds:[],
 sel:{},
 readPending:()=>null,
 savePending:record=>actions.push(["pending",record]),
 clearPending:()=>actions.push(["clear"]),
 toggleDeletionBusy:b=>actions.push(["busy",b]),
 showToast:(message)=>actions.push(["toast",message]),
 createRequestId:()=>"ee11bb33-1234-5678-abcd-123412341234",
 fetchJson:async(url,opts)=>{actions.push(["POST",url,opts]);return {success:true};},
 followDeletion:async()=>{actions.push(["follow"]);return "verified";},
 load:(force)=>actions.push(["refresh",force]),
 document:{getElementById:getId},
};
vm.runInNewContext(src.slice(a,b),context,{timeout:1000});
context.followDeletion=async()=>{actions.push(["follow"]);return "verified";};
const seed={
 seed_id:51999,title:"A Lifetime Love S01",
 can_delete_group:true,cross_seed_count:3,
 candidates:[
  {downloader:"Transmission",hash:"a".repeat(40)},
  {downloader:"Transmission",hash:"b".repeat(40)},
  {downloader:"qBittorrent",hash:"c".repeat(40)}
 ]
};
const item=context.groupFromSeed(seed);
assert.equal(item.targets.length,3);
assert.equal(item.delete_file,true);
const notReady={...seed,can_delete_group:false};
assert.equal(context.groupFromSeed(notReady),null);

const confirmStart=src.indexOf("function openDeleteDialog(items){");
const confirmEnd=src.indexOf("function closeDeleteDialog(accepted){",confirmStart);
const closeEnd=src.indexOf('document.getElementById("hhCancelDelete").onclick=',confirmEnd);
assert(confirmStart>=0&&confirmEnd>confirmStart);
vm.runInNewContext(src.slice(confirmStart,closeEnd),context,{timeout:1000});
(async()=>{
 const prompt=context.openDeleteDialog([item]);
 assert(getId("hhConfirmTitle").textContent.includes("全部辅种"));
 assert(getId("hhConfirmDesc").textContent.includes("3 个"));
 assert(getId("hhConfirmDesc").textContent.includes("Transmission: 2"));
 assert(getId("hhConfirmDesc").textContent.includes("qBittorrent: 1"));
 assert(getId("note").textContent.includes("不可撤销"));
 assert(getId("hhAcceptDelete").textContent.includes("3 个任务"));
 context.closeDeleteDialog(true);
 assert.equal(await prompt,true);
 await context.doDel([item]);
 const posted=actions.find(x=>x[0]==="POST");
 assert(posted,"must submit group POST");
 assert.equal(posted[1],"/api/v1/plugin/HHClubButler/delete_rescue_group");
 assert.equal(posted[2].method,"POST");
 assert.equal(posted[2].headers["X-HHClub-Request"],"1");
 const body=JSON.parse(posted[2].body);
 assert.equal(body.targets.length,3);
 assert.equal(body.delete_file,true);
 assert.equal(body.confirm,true);
 assert.equal(body.seed_id,51999);
 assert.equal(actions.filter(x=>x[0]==="POST").length,1,
  "must not repeat destructive POST");
 assert(actions.some(x=>x[0]==="refresh"&&x[1]===true));
 console.log("PASS: delete-all default, visible count, irreversible warning, one JSON manifest and no automatic retry");
})().catch(e=>{console.error(e);process.exitCode=1});

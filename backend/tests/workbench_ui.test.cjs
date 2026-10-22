// Current production dashboard DOM behavior; synthetic data only.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../../frontend/node_modules/jsdom');
const assets = path.resolve(__dirname, '../src/nba_time_machine/workbench/static');
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
function report() {
  return {slate_date:'2026-10-14', as_of:'2026-10-15T04:00:00Z', coverage:'Validated fixtures', games:[{
    game_id:'fixture', away:'Away', home:'Home', status:'final', published:true, missing_families:[], diagnostics:[],
    rating:{score:8, version:'postgame-watchability-v4', components:[{label:'Individual performance', points:4, normalized:1}]},
    enrichment:{players:[{name:'<img src=x onerror=alert(1)>', statistics:{PTS:60,AST:4,REB:3,STL:1,BLK:0,TO:1}, true_shooting:.75, severity:1}],patterns:[]},
    evidence:{source:'fixture'}, settings:{}, context:{},
  }]};
}
async function setup(transform = r => r) {
  const dom = new JSDOM(fs.readFileSync(path.join(assets,'index.html'),'utf8'), {url:'http://127.0.0.1:8765/?date=2026-10-14', runScripts:'outside-only'});
  const calls=[];
  dom.window.fetch = async (url, options={}) => {
    calls.push({url,options});
    const data = url.includes('ringer-status') ? {state:'ready'}
      : url.startsWith('/api/verify?') ? {state:'finished',ratings:{eligible:1,unavailable:0,failed:0}}
      : options.method==='POST' ? {state:'running',job_id:'job'} : transform(report());
    return {ok:true,json:async()=>data};
  };
  dom.window.eval(fs.readFileSync(path.join(assets,'ratings.js'),'utf8'));
  await tick();
  return {dom,w:dom.window,calls};
}
test('one production rating, honest publication and safe text; loading only reads', async () => {
  const {dom,w,calls}=await setup();
  const text=w.document.body.textContent;
  assert.match(text,/Watchability 8.00 \/ 10/);
  assert.match(text,/Published to the viewing guide/);
  assert.doesNotMatch(text,/Proposed score|Current app score|Tune the formula/);
  assert.match(text,/Individual performance/);
  assert.equal(w.document.querySelectorAll('#detail img').length,0);
  assert(calls.every(c=>!c.options.method));
  dom.window.close();
});
test('unpublished and unavailable games never become zero ratings', async () => {
  const {dom,w}=await setup(r=>{r.games[0].published=false;return r;});
  assert.match(w.document.body.textContent,/Update needed/);
  assert.match(w.document.body.textContent,/Update ratings from stored evidence to publish/);
  dom.window.close();
  const other=await setup(r=>{r.games[0].rating=null;return r;});
  assert.match(other.w.document.body.textContent,/Rating unavailable/);
  assert.equal(other.w.document.querySelector('#games tr td:nth-child(2)').textContent,'—');
  other.dom.window.close();
});
test('stored-evidence update explicitly publishes, then refreshes with GET', async () => {
  const {dom,w,calls}=await setup();
  w.document.getElementById('publish').click();
  await new Promise(resolve=>setTimeout(resolve,1100));
  const posts=calls.filter(c=>c.options.method==='POST');
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/api/publish');
  assert.equal(posts[0].options.headers['X-Workbench-Action'],'collect-day');
  assert.deepEqual(JSON.parse(posts[0].options.body),{slate_date:'2026-10-14'});
  assert.match(w.document.getElementById('verification').textContent,/1 published/);
  assert.equal(calls.filter(c=>c.url.startsWith('/api/slate')).length,2);
  dom.window.close();
});

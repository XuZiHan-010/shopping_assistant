// 离线 DOM 交互检查：禁止页面发起网络请求，不需要模型或后端。
import { readFileSync } from 'node:fs';
import { Window } from 'happy-dom';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('../prototypes/commerce-agents-sandbox.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const window = new Window({ settings: { disableCSSFileLoading:true, disableJavaScriptFileLoading:true } });
let networkCalls=0;
window.fetch=()=>{networkCalls++;throw Error('Unexpected network');};
window.setTimeout=(fn)=>setTimeout(fn,0);
window.clearTimeout=clearTimeout;
window.document.write(html.replace(/<script>[\s\S]*?<\/script>/, '').replace(/<link[^>]*>/g,''));
window.eval(script);
const document=window.document;
const click=selector=>{const el=document.querySelector(selector);assert.ok(el,selector);el.click();};
const change=(selector,value)=>{
  const el=document.querySelector(selector);assert.ok(el,selector);
  if(el.type==='checkbox')el.checked=value;else el.value=String(value);
  el.dispatchEvent(new window.Event('change',{bubbles:true}));
};
const wait=async()=>{
  for(let i=0;i<500;i++){
    await new Promise(r=>setTimeout(r,20));
    if(!document.querySelector('.typing') && ![...document.querySelectorAll('[data-act="approve"]')].some(el=>el.disabled))return;
  }
  throw Error('模拟交互超时');
};
const choose=(project,surface)=>{click(`[data-act="project"][data-id="${project}"]`);click(`[data-act="surface"][data-id="${surface}"]`);};
const run=async id=>{click(`#app [data-act="run"][data-id="${id}"]`);await wait();assert.ok(!document.querySelector('#transcript').textContent.includes('模拟脚本出现错误'));};
const events=()=>{click('[data-act="atab"][data-id="events"]');return [...document.querySelectorAll('#events .frame')].map(e=>e.textContent).filter(t=>t.startsWith('event:')).map(t=>({type:t.split('\n')[0].slice(7),data:JSON.parse(t.split('\ndata: ')[1])}));};

choose('anthropic','am');
await run('m2');
assert.ok(document.querySelector('[data-act="approve"]'));
await run('campaign');
change('[data-lab-field="budget"]',11000);await run('campaign');
assert.match(document.querySelector('#transcript').textContent,/10,000/);
for(const k of ['am','as','sm','ss']){
  choose(k.startsWith('s')?'shopify':'anthropic',k);
  const ids=[...document.querySelectorAll('#app [data-act="run"]')].map(b=>b.dataset.id);
  for(const id of [...new Set(ids)]) await run(id);
  for(const event of events()){
    if(event.type==='tool_call'){assert.ok(event.data.tool);assert.ok(event.data.id);}
    if(event.type==='tool_result'){assert.ok(event.data.id);assert.equal(typeof event.data.is_error,'boolean');}
    if(event.type==='ui')assert.ok(!event.data.component.startsWith('present_'));
    if(event.type==='turn_complete')assert.equal(typeof event.data.usage,'object');
  }
}
choose('anthropic','as');
click('[data-act="as-add"]');
const before=document.querySelectorAll('.mini-cart').length;
click('[data-lab="cart"][data-delta="1"]');
assert.match(document.querySelector('.mini-cart').textContent,/2/);
click('[data-lab="cart"][data-delta="remove"]');
assert.equal(document.querySelectorAll('.mini-cart').length,before-1);

choose('shopify','ss');
change('[data-bind="ss-creds"]',true);change('[data-bind="ss-scope"]',true);
await run('u1');await run('u2');click('[data-lab="complete-order"]');await run('u4');
assert.match(document.querySelector('#transcript').textContent,/#1042/);
choose('shopify','sm');await run('promo');
const cards=[...document.querySelectorAll('#transcript [data-act="approve"]')];
cards.at(-1).click();await wait();
assert.match(document.querySelector('#transcript').textContent,/未创建 Shopify 折扣/);
change('[data-lab-field="marketingScope"]',false);await run('campaign-results');
assert.match(document.querySelector('#transcript').textContent,/没有读取权限/);
for(const fault of ['401','429','partial']){change('[data-lab-field="fault"]',fault);await run('integration');}
click('[data-lab="retry-partial"]');
assert.match(document.querySelector('#transcript').textContent,/第二项重试成功/);
for(const name of ['travel','telecom','entertainment'])for(const role of ['buyer','merchant']){
  choose('anthropic',`${name}-${role}`);
  for(const id of [...document.querySelectorAll('#app [data-act="run"]')].map(b=>b.dataset.id))await run(id);
  if(role==='merchant'){click('[data-lab="vertical-approve"]');assert.ok(!document.querySelector('[data-lab="vertical-approve"]'));}
}
choose('anthropic','entertainment-buyer');click('[data-lab="expire"]');
assert.match(document.querySelector('#app').textContent,/保留票：无/);
const input=document.querySelector('#composer-input');input.value='非预设问题';
document.querySelector('#composer').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));
assert.match(document.querySelector('#transcript').textContent,/只回放预设流程/);
assert.equal(networkCalls,0);
console.log('通过：10 个界面、全部预设场景、审批与拒绝、购物车、会话订单、行业操作、事件字段；网络调用 0。');
await window.happyDOM.close();

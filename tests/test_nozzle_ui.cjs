// Interaction smoke test without a camera/browser or third-party dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor() { this.listeners = {}; this.style = {}; this.value = ''; }
  appendChild() {}
  addEventListener(name, handler) { this.listeners[name] = handler; }
  getBoundingClientRect() { return {left:0, top:0, width:1000, height:600}; }
  async fire(name, extra={}) { await this.listeners[name]({currentTarget:this, target:this, ...extra}); }
}
const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const requests = [];
const context = {
  document: {getElementById:get, createElement:() => new Element()},
  updateActuators:() => {}, refresh:() => {},
  postJson:async (url, body) => { requests.push({url,body}); return {ok:true,message:'OK'}; }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/nozzle.js'), 'utf8'), context);
context.updateActuators({frame_size:[640,480], nozzle:{dry_run:true,calibration:{corners:[],water_samples:[]}}});

(async () => {
  await get('nozzle-click').fire('click');
  await get('video').fire('click', {clientX:50,clientY:150});
  assert.equal(requests.length, 0, 'letterbox margins must not move the nozzle');
  await get('video').fire('click', {clientX:300,clientY:150});
  assert.equal(requests[0].url, '/api/nozzle');
  assert.equal(requests[0].body.action, 'aim');
  assert.equal(requests[0].body.u, .25);
  assert.equal(requests[0].body.v, .25);
  await get('nozzle-corners').fire('click');
  assert.equal(requests[1].url, '/api/pump');
  assert.equal(requests[1].body.action, 'stop', 'calibration starts by stopping/disarming');
  console.log('Nozzle UI: click coordinates and calibration stop passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

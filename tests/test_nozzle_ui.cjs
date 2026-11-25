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
const calibration = {
  length_cm:43, width_cm:31, nozzle_x_cm:21.5, nozzle_y_cm:15.5,
  nozzle_height_cm:29, camera_height_cm:36, camera_x_cm:21.5, camera_y_cm:15.5,
  target_height_cm:0, rotation_deg:0, pan_sign:1, tilt_sign:1, anchor_y:.5,
  mechanism:'yaw_pitch', image_aspect:4/3, corners:[], water_samples:[]
};
context.updateActuators({frame_size:[640,480], nozzle:{dry_run:true,calibration}});

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
  await get('nozzle-save').fire('click');
  assert.equal(requests.length, 2, 'incomplete image calibration must not be submitted');
  assert.match(get('nozzle-help').textContent, /0\/4/);

  get('nc-length_cm').value = 30;
  get('nc-width_cm').value = 11;
  await get('nozzle-settings-save').fire('click');
  assert.equal(requests[2].body.action, 'configure');
  assert.equal(requests[2].body.calibration.length_cm, 30);
  assert.equal(requests[2].body.calibration.width_cm, 11);
  assert.equal(requests[2].body.calibration.corners.length, 0);

  // A later status poll must not overwrite a measurement while it is being edited.
  get('nc-width_cm').value = 10;
  context.updateActuators({nozzle:{dry_run:true,calibration}});
  assert.equal(get('nc-width_cm').value, 10);

  context.postJson = async (url, body, button, onError) => {
    onError('Không ghi được file hiệu chuẩn');
    return null;
  };
  await get('nozzle-settings-save').fire('click');
  assert.equal(get('nozzle-help').textContent, 'Không ghi được file hiệu chuẩn');
  context.updateActuators({nozzle:{dry_run:true,calibration}});
  assert.equal(get('nozzle-help').textContent, 'Không ghi được file hiệu chuẩn');
  console.log('Nozzle UI: coordinates, incomplete corners, settings save and persistent errors passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

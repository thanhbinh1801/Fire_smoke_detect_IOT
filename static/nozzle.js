/* Fixed-camera calibration; coordinates account for object-fit: contain. */
(() => {
  const el = id => document.getElementById(id);
  const fields = {
    length_cm: 'Dài sàn (cm)', width_cm: 'Rộng sàn (cm)',
    nozzle_x_cm: 'Vòi X (cm)', nozzle_y_cm: 'Vòi Y (cm)',
    nozzle_height_cm: 'Cao đầu vòi (cm)', camera_height_cm: 'Cao camera (cm)',
    camera_x_cm: 'Camera X (cm)', camera_y_cm: 'Camera Y (cm)',
    target_height_cm: 'Cao mục tiêu (cm)', rotation_deg: 'Hướng lắp trục (°)',
    pan_sign: 'Chiều pan (±1)', tilt_sign: 'Chiều tilt (±1)',
    anchor_y: 'Điểm ngắm trong box (0–1)'
  };
  let calibration = null, frameSize = null, mode = '', corners = [], loaded = false;
  for (const [key, title] of Object.entries(fields)) {
    const label = document.createElement('label');
    label.textContent = title;
    label.style.fontSize = '12px';
    const input = document.createElement('input');
    input.type = 'number'; input.step = 'any'; input.id = `nc-${key}`;
    input.style.cssText = 'display:block;width:100%;box-sizing:border-box';
    label.appendChild(input); el('nozzle-fields').appendChild(label);
  }
  const help = text => { el('nozzle-help').textContent = text; };
  async function send(body) {
    const result = await postJson('/api/nozzle', body, undefined, help);
    if (result) { help(result.message); refresh(); }
    return result;
  }
  function receive(data) {
    frameSize = data.frame_size || frameSize;
    const n = data.nozzle;
    if (!n) return;
    const s = data.servo || {};
    if (s.pan && s.tilt) el('servo-angle').textContent = `${s.pan.angle}° / ${s.tilt.angle}°`;
    el('nozzle-status').textContent = `${n.dry_run ? 'NGẮM KHÔ' : 'CÓ NƯỚC'} · ${n.message} · ${n.calibrated ? 'Đã hiệu chuẩn' : 'Chưa hiệu chuẩn'}`;
    el('nozzle-dry').checked = n.dry_run;
    if (!loaded) {
      calibration = n.calibration;
      corners = calibration.corners.slice();
      for (const key of Object.keys(fields)) el(`nc-${key}`).value = calibration[key];
      el('nozzle-mechanism').value = calibration.mechanism;
      el('nozzle-samples').value = JSON.stringify(calibration.water_samples, null, 2);
      loaded = true;
    }
  }
  // Reuse the dashboard's single status polling loop.
  const originalUpdate = updateActuators;
  updateActuators = function(data) { originalUpdate(data); receive(data); };
  el('nozzle-dry').addEventListener('change', async event => {
    const wanted = event.target.checked;
    event.target.disabled = true;
    const result = await send({action:'dry_run', enabled:wanted});
    if (!result) event.target.checked = !wanted;
    event.target.disabled = false;
  });
  el('nozzle-corners').addEventListener('click', async () => {
    if (!await postJson('/api/pump', {action:'stop'})) return;
    corners = []; mode = 'corners';
    help('Chọn (0,0), tiếp theo đầu cạnh dài, góc đối diện, rồi góc còn lại. Chưa lưu thì hiệu chuẩn cũ vẫn giữ nguyên.');
  });
  el('nozzle-click').addEventListener('click', () => {
    mode = mode === 'aim' ? '' : 'aim';
    el('nozzle-click').textContent = mode === 'aim' ? 'Tắt click để ngắm' : 'Bật click để ngắm';
    help(mode === 'aim' ? 'Bấm vào vùng sàn để ngắm; thao tác này dừng bơm và disarm.' : 'Đã tắt click để ngắm.');
  });
  el('video').addEventListener('click', async event => {
    if (!mode || !frameSize) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const scale = Math.min(rect.width/frameSize[0], rect.height/frameSize[1]);
    const width = frameSize[0]*scale, height = frameSize[1]*scale;
    const u = (event.clientX-rect.left-(rect.width-width)/2)/width;
    const v = (event.clientY-rect.top-(rect.height-height)/2)/height;
    if (u<0 || u>1 || v<0 || v>1) return;
    if (mode === 'corners') {
      corners.push([u,v]);
      help(`Đã chọn ${corners.length}/4 góc: ${corners.map(p => p.map(x => x.toFixed(3)).join(', ')).join(' | ')}`);
      if (corners.length === 4) { mode = ''; help('Đã chọn đủ 4 góc. Kiểm tra thông số, rồi bấm Lưu hiệu chuẩn.'); }
    } else {
      await send({action:'aim',u,v});
    }
  });
  async function save(settingsOnly) {
    try {
      if (!calibration) throw new Error('Chưa nạp được thông số từ máy chủ.');
      const next = {...calibration};
      if (!settingsOnly) {
        if (!frameSize) throw new Error('Chưa có khung hình camera.');
        if (corners.length !== 4) throw new Error(`Đã chọn ${corners.length}/4 góc. Chọn đủ bốn góc, hoặc bấm Lưu thông số và áp dụng để lưu số đo trước.`);
        next.corners = corners;
        next.image_aspect = frameSize[0]/frameSize[1];
      }
      for (const key of Object.keys(fields)) {
        const raw = el(`nc-${key}`).value;
        if (raw === '' || !Number.isFinite(Number(raw))) throw new Error('Điền đầy đủ các thông số dạng số.');
        next[key] = Number(raw);
      }
      next.mechanism = el('nozzle-mechanism').value;
      next.water_samples = JSON.parse(el('nozzle-samples').value);
      if (await send({action:settingsOnly ? 'configure' : 'calibrate',calibration:next})) calibration = next;
    } catch (error) { help(error.message); }
  }
  el('nozzle-settings-save').addEventListener('click', () => save(true));
  el('nozzle-save').addEventListener('click', () => save(false));
})();

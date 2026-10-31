import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from supervisor import StationSupervisor


# Keep ScanManager alias pointing to StationSupervisor for backward compatibility
ScanManager = StationSupervisor


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>SAMI Operator Inspection Station</title>
<style>
  :root {
    --bg: #0b0f17;
    --panel: #131b26;
    --panel-alt: #1b2636;
    --border: #28364d;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --success: #22c55e;
    --success-dark: #052e16;
    --danger: #ef4444;
    --warning: #f59e0b;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* Top Industrial Header */
  header {
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    padding: 14px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
  }
  .station-brand {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .brand-mark {
    width: 40px;
    height: 40px;
    border-radius: 9px;
    background: linear-gradient(135deg, #0284c7, #38bdf8);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    font-size: 1.05rem;
    color: #fff;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.25);
  }
  .station-brand h1 {
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: 0.2px;
  }
  .station-brand p {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 2px;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .heartbeat-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 6px 12px;
    border-radius: 8px;
    font-size: 0.76rem;
    font-weight: 600;
    background: rgba(34, 197, 94, 0.1);
    border: 1px solid rgba(34, 197, 94, 0.35);
    color: #86efac;
  }
  .hb-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #22c55e;
    animation: pulse 1.2s infinite alternate;
  }

  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 8px 18px;
    border-radius: 999px;
    font-size: 0.86rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    background: var(--panel-alt);
    border: 1px solid var(--border);
  }
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--muted);
  }
  .status-pill.idle .status-dot { background: var(--accent); }
  .status-pill.scanning {
    background: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border-color: rgba(245, 158, 11, 0.5);
  }
  .status-pill.scanning .status-dot {
    background: #fbbf24;
    box-shadow: 0 0 10px #fbbf24;
    animation: pulse 1s infinite alternate;
  }
  .status-pill.completed {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
    border-color: rgba(34, 197, 94, 0.5);
  }
  .status-pill.completed .status-dot { background: #22c55e; }
  .status-pill.error, .status-pill.stopped {
    background: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border-color: rgba(239, 68, 68, 0.5);
  }
  .status-pill.error .status-dot, .status-pill.stopped .status-dot { background: #ef4444; }

  @keyframes pulse {
    from { opacity: 0.4; transform: scale(0.9); }
    to   { opacity: 1.0; transform: scale(1.2); }
  }

  /* Hardware & Backend Connection Feedback Bar */
  .conn-bar {
    background: #0e1520;
    border-bottom: 1px solid var(--border);
    padding: 10px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    flex-wrap: wrap;
  }
  .conn-grid {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    flex: 1;
  }
  .conn-item {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 14px;
    min-width: 195px;
  }
  .conn-led {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--muted);
    flex-shrink: 0;
  }
  .conn-item.CONNECTED .conn-led {
    background: var(--success);
    box-shadow: 0 0 8px rgba(34, 197, 94, 0.7);
  }
  .conn-item.SIMULATED .conn-led, .conn-item.CONNECTING .conn-led {
    background: var(--warning);
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.7);
  }
  .conn-item.OFFLINE .conn-led {
    background: var(--danger);
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.6);
  }
  .conn-label {
    font-size: 0.74rem;
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }
  .conn-state {
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--text);
  }
  .conn-item.CONNECTED .conn-state { color: #4ade80; }
  .conn-item.SIMULATED .conn-state, .conn-item.CONNECTING .conn-state { color: #fbbf24; }
  .conn-item.OFFLINE .conn-state { color: #f87171; }
  .conn-sub {
    font-size: 0.7rem;
    color: var(--muted);
    margin-left: 4px;
    font-weight: 400;
  }

  /* Main Operator Layout */
  .operator-grid {
    display: grid;
    grid-template-columns: 420px 1fr;
    gap: 20px;
    padding: 20px 28px;
    flex: 1;
  }
  @media (max-width: 1080px) {
    .operator-grid { grid-template-columns: 1fr; }
  }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 18px;
  }
  .card-title {
    font-size: 0.82rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  /* Part Selector */
  .part-select {
    width: 100%;
    padding: 13px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 1.02rem;
    font-weight: 600;
    margin-bottom: 16px;
    cursor: pointer;
  }
  .part-select:focus {
    outline: none;
    border-color: var(--accent);
  }

  /* Big Operator Action Buttons */
  .action-buttons {
    display: grid;
    grid-template-columns: 1fr 120px;
    gap: 12px;
    margin-bottom: 14px;
  }
  button {
    cursor: pointer;
    border: none;
    border-radius: 9px;
    font-weight: 700;
    transition: all 0.15s ease;
  }
  button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .btn-start {
    background: var(--success);
    color: var(--success-dark);
    font-size: 1.05rem;
    padding: 16px 20px;
    letter-spacing: 0.4px;
    box-shadow: 0 4px 16px rgba(34, 197, 94, 0.25);
  }
  .btn-start:hover:not(:disabled) {
    filter: brightness(1.08);
    transform: translateY(-1px);
  }
  .btn-stop {
    background: var(--danger);
    color: #fff;
    font-size: 1rem;
    padding: 16px 14px;
    letter-spacing: 0.4px;
  }
  .btn-stop:hover:not(:disabled) {
    filter: brightness(1.1);
  }
  .btn-small {
    background: var(--panel-alt);
    color: var(--text);
    border: 1px solid var(--border);
    padding: 6px 12px;
    font-size: 0.78rem;
    border-radius: 6px;
  }
  .btn-small:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }

  .sim-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.82rem;
    color: var(--muted);
    padding-top: 6px;
    cursor: pointer;
  }
  .sim-row input {
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  /* Cycle Progress Tracker */
  .progress-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin-top: 14px;
  }
  .progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.86rem;
    font-weight: 600;
    margin-bottom: 8px;
  }
  .progress-bar-track {
    width: 100%;
    height: 10px;
    background: var(--panel-alt);
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 12px;
  }
  .progress-bar-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #0ea5e9, #22c55e);
    transition: width 0.3s ease;
  }
  .step-pills {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
  }
  .step-pill {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 7px 6px;
    font-size: 0.72rem;
    text-align: center;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .step-pill.capture {
    border-color: rgba(56, 189, 248, 0.35);
    color: #cbd5e1;
  }
  .step-pill.active {
    background: rgba(245, 158, 11, 0.2);
    border-color: var(--warning);
    color: #fde68a;
    font-weight: 700;
  }
  .step-pill.done {
    background: rgba(34, 197, 94, 0.14);
    border-color: rgba(34, 197, 94, 0.55);
    color: #86efac;
  }

  /* Captured Images List */
  .image-list {
    max-height: 360px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .image-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.14s ease;
  }
  .image-card:hover {
    border-color: var(--accent);
    background: rgba(56, 189, 248, 0.06);
  }
  .image-card.active {
    border-color: var(--accent);
    background: rgba(56, 189, 248, 0.15);
    box-shadow: inset 3px 0 0 var(--accent);
  }
  .thumb {
    width: 64px;
    height: 46px;
    border-radius: 5px;
    object-fit: cover;
    background: #06090e;
    border: 1px solid var(--border);
    flex-shrink: 0;
  }
  .image-info {
    flex: 1;
    min-width: 0;
  }
  .image-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 3px;
  }
  .cam-tag {
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(56, 189, 248, 0.18);
    color: var(--accent);
    text-transform: uppercase;
  }
  .part-tag {
    font-size: 0.84rem;
    font-weight: 600;
    color: var(--text);
  }
  .image-time {
    font-size: 0.76rem;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Right Column: Main Inspection Viewer */
  .viewer-panel {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 170px);
    min-height: 550px;
    margin-bottom: 0;
  }
  .viewer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
    flex-wrap: wrap;
    gap: 10px;
  }
  .viewer-title-group h2 {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text);
  }
  .viewer-title-group p {
    font-size: 0.82rem;
    color: var(--accent);
    margin-top: 2px;
  }
  .viewer-stage {
    flex: 1;
    background: #06090e;
    border: 1px solid var(--border);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    position: relative;
  }
  .viewer-stage img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }
  .viewer-empty {
    text-align: center;
    color: var(--muted);
    padding: 32px;
    max-width: 440px;
  }
  .viewer-empty h3 {
    font-size: 1.05rem;
    color: var(--text);
    margin-bottom: 8px;
  }
  .viewer-empty p {
    font-size: 0.88rem;
    line-height: 1.5;
  }

  .status-footer {
    margin-top: 12px;
    padding: 10px 14px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 0.82rem;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }
</style>
</head>
<body>

<header>
  <div class="station-brand">
    <div class="brand-mark">S</div>
    <div>
      <h1>SAMI Automated Visual Inspection Station</h1>
      <p>Load 1 Pick &rarr; Camera 1 &amp; Camera 2 Inspection &rarr; Return to Load 1</p>
    </div>
  </div>
  <div class="header-right">
    <div id="statusBadge" class="status-pill idle">
      <span class="status-dot"></span>
      <span id="statusText">READY</span>
    </div>
  </div>
</header>

<!-- Live Connection Feedback Bar (Supervisor + Cobot + Relay Lights + Camera) -->
<div class="conn-bar">
  <div class="conn-grid">
    <div id="connCard_backend" class="conn-item CONNECTED">
      <span class="conn-led"></span>
      <div>
        <div class="conn-label">Backend Supervisor</div>
        <div class="conn-state" id="connState_backend">CONNECTED <span class="conn-sub" id="connSub_backend"></span></div>
      </div>
    </div>

    <div id="connCard_cobot" class="conn-item CHECKING">
      <span class="conn-led"></span>
      <div>
        <div class="conn-label">Fairino Cobot</div>
        <div class="conn-state" id="connState_cobot">CHECKING...</div>
      </div>
    </div>

    <div id="connCard_relay" class="conn-item CHECKING">
      <span class="conn-led"></span>
      <div>
        <div class="conn-label">Relay Lights</div>
        <div class="conn-state" id="connState_relay">CHECKING...</div>
      </div>
    </div>

    <div id="connCard_camera" class="conn-item CHECKING">
      <span class="conn-led"></span>
      <div>
        <div class="conn-label">Inspection Camera</div>
        <div class="conn-state" id="connState_camera">CHECKING...</div>
      </div>
    </div>
  </div>

  <button class="btn-small" onclick="checkConnections()">Check Connections</button>
</div>

<div class="operator-grid">
  <!-- Left Column: Operator Controls & Captured Images -->
  <div>
    <div class="card">
      <div class="card-title">
        <span>1. Select Part &amp; Start Inspection</span>
      </div>

      <select id="objectSelect" class="part-select" aria-label="Select Part to Inspect"></select>

      <div class="action-buttons">
        <button id="startScanBtn" class="btn-start" onclick="startScan()">START INSPECTION</button>
        <button id="stopScanBtn" class="btn-stop" onclick="stopScan()" disabled>STOP</button>
      </div>

      <label class="sim-row">
        <input type="checkbox" id="simulateToggle" />
        <span>Test / Simulation Mode (run without hardware)</span>
      </label>

      <!-- Live Cycle Progress -->
      <div class="progress-box">
        <div class="progress-header">
          <span id="cycleStageLabel">Station Ready at Load 1</span>
          <span id="cycleStepCounter" style="color:var(--accent);">0 / 8</span>
        </div>
        <div class="progress-bar-track">
          <div id="progressBarFill" class="progress-bar-fill"></div>
        </div>
        <div id="stepPillsContainer" class="step-pills"></div>
      </div>
    </div>

    <!-- Captured Images List -->
    <div class="card" style="margin-bottom:0;">
      <div class="card-title">
        <span>2. Inspection Captures (<span id="imageCount">0</span>)</span>
        <button class="btn-small" onclick="loadImages()">Refresh</button>
      </div>
      <div id="imageList" class="image-list">
        <div style="padding:18px; text-align:center; color:var(--muted); font-size:0.88rem;">
          No inspection images captured for this part yet.
        </div>
      </div>
    </div>
  </div>

  <!-- Right Column: Large Inspection Image Viewer -->
  <div class="card viewer-panel">
    <div class="viewer-header">
      <div class="viewer-title-group">
        <h2 id="viewerTitle">Inspection Image Viewer</h2>
        <p id="viewerMeta">Select an image from the left or start an inspection cycle</p>
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn-small" onclick="navigateImage(-1)">&larr; Previous</button>
        <button class="btn-small" onclick="navigateImage(1)">Next &rarr;</button>
      </div>
    </div>

    <div class="viewer-stage">
      <div id="viewerPlaceholder" class="viewer-empty">
        <h3>Ready for Inspection</h3>
        <p>Place the part in <b>Load 1</b>, choose the part type on the left, and press <b>START INSPECTION</b>.</p>
      </div>
      <img id="previewImage" style="display:none;" alt="Inspection Capture" />
    </div>

    <div class="status-footer">
      <span id="latestLogLine">Supervisor &amp; Orchestrator initialized and ready.</span>
      <span id="activePartFooter" style="color:var(--text); font-weight:600;"></span>
    </div>
  </div>
</div>

<script>
  let objectsData = [];
  let currentImages = [];
  let selectedImageRelPath = null;
  let lastAutoSelectedImage = null;
  let lastState = {};

  async function init() {
    await loadObjects();
    await loadImages();
    await pollState();
    setInterval(pollState, 800);
  }

  async function loadObjects() {
    const res = await fetch('/api/objects');
    const data = await res.json();
    objectsData = data.objects || [];
    const sel = document.getElementById('objectSelect');
    const previous = sel.value;
    sel.innerHTML = '';

    objectsData.forEach(obj => {
      const opt = document.createElement('option');
      opt.value = obj.config_file;
      opt.textContent = `Part: ${obj.object_name}`;
      sel.appendChild(opt);
    });

    if (previous && objectsData.some(o => o.config_file === previous)) {
      sel.value = previous;
    }

    sel.onchange = () => onObjectChanged();
    onObjectChanged();
  }

  function getSelectedObject() {
    const val = document.getElementById('objectSelect').value;
    return objectsData.find(o => o.config_file === val) || null;
  }

  function onObjectChanged() {
    const obj = getSelectedObject();
    document.getElementById('activePartFooter').textContent = obj ? `Active Part: ${obj.object_name}` : '';
    renderStepPills(0, false);
    loadImages();
  }

  function renderStepPills(currentStep, running) {
    const obj = getSelectedObject();
    const box = document.getElementById('stepPillsContainer');
    if (!obj || !obj.steps) {
      box.innerHTML = '';
      return;
    }

    box.innerHTML = obj.steps.map(s => {
      let cls = 'step-pill';
      if (s.capture) cls += ' capture';
      if (running && s.step === currentStep) {
        cls += ' active';
      } else if ((running && s.step < currentStep) || (!running && lastState.status === 'completed')) {
        cls += ' done';
      }
      const shortLabel = s.label
        .replace(/Safe Waypoint\\s*/i, 'Safe ')
        .replace(/\\s*\\(.*?\\)/g, '');
      return `<div class="${cls}" title="Step ${s.step}: ${s.label}">${s.step}. ${shortLabel}</div>`;
    }).join('');
  }

  async function startScan() {
    const obj = getSelectedObject();
    if (!obj) return;
    const simulate = document.getElementById('simulateToggle').checked;

    const res = await fetch('/api/scan/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        config_file: obj.config_file,
        simulate: simulate
      })
    });
    const out = await res.json();
    if (!res.ok) {
      alert(out.error || 'Unable to start inspection');
    }
    await pollState();
  }

  async function stopScan() {
    await fetch('/api/scan/stop', { method: 'POST' });
    await pollState();
  }

  async function loadImages() {
    const obj = getSelectedObject();
    const cfgParam = obj ? encodeURIComponent(obj.config_file) : '__all__';
    const res = await fetch(`/api/images?config_file=${cfgParam}`);
    const data = await res.json();
    currentImages = data.images || [];

    document.getElementById('imageCount').textContent = currentImages.length;
    const listEl = document.getElementById('imageList');

    if (currentImages.length === 0) {
      listEl.innerHTML = `
        <div style="padding:18px; text-align:center; color:var(--muted); font-size:0.88rem;">
          No inspection images captured for this part yet.
        </div>`;
      return;
    }

    listEl.innerHTML = currentImages.map((img, idx) => {
      const isSelected = img.rel_path === selectedImageRelPath;
      return `
        <div class="image-card ${isSelected ? 'active' : ''}" onclick="selectImageByIndex(${idx})">
          <img class="thumb" src="/api/image?path=${encodeURIComponent(img.rel_path)}" alt="${img.camera_label}" loading="lazy" />
          <div class="image-info">
            <div class="image-top">
              <span class="cam-tag">${img.camera_label}</span>
              <span class="part-tag">${img.object_name}</span>
            </div>
            <div class="image-time">${img.timestamp}</div>
          </div>
        </div>
      `;
    }).join('');
  }

  function selectImageByIndex(idx) {
    if (idx < 0 || idx >= currentImages.length) return;
    const img = currentImages[idx];
    selectedImageRelPath = img.rel_path;

    const imgEl = document.getElementById('previewImage');
    const placeholder = document.getElementById('viewerPlaceholder');

    imgEl.src = `/api/image?path=${encodeURIComponent(img.rel_path)}&t=${Date.now()}`;
    imgEl.style.display = 'block';
    placeholder.style.display = 'none';

    document.getElementById('viewerTitle').textContent = `${img.object_name} — ${img.camera_label}`;
    document.getElementById('viewerMeta').textContent = `Captured at ${img.timestamp} (${img.filename})`;

    loadImages();
  }

  function navigateImage(direction) {
    if (currentImages.length === 0) return;
    const currentIndex = currentImages.findIndex(i => i.rel_path === selectedImageRelPath);
    let nextIndex = currentIndex === -1 ? 0 : currentIndex + direction;
    if (nextIndex < 0) nextIndex = currentImages.length - 1;
    if (nextIndex >= currentImages.length) nextIndex = 0;
    selectImageByIndex(nextIndex);
  }

  function updateConnectionCards(conns, lastHeartbeat, lastStepMs) {
    const simChecked = document.getElementById('simulateToggle').checked;
    const devices = ['backend', 'cobot', 'relay', 'camera'];

    devices.forEach(dev => {
      const card = document.getElementById(`connCard_${dev}`);
      const stateEl = document.getElementById(`connState_${dev}`);
      if (!card || !stateEl) return;

      const info = (conns && conns[dev]) || { status: 'CHECKING', detail: '' };
      let st = info.status || 'CHECKING';

      // If Simulation Mode checkbox is enabled and physical hardware is OFFLINE, show SIMULATED ready state
      if (dev !== 'backend' && simChecked && st === 'OFFLINE') {
        st = 'SIMULATED';
      }

      card.className = `conn-item ${st}`;

      if (dev === 'backend') {
        const subText = lastHeartbeat ? `• ${lastHeartbeat}${lastStepMs ? ' (' + lastStepMs + 'ms)' : ''}` : '';
        stateEl.innerHTML = `${st} <span class="conn-sub">${subText}</span>`;
      } else {
        const detailText = st === 'SIMULATED' ? 'Simulation Ready' : (info.detail || '');
        stateEl.innerHTML = `${st} <span class="conn-sub">${detailText ? '• ' + detailText : ''}</span>`;
      }
    });
  }

  async function checkConnections() {
    const obj = getSelectedObject();
    const cfg = obj ? obj.config_file : 'dowel.yaml';
    await fetch('/api/connections/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config_file: cfg })
    });
    await pollState();
  }

  document.getElementById('simulateToggle').addEventListener('change', () => {
    if (lastState && lastState.connections) {
      updateConnectionCards(lastState.connections, lastState.last_heartbeat, lastState.last_step_duration_ms);
    }
  });

  async function pollState() {
    try {
      const res = await fetch('/api/status');
      const state = await res.json();
      lastState = state;

      const startBtn = document.getElementById('startScanBtn');
      const stopBtn = document.getElementById('stopScanBtn');
      const selectEl = document.getElementById('objectSelect');
      const badge = document.getElementById('statusBadge');
      const statusText = document.getElementById('statusText');

      startBtn.disabled = state.running;
      stopBtn.disabled = !state.running;
      selectEl.disabled = state.running;

      updateConnectionCards(state.connections, state.last_heartbeat, state.last_step_duration_ms);

      badge.className = 'status-pill ' + (state.status || 'idle');
      if (state.running) {
        statusText.textContent = 'INSPECTING PART';
      } else if (state.status === 'completed') {
        statusText.textContent = 'CYCLE COMPLETE';
      } else if (state.status === 'error') {
        statusText.textContent = 'STATION FAULT';
      } else if (state.status === 'stopped') {
        statusText.textContent = 'STOPPED';
      } else {
        statusText.textContent = 'READY';
      }

      const obj = getSelectedObject();
      const total = state.total_steps || (obj ? obj.total_steps : 8);
      const step = state.running ? state.current_step : (state.status === 'completed' ? total : 0);
      const pct = total > 0 ? Math.round((step / total) * 100) : 0;

      document.getElementById('cycleStepCounter').textContent = `${step} / ${total}`;
      document.getElementById('progressBarFill').style.width = `${pct}%`;
      document.getElementById('cycleStageLabel').textContent =
        state.current_label || (state.running ? 'Moving cobot...' : 'Station Ready at Load 1');

      renderStepPills(step, state.running);

      if (state.logs && state.logs.length > 0) {
        document.getElementById('latestLogLine').textContent = state.logs[state.logs.length - 1];
      }

      if (state.last_image && state.last_image !== lastAutoSelectedImage) {
        lastAutoSelectedImage = state.last_image;
        await loadImages();
        const idx = currentImages.findIndex(i => i.rel_path === state.last_image);
        if (idx !== -1) {
          selectImageByIndex(idx);
        }
      }
    } catch (e) {
      updateConnectionCards({
        backend: { status: 'OFFLINE', detail: 'Server unreachable' },
        cobot: { status: 'OFFLINE', detail: '' },
        relay: { status: 'OFFLINE', detail: '' },
        camera: { status: 'OFFLINE', detail: '' }
      }, '', null);
    }
  }

  init();
</script>
</body>
</html>
"""


class InspectionUIRequestHandler(BaseHTTPRequestHandler):
    supervisor = StationSupervisor()

    def log_message(self, format, *args):
        pass

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/objects":
            self._send_json({"objects": self.supervisor.list_objects()})
            return

        if path == "/api/status":
            self._send_json(self.supervisor.get_state())
            return

        if path == "/api/images":
            cfg = query.get("config_file", [None])[0]
            self._send_json({"images": self.supervisor.list_images(cfg)})
            return

        if path == "/api/image":
            rel_path = unquote(query.get("path", [""])[0])
            full_path = os.path.abspath(
                os.path.join(self.supervisor.base_dir, rel_path)
            )
            if (
                not full_path.startswith(self.supervisor.base_dir)
                or not os.path.isfile(full_path)
            ):
                self._send_json(
                    {"error": "Image not found"}, status=HTTPStatus.NOT_FOUND
                )
                return

            ctype, _ = mimetypes.guess_type(full_path)
            with open(full_path, "rb") as f:
                data = f.read()

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype or "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except Exception as exc:
            self._send_json(
                {"error": f"Invalid JSON: {exc}"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if path == "/api/scan/start":
            config_file = body.get("config_file", "dowel.yaml")
            simulate = bool(body.get("simulate", False))
            try:
                self.supervisor.start_scan(
                    config_filename=config_file,
                    simulate=simulate,
                )
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json(
                    {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST
                )
            return

        if path == "/api/scan/stop":
            stopped = self.supervisor.stop_scan()
            self._send_json({"ok": stopped})
            return

        if path == "/api/connections/check":
            config_file = body.get("config_file", "dowel.yaml")
            self.supervisor.probe_network_devices(config_file)
            self._send_json(self.supervisor.get_state())
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)


def run_server(host="0.0.0.0", port=8080):
    server = ThreadingHTTPServer((host, port), InspectionUIRequestHandler)
    print(f"SAMI Operator Web UI running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SAMI Operator Inspection Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)

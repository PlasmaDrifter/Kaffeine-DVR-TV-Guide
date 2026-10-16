"""
HTML, CSS, and Vanilla JavaScript single-page application for Kaffeine DVR remote web companion.
Embedded as a clean, dependency-free template string.
"""

WEB_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Kaffeine DVR Web Companion</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon.png">
  <link rel="shortcut icon" href="/favicon.ico">
  <style>
    :root {
      --bg-dark: #0f131a;
      --card-bg: #1a202c;
      --card-border: #2d3748;
      --text-main: #e2e8f0;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --danger: #ef4444;
      --danger-hover: #dc2626;
      --success: #22c55e;
      --warning: #f59e0b;
      --header-bg: #141a24;
    }
    html { font-size: 19.2px; }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; }
    body { background-color: var(--bg-dark); color: var(--text-main); min-height: 100vh; display: flex; flex-direction: column; }

    header { background-color: var(--header-bg); border-bottom: 1px solid var(--card-border); padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.15rem; color: #fff; }
    .brand-badge { background: #0284c7; color: #fff; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; font-weight: bold; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 0.82rem; color: var(--text-muted); background: #1f2937; padding: 4px 10px; border-radius: 9999px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); }

    nav { display: flex; gap: 8px; }
    .nav-btn { background: transparent; border: 1px solid var(--card-border); color: var(--text-main); padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 0.9rem; font-weight: 500; transition: all 0.15s; }
    .nav-btn:hover { background: #2d3748; }
    .nav-btn.active { background: #0284c7; border-color: #0284c7; color: #fff; }

    main { flex: 1; padding: 18px 20px; max-width: 100%; width: 100%; margin: 0 auto; }

    .view-panel { display: none; }
    .view-panel.active { display: block; }

    .toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; background: var(--card-bg); padding: 12px 16px; border-radius: 8px; border: 1px solid var(--card-border); }
    .toolbar-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    select, input[type="text"], input[type="password"] { background: #111827; border: 1px solid #374151; color: #fff; padding: 7px 12px; border-radius: 6px; font-size: 0.9rem; outline: none; }
    select:focus, input:focus { border-color: var(--accent); }

    .btn { background: #0284c7; color: #fff; border: none; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 0.88rem; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; transition: background 0.15s; }
    .btn:hover { background: var(--accent-hover); }
    .btn-secondary { background: #374151; color: #d1d5db; }
    .btn-secondary:hover { background: #4b5563; color: #fff; }
    .btn-danger { background: var(--danger); }
    .btn-danger:hover { background: var(--danger-hover); }
    .btn-sm { padding: 4px 10px; font-size: 0.8rem; }

    .view-mode-toggle { display: inline-flex; border: 1px solid var(--card-border); border-radius: 6px; overflow: hidden; }
    .view-mode-toggle button { border: none; border-radius: 0; background: #1e2638; color: var(--text-muted); cursor: pointer; padding: 5px 12px; font-size: 0.82rem; font-weight: 600; transition: background 0.15s; }
    .view-mode-toggle button:hover { background: #2d3748; color: #fff; }
    .view-mode-toggle button.active { background: #0284c7; color: #fff; }

    .grid-table { width: 100%; border-collapse: collapse; margin-top: 8px; background: var(--card-bg); border-radius: 8px; overflow: hidden; border: 1px solid var(--card-border); }
    .grid-table th { background: #141a24; padding: 10px 14px; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); border-bottom: 1px solid var(--card-border); }
    .grid-table td { padding: 12px 14px; border-bottom: 1px solid #232b38; font-size: 0.9rem; vertical-align: middle; }
    .grid-table tr:hover { background: #202836; }

    /* Compact List View Table */
    .compact-table th { padding: 5px 8px; font-size: 0.72rem; }
    .compact-table td { padding: 4px 8px; font-size: 0.8rem; line-height: 1.2; }

    /* EPG Grid Styles with Anchored Left Channels and Grab / Pan */
    .epg-wrapper {
      position: relative;
      width: 100%;
      display: flex;
      max-height: calc(100vh - 210px);
      min-height: 480px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      overflow: hidden;
      box-sizing: border-box;
    }
    .epg-channels-col {
      width: 120px;
      min-width: 120px;
      max-width: 120px;
      flex-shrink: 0;
      display: flex;
      flex-direction: column;
      background: #141a24;
      border-right: 2px solid var(--card-border);
      z-index: 30;
      user-select: none;
    }
    .epg-corner-header {
      height: 32px;
      min-height: 32px;
      box-sizing: border-box;
      background: #111620;
      border-bottom: 2px solid var(--card-border);
      padding: 6px 8px;
      font-size: 0.74rem;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--text-muted);
      display: flex;
      align-items: center;
    }
    .epg-channel-list {
      flex: 1;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .epg-channel-cell {
      height: 46px;
      min-height: 46px;
      max-height: 46px;
      box-sizing: border-box;
      padding: 4px 8px;
      border-bottom: 1px solid #232b38;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    .epg-channel-name {
      font-weight: 700;
      font-size: 0.8rem;
      color: #fff;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .epg-timeline-pane {
      flex: 1;
      min-width: 0;
      overflow-x: auto;
      overflow-y: auto;
      position: relative;
      cursor: grab;
      user-select: none;
      -webkit-user-select: none;
    }
    .epg-timeline-pane.grabbing {
      cursor: grabbing;
    }
    .epg-timeline-pane.grabbing * {
      cursor: grabbing !important;
    }
    .epg-timeline-header {
      position: sticky;
      top: 0;
      z-index: 25;
      background: #141a24;
      border-bottom: 2px solid var(--card-border);
      height: 32px;
      min-height: 32px;
      display: flex;
    }
    .epg-time-slot {
      width: 150px;
      min-width: 150px;
      height: 32px;
      line-height: 32px;
      padding: 0 8px;
      font-size: 0.74rem;
      font-weight: 600;
      color: var(--text-muted);
      border-right: 1px solid #283244;
      box-sizing: border-box;
      white-space: nowrap;
    }
    .epg-timeline-body {
      position: relative;
    }
    .epg-row {
      height: 46px;
      min-height: 46px;
      max-height: 46px;
      box-sizing: border-box;
      position: relative;
      border-bottom: 1px solid #232b38;
    }
    .epg-row:hover {
      background: rgba(255, 255, 255, 0.02);
    }
    .epg-program-tile {
      position: absolute;
      top: 3px;
      bottom: 3px;
      box-sizing: border-box;
      background: #1e2638;
      border: 1px solid #334155;
      border-radius: 4px;
      padding: 3px 6px;
      cursor: pointer;
      overflow: hidden;
      transition: background 0.15s, border-color 0.15s;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    .epg-program-tile:hover {
      background: #2a354c;
      border-color: var(--accent);
      z-index: 10;
    }
    .epg-program-tile.scheduled {
      border-left: 3px solid #ef4444;
      background: #2b1f2e;
    }
    .epg-program-tile.airing-now {
      border-color: #38bdf8;
    }
    .epg-rec-dot {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #ef4444;
      margin-right: 4px;
      vertical-align: middle;
    }
    .epg-tile-title {
      font-size: 0.76rem;
      font-weight: 600;
      color: #f1f5f9;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      line-height: 1.2;
    }
    .epg-tile-time {
      font-size: 0.66rem;
      color: var(--text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-top: 2px;
      line-height: 1;
    }
    .epg-now-line {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      background: #ef4444;
      opacity: 0.3;
      z-index: 20;
      pointer-events: none;
    }

    .badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: bold; text-transform: uppercase; }
    .badge-recording { background: #ef4444; color: #fff; }
    .badge-armed { background: #f59e0b; color: #000; }
    .badge-completed { background: #22c55e; color: #fff; }
    .badge-queued { background: #3b82f6; color: #fff; }

    /* Video modal */
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(4px); z-index: 100; align-items: center; justify-content: center; padding: 16px; }
    .modal-overlay.active { display: flex; }
    .modal-card { background: #111827; border: 1px solid #374151; border-radius: 10px; width: 100%; max-width: 900px; overflow: hidden; display: flex; flex-direction: column; }
    .modal-header { padding: 12px 18px; background: #1f2937; display: flex; justify-content: space-between; align-items: center; }
    .modal-title { font-weight: 600; font-size: 1.05rem; }
    .modal-close { background: transparent; border: none; color: #9ca3af; font-size: 1.3rem; cursor: pointer; }
    .modal-close:hover { color: #fff; }
    .video-wrapper { position: relative; width: 100%; background: #000; padding-top: 56.25%; /* 16:9 */ }
    .video-wrapper video { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }

    /* Login overlay */
    .login-overlay { display: none; position: fixed; inset: 0; background: #0a0e14; z-index: 200; align-items: center; justify-content: center; }
    .login-overlay.active { display: flex; }
    .login-box { background: var(--card-bg); border: 1px solid var(--card-border); padding: 28px; border-radius: 10px; width: 100%; max-width: 360px; text-align: center; }
    .login-box h2 { margin-bottom: 16px; font-size: 1.25rem; }
    .login-box input { width: 100%; margin-bottom: 16px; }
    .login-box .btn { width: 100%; justify-content: center; }
    .login-error { color: var(--danger); font-size: 0.85rem; margin-top: 10px; display: none; }

    @media (max-width: 640px) {
      header { flex-direction: column; align-items: stretch; }
      nav { justify-content: space-around; width: 100%; }
      .nav-btn { flex: 1; text-align: center; }
      .toolbar { flex-direction: column; align-items: stretch; }
      .toolbar-group { width: 100%; justify-content: space-between; }
    }
  </style>
</head>
<body>

  <!-- Login Overlay -->
  <div id="loginOverlay" class="login-overlay">
    <div class="login-box">
      <h2>Kaffeine DVR</h2>
      <p style="color: var(--text-muted); font-size: 0.88rem; margin-bottom: 16px;">Authentication Required</p>
      <input type="password" id="loginPassInput" placeholder="Enter Access Password" onkeydown="if(event.key==='Enter') doLogin()">
      <button class="btn" onclick="doLogin()">Unlock DVR Access</button>
      <div id="loginError" class="login-error">Incorrect password. Please try again.</div>
    </div>
  </div>

  <!-- Header -->
  <header>
    <div class="brand">
      <span>Kaffeine DVR</span>
      <span class="brand-badge">Companion</span>
    </div>
    <div class="status-badge">
      <span class="status-dot"></span>
      <span id="diskStatusText">Storage: Checking...</span>
    </div>
    <nav>
      <button class="nav-btn active" onclick="switchTab('guide')">TV Guide</button>
      <button class="nav-btn" onclick="switchTab('recordings')">Recordings & Player</button>
    </nav>
  </header>

  <!-- Main View Area -->
  <main>
    <!-- TV Guide View -->
    <div id="guideView" class="view-panel active">
      <div class="toolbar">
        <div class="toolbar-group">
          <label style="font-size: 0.85rem; color: var(--text-muted);">Broadcast Date:</label>
          <select id="guideDateSelect" onchange="loadGuide()"></select>
          <button class="btn btn-sm" onclick="loadGuide()">Refresh Listings</button>
          <div class="view-mode-toggle">
            <button id="viewGridBtn" class="active" onclick="setGuideViewMode('grid')">Grid View</button>
            <button id="viewListBtn" onclick="setGuideViewMode('list')">List View</button>
          </div>
          <button id="jumpNowBtn" class="btn btn-sm btn-secondary" onclick="scrollToCurrentTime()">Jump to Now</button>
        </div>
        <div class="toolbar-group">
          <label style="font-size: 0.82rem; color: var(--text-muted);">Channel:</label>
          <select id="guideChannelSelect" onchange="renderGuide()">
            <option value="All">All Channels</option>
          </select>
          <label id="trimPassedWrapper" style="font-size: 0.82rem; color: var(--text-muted); display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;">
            <input type="checkbox" id="trimPassedCheckbox" checked onchange="renderGuide()"> Trim Passed Shows
          </label>
          <input type="text" id="guideSearchInput" placeholder="Filter by show or channel..." oninput="renderGuide()">
        </div>
      </div>

      <!-- EPG Grid View Container -->
      <div id="guideGridContainer" style="display: block;">
        <div id="epgGridWrapper" class="epg-wrapper">
          <div id="epgEmptyNotice" style="display: none; text-align: center; color: var(--text-muted); padding: 40px; width: 100%;">
            Loading TV Guide Grid...
          </div>
          <div id="epgGridContent" style="display: flex; width: 100%; height: 100%; overflow: hidden;">
            <div class="epg-channels-col">
              <div class="epg-corner-header">Channel</div>
              <div class="epg-channel-list" id="epgChannelList"></div>
            </div>
            <div class="epg-timeline-pane" id="epgTimelinePane">
              <div class="epg-timeline-header" id="epgTimelineHeader" style="width: 8400px;"></div>
              <div class="epg-timeline-body" id="epgTimelineBody" style="width: 8400px;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- List View Container -->
      <div id="guideListContainer" style="display: none;">
        <table class="grid-table compact-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Channel</th>
              <th>Program Title</th>
              <th>Duration</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody id="guideTableBody">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 30px;">Loading TV Guide listings...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Recordings View -->
    <div id="recordingsView" class="view-panel">
      <div class="toolbar">
        <div class="toolbar-group">
          <button class="btn btn-sm" onclick="loadRecordings()">Refresh Recordings</button>
        </div>
        <div class="toolbar-group">
          <span id="activeRecSummary" style="font-size: 0.85rem; color: var(--text-muted);">Active Schedule & Completed History</span>
        </div>
      </div>

      <table class="grid-table">
        <thead>
          <tr>
            <th>Play / Watch</th>
            <th>Title</th>
            <th>Channel</th>
            <th>Recorded At</th>
            <th>Status / Size</th>
            <th style="text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody id="recordingsTableBody">
          <tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">Loading recordings...</td></tr>
        </tbody>
      </table>
    </div>
  </main>

  <!-- Program Details Modal -->
  <div id="programModal" class="modal-overlay" onclick="closeProgramModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()" style="max-width: 520px;">
      <div class="modal-header">
        <span id="progModalTitle" class="modal-title">Program Details</span>
        <button class="modal-close" onclick="closeProgramModal()">&times;</button>
      </div>
      <div style="padding: 18px 20px;">
        <div id="progModalSubtitle" style="font-size: 0.95rem; font-weight: 600; color: var(--accent); margin-bottom: 8px;"></div>
        <div id="progModalMeta" style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 12px;"></div>
        <div id="progModalSummary" style="font-size: 0.88rem; line-height: 1.5; color: #cbd5e1; max-height: 200px; overflow-y: auto; margin-bottom: 20px; background: #0f131a; padding: 12px; border-radius: 6px; border: 1px solid var(--card-border);"></div>
        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-secondary" onclick="closeProgramModal()">Close</button>
          <button id="progModalActionBtn" class="btn" onclick="handleProgModalAction()">Schedule Recording</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Video Playback Modal -->
  <div id="videoModal" class="modal-overlay" onclick="closeVideoModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <span id="videoModalTitle" class="modal-title">Watch Recording</span>
        <div style="display: flex; align-items: center; gap: 10px;">
          <a id="videoDownloadLink" class="btn btn-sm" href="#" download style="text-decoration: none;">Download File</a>
          <button class="modal-close" onclick="closeVideoModal()">&times;</button>
        </div>
      </div>
      <div class="video-wrapper">
        <video id="html5VideoPlayer" controls autoplay preload="metadata">
          Your browser does not support HTML5 video playback.
        </video>
      </div>
    </div>
  </div>

  <script>
    let authToken = localStorage.getItem("kaffeine_web_token") || "";
    let guideItems = [];
    let currentGuideViewMode = localStorage.getItem("kaffeine_guide_view_mode") || "grid";
    let selectedProgForModal = null;
    const SLOT_WIDTH = 150;
    const TOTAL_SLOTS = 56;
    const TRACK_WIDTH = TOTAL_SLOTS * SLOT_WIDTH;

    let isPanning = false;
    let panStartX = 0;
    let panStartY = 0;
    let panScrollLeft = 0;
    let panScrollTop = 0;
    let hasDragged = false;

    function initEPGPan() {
      const pane = document.getElementById("epgTimelinePane");
      const chList = document.getElementById("epgChannelList");
      const chCol = document.querySelector(".epg-channels-col");
      if (!pane) return;

      // Sync vertical scrolling between timeline pane and channel list
      pane.addEventListener("scroll", () => {
        if (chList) chList.scrollTop = pane.scrollTop;
      }, { passive: true });

      // Forward wheel scrolling from channel list to timeline pane
      if (chCol) {
        chCol.addEventListener("wheel", (e) => {
          pane.scrollTop += e.deltaY;
          e.preventDefault();
        }, { passive: false });
      }

      function startPan(e) {
        if (e.button !== 0) return;
        isPanning = true;
        hasDragged = false;
        panStartX = e.pageX - pane.offsetLeft;
        panStartY = e.pageY - pane.offsetTop;
        panScrollLeft = pane.scrollLeft;
        panScrollTop = pane.scrollTop;
      }

      pane.addEventListener("mousedown", startPan);
      if (chCol) {
        chCol.addEventListener("mousedown", startPan);
      }

      window.addEventListener("mousemove", (e) => {
        if (!isPanning) return;
        const x = e.pageX - pane.offsetLeft;
        const y = e.pageY - pane.offsetTop;
        const walkX = x - panStartX;
        const walkY = y - panStartY;

        if (Math.abs(walkX) > 4 || Math.abs(walkY) > 4) {
          hasDragged = true;
          pane.classList.add("grabbing");
        }

        pane.scrollLeft = panScrollLeft - walkX;
        pane.scrollTop = panScrollTop - walkY;
      });

      window.addEventListener("mouseup", () => {
        if (!isPanning) return;
        isPanning = false;
        pane.classList.remove("grabbing");
        setTimeout(() => {
          hasDragged = false;
        }, 80);
      });
    }

    function setGuideViewMode(mode) {
      currentGuideViewMode = mode;
      localStorage.setItem("kaffeine_guide_view_mode", mode);
      updateGuideViewControls();
      renderGuide();
    }

    function updateGuideViewControls() {
      const isGrid = currentGuideViewMode === "grid";
      const gridBtn = document.getElementById("viewGridBtn");
      const listBtn = document.getElementById("viewListBtn");
      const gridBox = document.getElementById("guideGridContainer");
      const listBox = document.getElementById("guideListContainer");
      const nowBtn = document.getElementById("jumpNowBtn");
      const trimWrapper = document.getElementById("trimPassedWrapper");

      if (gridBtn) gridBtn.className = isGrid ? "active" : "";
      if (listBtn) listBtn.className = !isGrid ? "active" : "";
      if (gridBox) gridBox.style.display = isGrid ? "block" : "none";
      if (listBox) listBox.style.display = isGrid ? "none" : "block";
      if (nowBtn) nowBtn.style.display = isGrid ? "inline-flex" : "none";
      if (trimWrapper) trimWrapper.style.display = isGrid ? "none" : "inline-flex";
    }

    async function apiFetch(endpoint, options = {}) {
      options.headers = options.headers || {};
      if (authToken) {
        options.headers["Authorization"] = "Bearer " + authToken;
      }
      const resp = await fetch(endpoint, options);
      if (resp.status === 401) {
        document.getElementById("loginOverlay").classList.add("active");
        throw new Error("Unauthorized");
      }
      return resp;
    }

    async function doLogin() {
      const input = document.getElementById("loginPassInput");
      const err = document.getElementById("loginError");
      err.style.display = "none";
      try {
        const resp = await fetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: input.value })
        });
        const data = await resp.json();
        if (resp.ok && data.token) {
          authToken = data.token;
          localStorage.setItem("kaffeine_web_token", authToken);
          document.getElementById("loginOverlay").classList.remove("active");
          input.value = "";
          initApp();
        } else {
          err.style.display = "block";
        }
      } catch (e) {
        err.style.display = "block";
      }
    }

    function switchTab(tab) {
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
      if (tab === "guide") {
        document.querySelectorAll(".nav-btn")[0].classList.add("active");
        document.getElementById("guideView").classList.add("active");
        loadGuide();
      } else {
        document.querySelectorAll(".nav-btn")[1].classList.add("active");
        document.getElementById("recordingsView").classList.add("active");
        loadRecordings();
      }
    }

    function populateDateDropdown() {
      const sel = document.getElementById("guideDateSelect");
      sel.innerHTML = "";
      const now = new Date();
      for (let i = 0; i < 7; i++) {
        const d = new Date(now);
        d.setDate(d.getDate() + i);
        const iso = d.toISOString().split("T")[0];
        const opt = document.createElement("option");
        opt.value = iso;
        opt.textContent = i === 0 ? `Today (${iso})` : i === 1 ? `Tomorrow (${iso})` : `${d.toLocaleDateString('en-US', { weekday: 'short' })} (${iso})`;
        sel.appendChild(opt);
      }
    }

    async function checkStatus() {
      try {
        const resp = await apiFetch("/api/status");
        if (resp.ok) {
          const data = await resp.json();
          const freeGb = data.free_disk_gb !== undefined ? data.free_disk_gb + " GB Free" : "";
          const activeCount = data.active_recordings !== undefined ? data.active_recordings + " Recording" : "";
          document.getElementById("diskStatusText").textContent = [freeGb, activeCount].filter(Boolean).join(" • ") || "Ready";
        }
      } catch (e) {}
    }

    function populateChannelDropdown(items) {
      const sel = document.getElementById("guideChannelSelect");
      if (!sel) return;
      const currentVal = sel.value || "All";
      const channelSet = new Set();
      (items || []).forEach(p => {
        if (p.channel) channelSet.add(p.channel);
      });
      const channels = Array.from(channelSet);
      channels.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));

      sel.innerHTML = '<option value="All">All Channels</option>' +
        channels.map(ch => `<option value="${escapeHtml(ch)}">${escapeHtml(ch)}</option>`).join("");

      if (channels.includes(currentVal)) {
        sel.value = currentVal;
      } else {
        sel.value = "All";
      }
    }

    async function loadGuide() {
      const dateElem = document.getElementById("guideDateSelect");
      const selDate = dateElem ? dateElem.value : "";
      const tbody = document.getElementById("guideTableBody");
      const notice = document.getElementById("epgEmptyNotice");
      const content = document.getElementById("epgGridContent");

      if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--text-muted);">Fetching schedule for ${selDate || "today"}...</td></tr>`;
      if (notice) {
        notice.style.display = "block";
        notice.textContent = `Fetching schedule for ${selDate || "today"}...`;
      }
      if (content) content.style.display = "none";

      try {
        const resp = await apiFetch(`/api/guide?date=${encodeURIComponent(selDate)}`);
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          const errMsg = `Error ${resp.status}: ${escapeHtml(errData.error || "Failed to load TV guide.")}`;
          if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: #ef4444;">${errMsg}</td></tr>`;
          if (notice) {
            notice.style.display = "block";
            notice.innerHTML = errMsg;
          }
          if (content) content.style.display = "none";
          return;
        }
        guideItems = await resp.json();
        populateChannelDropdown(guideItems);
        renderGuide();

        const now = new Date();
        const todayStr = now.toISOString().split("T")[0];
        if (selDate === todayStr && currentGuideViewMode === "grid") {
          setTimeout(scrollToCurrentTime, 120);
        }
      } catch (e) {
        const errMsg = escapeHtml(e.message || "Failed to load TV guide.");
        if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: #ef4444;">${errMsg}</td></tr>`;
        if (notice) {
          notice.style.display = "block";
          notice.innerHTML = errMsg;
        }
        if (content) content.style.display = "none";
      }
    }

    function renderGuide() {
      const q = (document.getElementById("guideSearchInput").value || "").toLowerCase().trim();
      const chSel = document.getElementById("guideChannelSelect");
      const selectedChannel = chSel ? chSel.value : "All";

      let items = guideItems || [];
      if (selectedChannel && selectedChannel !== "All") {
        items = items.filter(p => p.channel === selectedChannel);
      }
      if (q) {
        items = items.filter(p =>
          (p.title && p.title.toLowerCase().includes(q)) ||
          (p.channel && p.channel.toLowerCase().includes(q)) ||
          (p.episode_title && p.episode_title.toLowerCase().includes(q))
        );
      }

      if (currentGuideViewMode === "grid") {
        renderEPGGrid(items);
      } else {
        renderGuideTable(items);
      }
    }

    function renderGuideTable(items) {
      const tbody = document.getElementById("guideTableBody");
      if (!tbody) return;
      if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--text-muted);">No broadcast listings found for this date.</td></tr>`;
        return;
      }

      const selDate = document.getElementById("guideDateSelect") ? document.getElementById("guideDateSelect").value : "";
      const now = new Date();
      const todayStr = now.toISOString().split("T")[0];
      const isToday = selDate === todayStr;
      const trimCheckbox = document.getElementById("trimPassedCheckbox");
      const shouldTrim = isToday && trimCheckbox && trimCheckbox.checked;

      let displayItems = items;
      if (shouldTrim) {
        displayItems = items.filter(p => {
          if (!p.start_iso) return true;
          const startDt = new Date(p.start_iso);
          const durMins = p.runtime_mins || 30;
          const endDt = new Date(startDt.getTime() + durMins * 60000);
          return endDt >= now;
        });
      }

      if (displayItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--text-muted);">No upcoming programs remaining for today. Uncheck "Trim Passed Shows" to view earlier broadcasts.</td></tr>`;
        return;
      }

      window.filteredGuideList = displayItems;

      tbody.innerHTML = displayItems.map((p, idx) => {
        const startStr = p.start_iso ? p.start_iso.substring(11, 16) : "--:--";
        const timeCell = `<span style="font-weight: 600; color: var(--accent); font-size: 0.82rem;">${escapeHtml(startStr)}</span>`;

        const isScheduled = !!p.is_scheduled;
        const btnHtml = isScheduled
          ? `<span class="badge badge-armed" style="padding: 2px 6px; font-size: 0.7rem;">Scheduled</span>`
          : `<button class="btn btn-sm" style="padding: 2px 8px; font-size: 0.75rem;" onclick="scheduleShowByIndex(${idx})">Record</button>`;

        let titleHtml = `<span style="font-weight: 600;">${escapeHtml(p.title || "Untitled")}</span>`;
        if (p.episode_title) {
          titleHtml += ` <span style="font-size: 0.76rem; color: var(--text-muted); font-weight: normal;">(${escapeHtml(p.episode_title)})</span>`;
        }

        const durStr = p.duration_iso ? p.duration_iso.substring(0, 5) : "00:30";

        return `<tr>
          <td>${timeCell}</td>
          <td><b>${escapeHtml(p.channel || "")}</b></td>
          <td>${titleHtml}</td>
          <td style="color: var(--text-muted); font-size: 0.8rem;">${escapeHtml(durStr)}</td>
          <td style="text-align: right;">${btnHtml}</td>
        </tr>`;
      }).join("");
    }

    function renderEPGGrid(items) {
      const notice = document.getElementById("epgEmptyNotice");
      const content = document.getElementById("epgGridContent");
      const chList = document.getElementById("epgChannelList");
      const timeHeader = document.getElementById("epgTimelineHeader");
      const timeBody = document.getElementById("epgTimelineBody");

      if (!items || items.length === 0) {
        if (notice) {
          notice.style.display = "block";
          notice.textContent = "No broadcast listings found for this date.";
        }
        if (content) content.style.display = "none";
        return;
      }

      if (notice) notice.style.display = "none";
      if (content) content.style.display = "flex";

      // Group by channel in order
      const channelMap = new Map();
      for (const p of items) {
        const ch = p.channel || "Unknown";
        if (!channelMap.has(ch)) {
          channelMap.set(ch, []);
        }
        channelMap.get(ch).push(p);
      }

      const selDate = document.getElementById("guideDateSelect") ? document.getElementById("guideDateSelect").value : "";
      const dayStart = new Date(selDate + "T00:00:00");
      const now = new Date();
      const todayStr = now.toISOString().split("T")[0];
      const isToday = selDate === todayStr;

      // Build Timeline Header slots
      let slotsHtml = "";
      for (let s = 0; s < TOTAL_SLOTS; s++) {
        const slotMins = s * 30;
        const slotDate = new Date(dayStart.getTime() + slotMins * 60000);
        const timeLabel = slotDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
        slotsHtml += `<div class="epg-time-slot">${escapeHtml(timeLabel)}</div>`;
      }

      // Now indicator line
      let nowLineHtml = "";
      if (isToday) {
        const diffMins = (now - dayStart) / 60000;
        if (diffMins >= 0 && diffMins <= TOTAL_SLOTS * 30) {
          const nowPx = Math.round((diffMins / 30) * SLOT_WIDTH);
          nowLineHtml = `<div class="epg-now-line" style="left: ${nowPx}px;"></div>`;
        }
      }

      let channelCellsHtml = "";
      let rowsHtml = "";

      channelMap.forEach((progs, chName) => {
        channelCellsHtml += `<div class="epg-channel-cell">
          <div class="epg-channel-name" title="${escapeHtml(chName)}">${escapeHtml(chName)}</div>
        </div>`;

        let tilesHtml = "";
        for (const p of progs) {
          const pIdx = guideItems.indexOf(p);
          if (!p.start_iso) continue;
          const startDt = new Date(p.start_iso);
          const diffMins = Math.round((startDt - dayStart) / 60000);
          const durMins = p.runtime_mins || 30;
          if (diffMins + durMins <= 0 || diffMins >= TOTAL_SLOTS * 30) continue;

          const clampedStartMins = Math.max(0, diffMins);
          const clampedDurMins = durMins - (diffMins < 0 ? Math.abs(diffMins) : 0);
          const leftPx = Math.round((clampedStartMins / 30) * SLOT_WIDTH);
          const widthPx = Math.max(40, Math.round((clampedDurMins / 30) * SLOT_WIDTH) - 2);

          const isSched = !!p.is_scheduled;
          const endDt = new Date(startDt.getTime() + durMins * 60000);
          const isAiringNow = isToday && (startDt <= now && now < endDt);

          const timeRange = `${p.start_iso.substring(11, 16)} - ${endDt.toTimeString().substring(0, 5)}`;
          const tileClass = `epg-program-tile ${isSched ? 'scheduled' : ''} ${isAiringNow ? 'airing-now' : ''}`;

          tilesHtml += `<div class="${tileClass}" style="left: ${leftPx}px; width: ${widthPx}px;" onclick="openProgramModal(${pIdx})" title="${escapeHtml(p.title)}: ${escapeHtml(p.summary || '')}">
            <div class="epg-tile-title">${isSched ? '<span class="epg-rec-dot"></span>' : ''}${escapeHtml(p.title || 'Untitled')}</div>
            <div class="epg-tile-time">${escapeHtml(timeRange)}</div>
          </div>`;
        }

        rowsHtml += `<div class="epg-row">
          ${tilesHtml}
        </div>`;
      });

      if (chList) chList.innerHTML = channelCellsHtml;
      if (timeHeader) timeHeader.innerHTML = nowLineHtml + slotsHtml;
      if (timeBody) timeBody.innerHTML = nowLineHtml + rowsHtml;
    }

    function scrollToCurrentTime() {
      const pane = document.getElementById("epgTimelinePane");
      if (!pane) return;
      const selDate = document.getElementById("guideDateSelect") ? document.getElementById("guideDateSelect").value : "";
      const dayStart = new Date(selDate + "T00:00:00");
      const now = new Date();
      const diffMins = (now - dayStart) / 60000;
      if (diffMins >= 0 && diffMins <= TOTAL_SLOTS * 30) {
        const nowPx = Math.round((diffMins / 30) * SLOT_WIDTH);
        pane.scrollTo({ left: Math.max(0, nowPx - 120), behavior: 'smooth' });
      } else {
        pane.scrollTo({ left: 0, behavior: 'smooth' });
      }
    }

    function openProgramModal(idx) {
      if (hasDragged) return;
      const p = (guideItems || [])[idx];
      if (!p) return;
      selectedProgForModal = p;

      document.getElementById("progModalTitle").textContent = p.title || "Untitled";
      document.getElementById("progModalSubtitle").textContent = p.episode_title || "";
      document.getElementById("progModalMeta").textContent = `${p.channel || ""} • ${p.start_iso ? p.start_iso.replace('T', ' ') : ''} (${p.duration_iso || '00:30:00'})`;
      document.getElementById("progModalSummary").textContent = p.summary || "No description provided in TV Guide listing.";

      const actBtn = document.getElementById("progModalActionBtn");
      if (p.is_scheduled) {
        actBtn.textContent = "Already Scheduled";
        actBtn.className = "btn btn-secondary";
        actBtn.disabled = true;
      } else {
        actBtn.textContent = "Schedule Recording";
        actBtn.className = "btn";
        actBtn.disabled = false;
      }

      document.getElementById("programModal").classList.add("active");
    }

    function closeProgramModal(e) {
      document.getElementById("programModal").classList.remove("active");
      selectedProgForModal = null;
    }

    async function handleProgModalAction() {
      if (!selectedProgForModal) return;
      const p = selectedProgForModal;
      closeProgramModal();
      await scheduleShow(p);
    }

    async function scheduleShowByIndex(idx) {
      const p = (window.filteredGuideList || [])[idx];
      if (!p) return;
      await scheduleShow(p);
    }

    async function scheduleShow(prog) {
      try {
        const resp = await apiFetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: prog.title,
            channel: prog.channel,
            start_iso: prog.start_iso,
            duration_iso: prog.duration_iso
          })
        });
        if (resp.ok) {
          prog.is_scheduled = true;
          renderGuide();
        } else {
          alert("Failed to schedule recording.");
        }
      } catch (e) {
        alert("Network error while scheduling.");
      }
    }

    async function loadRecordings() {
      const tbody = document.getElementById("recordingsTableBody");
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: var(--text-muted);">Fetching recordings...</td></tr>`;
      try {
        const resp = await apiFetch("/api/recordings");
        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: #ef4444;">Error ${resp.status}: ${escapeHtml(errData.error || "Failed to load recordings.")}</td></tr>`;
          return;
        }
        const data = await resp.json();
        const active = data.active || [];
        const history = data.history || [];
        const combined = [...active, ...history];

        if (combined.length === 0) {
          tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: var(--text-muted);">No recordings scheduled or recorded yet.</td></tr>`;
          return;
        }

        window.recordingsData = combined;

        tbody.innerHTML = combined.map((r, idx) => {
          const isFinished = r.status === "COMPLETED" || !r.status;
          const isFileAvailable = !!r.file_available;
          let playBtn = "";
          if (isFileAvailable) {
            playBtn = `<button class="btn btn-sm" onclick="playByIndex(${idx})">▶ Play</button>`;
          } else if (r.status === "RECORDING") {
            playBtn = `<span class="badge badge-recording">Recording Now</span>`;
          } else if (r.status === "ARMED" || r.status === "QUEUED") {
            playBtn = `<span class="badge badge-queued">${r.status}</span>`;
          } else {
            playBtn = `<span style="color: var(--text-muted); font-size: 0.8rem;">File Unavailable</span>`;
          }

          let actionBtn = "";
          if (r.id && (r.status === "QUEUED" || r.status === "ARMED")) {
            actionBtn = `<button class="btn btn-danger btn-sm" onclick="cancelRecording(${r.id})">Cancel</button>`;
          } else if (isFileAvailable && r.stream_url) {
            const rawDlUrl = authToken ? `${r.stream_url}?raw=1&token=${encodeURIComponent(authToken)}` : `${r.stream_url}?raw=1`;
            const dlName = escapeHtml(r.filename || ((r.title || "recording").trim().replace(/[/\\?%*:|"<>]/g, '_') + ".m2t"));
            actionBtn = `<a href="${rawDlUrl}" download="${dlName}" class="btn btn-secondary btn-sm" style="text-decoration: none; padding: 4px 8px; font-size: 0.75rem;">Download</a>`;
          }

          return `<tr>
            <td>${playBtn}</td>
            <td><b>${escapeHtml(r.title || "")}</b></td>
            <td>${escapeHtml(r.channel || "")}</td>
            <td style="color: var(--text-muted); font-size: 0.85rem;">${escapeHtml(r.start_iso || r.completed_at || "")}</td>
            <td>${escapeHtml(r.size_str || r.status || "Completed")}</td>
            <td style="text-align: right;">${actionBtn}</td>
          </tr>`;
        }).join("");
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: #ef4444;">Failed to load recordings.</td></tr>`;
      }
    }

    function playByIndex(idx) {
      const r = (window.recordingsData || [])[idx];
      if (!r) return;
      openVideoPlayer(r.stream_url, r.title, r.filename);
    }

    async function cancelRecording(id) {
      if (!confirm("Are you sure you want to cancel this scheduled recording?")) return;
      try {
        const resp = await apiFetch(`/api/schedule/${id}`, { method: "DELETE" });
        if (resp.ok) {
          loadRecordings();
        }
      } catch (e) {
        alert("Failed to cancel recording.");
      }
    }

    function openVideoPlayer(url, title, filename) {
      if (!url) return;
      const modal = document.getElementById("videoModal");
      const video = document.getElementById("html5VideoPlayer");
      const dlLink = document.getElementById("videoDownloadLink");
      document.getElementById("videoModalTitle").textContent = title || "Watch Recording";

      let downloadName = filename;
      if (!downloadName && title) {
        downloadName = title.trim().replace(/[/\\?%*:|"<>]/g, '_') + '.m2t';
      }
      if (downloadName) {
        dlLink.setAttribute("download", downloadName);
      } else {
        dlLink.removeAttribute("download");
      }

      // Stream URL (MP4 stream)
      const streamUrl = authToken ? `${url}?token=${encodeURIComponent(authToken)}` : url;
      // Direct raw file download URL
      const rawUrl = authToken ? `${url}?raw=1&token=${encodeURIComponent(authToken)}` : `${url}?raw=1`;
      dlLink.href = rawUrl;

      video.src = streamUrl;
      modal.classList.add("active");
      video.play().catch(() => {});
    }

    function closeVideoModal(e) {
      const modal = document.getElementById("videoModal");
      const video = document.getElementById("html5VideoPlayer");
      video.pause();
      video.src = "";
      modal.classList.remove("active");
    }

    function escapeHtml(str) {
      if (!str) return "";
      return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
    }

    function initApp() {
      populateDateDropdown();
      updateGuideViewControls();
      initEPGPan();
      checkStatus();
      loadGuide();
      setInterval(checkStatus, 15000);
    }

    // Initialize check
    (async function() {
      try {
        const resp = await fetch("/api/status", {
          headers: authToken ? { "Authorization": "Bearer " + authToken } : {}
        });
        if (resp.status === 401) {
          document.getElementById("loginOverlay").classList.add("active");
        } else {
          initApp();
        }
      } catch (e) {
        initApp();
      }
    })();
  </script>
</body>
</html>
"""

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

    main { flex: 1; padding: 18px 20px; max-width: 1200px; width: 100%; margin: 0 auto; }

    .view-panel { display: none; }
    .view-panel.active { display: block; }

    .toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; background: var(--card-bg); padding: 12px 16px; border-radius: 8px; border: 1px solid var(--card-border); }
    .toolbar-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    select, input[type="text"], input[type="password"] { background: #111827; border: 1px solid #374151; color: #fff; padding: 7px 12px; border-radius: 6px; font-size: 0.9rem; outline: none; }
    select:focus, input:focus { border-color: var(--accent); }

    .btn { background: #0284c7; color: #fff; border: none; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 0.88rem; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; transition: background 0.15s; }
    .btn:hover { background: var(--accent-hover); }
    .btn-danger { background: var(--danger); }
    .btn-danger:hover { background: var(--danger-hover); }
    .btn-sm { padding: 4px 10px; font-size: 0.8rem; }

    .grid-table { width: 100%; border-collapse: collapse; margin-top: 8px; background: var(--card-bg); border-radius: 8px; overflow: hidden; border: 1px solid var(--card-border); }
    .grid-table th { background: #141a24; padding: 10px 14px; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); border-bottom: 1px solid var(--card-border); }
    .grid-table td { padding: 12px 14px; border-bottom: 1px solid #232b38; font-size: 0.9rem; vertical-align: middle; }
    .grid-table tr:hover { background: #202836; }

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
        </div>
        <div class="toolbar-group">
          <input type="text" id="guideSearchInput" placeholder="Filter by show or channel..." oninput="filterGuideTable()">
        </div>
      </div>

      <table class="grid-table">
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

  <!-- Video Playback Modal -->
  <div id="videoModal" class="modal-overlay" onclick="closeVideoModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <span id="videoModalTitle" class="modal-title">Watch Recording</span>
        <button class="modal-close" onclick="closeVideoModal()">&times;</button>
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

    async function loadGuide() {
      const selDate = document.getElementById("guideDateSelect").value;
      const tbody = document.getElementById("guideTableBody");
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--text-muted);">Fetching schedule for ${selDate}...</td></tr>`;
      try {
        const resp = await apiFetch(`/api/guide?date=${selDate}`);
        if (!resp.ok) return;
        guideItems = await resp.json();
        renderGuideTable(guideItems);
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: #ef4444;">Failed to load TV guide.</td></tr>`;
      }
    }

    function renderGuideTable(items) {
      const tbody = document.getElementById("guideTableBody");
      if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 25px; color: var(--text-muted);">No broadcast listings found for this date.</td></tr>`;
        return;
      }
      tbody.innerHTML = items.map(p => {
        const start = p.start_iso ? p.start_iso.substring(11, 16) : "--:--";
        const isScheduled = !!p.is_scheduled;
        const btnHtml = isScheduled
          ? `<span class="badge badge-armed">Scheduled</span>`
          : `<button class="btn btn-sm" onclick='scheduleShow(${JSON.stringify(p)})'>Record</button>`;
        return `<tr>
          <td style="font-weight: 600; color: var(--accent);">${escapeHtml(start)}</td>
          <td><b>${escapeHtml(p.channel || "")}</b></td>
          <td>${escapeHtml(p.title || "Untitled")}</td>
          <td>${escapeHtml(p.duration_iso || "00:30:00")}</td>
          <td style="text-align: right;">${btnHtml}</td>
        </tr>`;
      }).join("");
    }

    function filterGuideTable() {
      const q = (document.getElementById("guideSearchInput").value || "").toLowerCase().trim();
      if (!q) {
        renderGuideTable(guideItems);
        return;
      }
      const filtered = guideItems.filter(p =>
        (p.title && p.title.toLowerCase().includes(q)) ||
        (p.channel && p.channel.toLowerCase().includes(q))
      );
      renderGuideTable(filtered);
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
          filterGuideTable();
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
        if (!resp.ok) return;
        const data = await resp.json();
        const active = data.active || [];
        const history = data.history || [];
        const combined = [...active, ...history];

        if (combined.length === 0) {
          tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: var(--text-muted);">No recordings scheduled or recorded yet.</td></tr>`;
          return;
        }

        tbody.innerHTML = combined.map(r => {
          const isFinished = r.status === "COMPLETED" || !r.status;
          const isFileAvailable = !!r.file_available;
          let playBtn = "";
          if (isFileAvailable) {
            playBtn = `<button class="btn btn-sm" onclick='openVideoPlayer("${r.stream_url}", "${escapeHtml(r.title)}")'>▶ Play</button>`;
          } else if (r.status === "RECORDING") {
            playBtn = `<span class="badge badge-recording">Recording Now</span>`;
          } else if (r.status === "ARMED" || r.status === "QUEUED") {
            playBtn = `<span class="badge badge-queued">${r.status}</span>`;
          } else {
            playBtn = `<span style="color: var(--text-muted); font-size: 0.8rem;">File Unavailable</span>`;
          }

          let cancelBtn = "";
          if (r.id && (r.status === "QUEUED" || r.status === "ARMED")) {
            cancelBtn = `<button class="btn btn-danger btn-sm" onclick="cancelRecording(${r.id})">Cancel</button>`;
          }

          return `<tr>
            <td>${playBtn}</td>
            <td><b>${escapeHtml(r.title || "")}</b></td>
            <td>${escapeHtml(r.channel || "")}</td>
            <td style="color: var(--text-muted); font-size: 0.85rem;">${escapeHtml(r.start_iso || r.completed_at || "")}</td>
            <td>${escapeHtml(r.size_str || r.status || "Completed")}</td>
            <td style="text-align: right;">${cancelBtn}</td>
          </tr>`;
        }).join("");
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; color: #ef4444;">Failed to load recordings.</td></tr>`;
      }
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

    function openVideoPlayer(url, title) {
      if (!url) return;
      const modal = document.getElementById("videoModal");
      const video = document.getElementById("html5VideoPlayer");
      document.getElementById("videoModalTitle").textContent = title || "Watch Recording";
      // Append token query param if authenticated
      const fullUrl = authToken ? `${url}?token=${encodeURIComponent(authToken)}` : url;
      video.src = fullUrl;
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

// Mnemo Trust Console — vanilla JS, no dependencies, no CDN.
// Talks only to this app's own read-only /api/* routes (never to GMS/UI directly from the browser).

const $ = (sel) => document.querySelector(sel);

// --- heartbeat: the 5-second-wow ticker -------------------------------------------------------

let hbBaseSeconds = null;
let hbBaseWallClock = null;
let hbWatchingCount = 0;
let hbAwake = false;

function escapeXml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
  }[c]));
}

function renderHeartbeat() {
  const el = $("#heartbeat");
  const txt = $("#hb-text");
  el.classList.remove("heartbeat--pending", "heartbeat--awake", "heartbeat--stale", "heartbeat--down");

  if (hbBaseSeconds === null) {
    el.classList.add("heartbeat--down");
    txt.textContent = "no wake events observed yet";
    return;
  }
  const drifted = Math.floor((Date.now() - hbBaseWallClock) / 1000);
  const liveSeconds = Math.max(0, hbBaseSeconds + drifted);
  el.classList.add(hbAwake ? "heartbeat--awake" : "heartbeat--stale");
  const plural = hbWatchingCount === 1 ? "" : "s";
  txt.textContent =
    `Mnemo ${hbAwake ? "awake" : "quiet"} · last event ${liveSeconds}s ago · ` +
    `watching ${hbWatchingCount} PROD model${plural}`;
}

async function pollHeartbeat() {
  try {
    const r = await fetch("/api/heartbeat");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    hbBaseSeconds = data.last_event_seconds_ago;
    hbBaseWallClock = Date.now();
    hbWatchingCount = data.watching_count;
    hbAwake = data.awake;
  } catch (e) {
    hbBaseSeconds = null;
  }
  renderHeartbeat();
}

setInterval(renderHeartbeat, 1000);
setInterval(pollHeartbeat, 5000);

// --- confidence timeseries chart (inline SVG, built from live mnemo.provenance) ---------------

function buildTimeseriesSVG(prov) {
  const W = 820, H = 420;
  const marginL = 56, marginR = 30, marginT = 26, marginB = 56;
  const plotTop = marginT, plotBottom = H - marginB;
  const plotW = W - marginL - marginR;
  const n = prov.length;

  const xFor = (i) => (n <= 1 ? marginL + plotW / 2 : marginL + i * (plotW / (n - 1)));
  const yFor = (c) => plotBottom - c * (plotBottom - plotTop);

  let grid = "";
  [0, 0.25, 0.5, 0.75, 1.0].forEach((v) => {
    const y = yFor(v);
    grid += `<line x1="${marginL}" y1="${y}" x2="${W - marginR}" y2="${y}" stroke="#2c313c" stroke-width="1"/>`;
    grid += `<text x="${marginL - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#8a93a2">${v.toFixed(2)}</text>`;
  });

  const tauY = yFor(0.70);
  const tauLine =
    `<line x1="${marginL}" y1="${tauY}" x2="${W - marginR}" y2="${tauY}" stroke="#d9a441" stroke-width="1.5" stroke-dasharray="6,4"/>` +
    `<text x="${W - marginR}" y="${tauY - 8}" text-anchor="end" font-size="10.5" fill="#d9a441">governance τ=0.70</text>`;

  if (n === 0) {
    return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
      <rect width="${W}" height="${H}" fill="#1b1f27" rx="8"/>${grid}${tauLine}
      <text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="13" fill="#8a93a2">no provenance events recorded yet</text>
      </svg>`;
  }

  let segLines = "";
  for (let i = 1; i < n; i++) {
    const delta = prov[i].delta ?? 0;
    const color = delta < 0 ? "#e06c75" : "#9aa4b2";
    segLines += `<line x1="${xFor(i - 1)}" y1="${yFor(prov[i - 1].c_after)}" x2="${xFor(i)}" y2="${yFor(prov[i].c_after)}" stroke="${color}" stroke-width="3" stroke-linecap="round"/>`;
  }

  let points = "";
  prov.forEach((p, i) => {
    const x = xFor(i), y = yFor(p.c_after);
    const dotColor = (p.delta ?? 0) < 0 ? "#e06c75" : "#9aa4b2";
    points += `<circle cx="${x}" cy="${y}" r="5.5" fill="${dotColor}"/>`;
    points += `<text x="${x}" y="${y - 12}" text-anchor="middle" font-size="12" font-weight="bold" fill="#e6e6e6">${Number(p.c_after).toFixed(3)}</text>`;
    points += `<text x="${x}" y="${H - marginB + 18}" text-anchor="middle" font-size="10" fill="#8a93a2">${escapeXml(p.source)}</text>`;
    points += `<text x="${x}" y="${H - marginB + 31}" text-anchor="middle" font-size="9" fill="#606774">${escapeXml(p.event || "")}</text>`;
  });

  return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
    <rect width="${W}" height="${H}" fill="#1b1f27" rx="8"/>
    ${grid}${tauLine}${segLines}${points}
    </svg>`;
}

// --- verdict / status badges -------------------------------------------------------------------

function verdictBadge(verdict) {
  if (!verdict) return `<span class="badge badge--muted">unobserved</span>`;
  const cls = { "auto-write": "badge--auto-write", "open-proposal": "badge--open-proposal", "needs-review": "badge--needs-review-verdict" }[verdict] || "badge--muted";
  return `<span class="badge ${cls}">${escapeXml(verdict)}</span>`;
}

function statusBadge(status) {
  if (!status) return `<span class="badge badge--muted">—</span>`;
  const cls = status === "NEEDS_REVIEW" ? "badge--needs-review" : "badge--trusted";
  return `<span class="badge ${cls}">${escapeXml(status)}</span>`;
}

// --- model detail (chart + meta) ----------------------------------------------------------------

async function loadModelDetail(urn) {
  const mount = $("#chart-mount");
  const meta = $("#model-meta");
  mount.innerHTML = `<p class="empty">Loading…</p>`;
  meta.innerHTML = "";
  try {
    const r = await fetch(`/api/model/${encodeURIComponent(urn)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    mount.innerHTML = buildTimeseriesSVG(d.provenance || []);

    const ago = d.last_wake_seconds_ago;
    const agoText = ago === null || ago === undefined ? "unknown" : `${ago}s ago`;
    const drift = d.sources_drifted
      ? `<span style="color:var(--red)">drifted</span>`
      : (d.current_sources && d.current_sources.length ? `<span style="color:var(--green)">stable</span>` : "—");

    meta.innerHTML = `
      <div><dt>confidence</dt><dd>${Number(d.confidence).toFixed(3)}</dd></div>
      <div><dt>verdict</dt><dd>${verdictBadge(d.verdict)}</dd></div>
      <div><dt>governance</dt><dd>${statusBadge(d.governance_status)}</dd></div>
      <div><dt>last wake</dt><dd>${agoText}</dd></div>
      <div><dt>last event</dt><dd>${escapeXml(d.last_event || "—")}</dd></div>
      <div><dt>sources</dt><dd>${drift}</dd></div>
    `;
  } catch (e) {
    mount.innerHTML = `<p class="empty">Failed to load: ${escapeXml(e.message)}</p>`;
  }
}

// --- governance queue ----------------------------------------------------------------------------

async function renderQueue(models) {
  const mount = $("#queue-mount");
  const countBadge = $("#queue-count");
  const needsReview = models.filter((m) => m.governance_status === "NEEDS_REVIEW");
  countBadge.textContent = String(needsReview.length);

  if (needsReview.length === 0) {
    mount.innerHTML = `<p class="empty">Nothing awaiting review.</p>`;
    return;
  }

  mount.innerHTML = `<div class="queue-list">${needsReview
    .map(
      (m) => `
    <div class="queue-item" data-urn="${escapeXml(m.urn)}">
      <div class="queue-item-head">
        <span>${escapeXml(m.model_name)}</span>
        ${verdictBadge(m.verdict)}
      </div>
      <div class="urn">${escapeXml(m.urn)}</div>
      <div class="evidence">confidence ${Number(m.confidence).toFixed(3)} · loading evidence…</div>
    </div>`
    )
    .join("")}</div>`;

  document.querySelectorAll(".queue-item").forEach((el) => {
    el.addEventListener("click", () => {
      $("#model-select").value = el.dataset.urn;
      loadModelDetail(el.dataset.urn);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });

  // Fill in evidence URNs (remembered-vs-current) per queue item, best-effort, after the list
  // is already interactive — this is the only place the console makes N follow-up requests, and
  // N is bounded by the queue size (models actually needing review), not the full model count.
  await Promise.all(
    needsReview.map(async (m) => {
      try {
        const r = await fetch(`/api/model/${encodeURIComponent(m.urn)}`);
        if (!r.ok) return;
        const d = await r.json();
        const el = document.querySelector(`.queue-item[data-urn="${CSS.escape(m.urn)}"] .evidence`);
        if (!el) return;
        const current = (d.current_sources || []).join(", ") || "—";
        el.textContent = `confidence ${Number(m.confidence).toFixed(3)} · current source: ${current}`;
      } catch (_) {
        /* best-effort only */
      }
    })
  );
}

// --- model list / selector -----------------------------------------------------------------------

async function loadModels() {
  try {
    const r = await fetch("/api/models");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const select = $("#model-select");
    select.innerHTML = "";
    data.models.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m.urn;
      opt.textContent = `${m.model_name} · c=${Number(m.confidence).toFixed(3)}`;
      select.appendChild(opt);
    });
    await renderQueue(data.models);
    if (data.models.length) {
      select.value = data.models[0].urn;
      await loadModelDetail(data.models[0].urn);
    } else {
      $("#chart-mount").innerHTML = `<p class="empty">No observed models yet — run the demo pipeline.</p>`;
    }
  } catch (e) {
    $("#chart-mount").innerHTML = `<p class="empty">Failed to reach the console API: ${escapeXml(e.message)}</p>`;
  }
}

$("#model-select").addEventListener("change", (ev) => loadModelDetail(ev.target.value));

// --- boot -----------------------------------------------------------------------------------------

pollHeartbeat();
loadModels();
setInterval(loadModels, 30000); // refresh model list + queue every 30s (heartbeat ticks every 5s)

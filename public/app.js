/* SENTINEL / WW3 BAROMETER v4.0 — Rendering Engine */
const SCORE_CIRCUMFERENCE = 2 * Math.PI * 92;

function formatDateTime(value) {
  try {
    const d = new Date(value);
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: false, timeZoneName: 'short'
    }).format(d);
  } catch { return value || '—'; }
}

function esc(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

function nl2br(str) { return esc(str).replace(/\n/g, '<br>'); }

function classBadge(kind) {
  const m = { VERIFIED:'class-verified', ASSESSMENT:'class-assessment', INTERPRETIVE:'class-interpretive', DATA:'class-data' };
  return '<span class="class-badge '+(m[kind]||'class-data')+'">'+esc(kind||'DATA')+'</span>';
}

function confBadge(level) {
  return '<span class="confidence-badge confidence-'+(level||'moderate').toLowerCase()+'">'+esc(level||'MODERATE')+'</span>';
}

function sevBadge(level) {
  return '<span class="severity-badge severity-'+(level||'watch').toLowerCase()+'">'+esc(level||'WATCH')+'</span>';
}

function vectorFill(cls) {
  switch ((cls||'').toUpperCase()) {
    case 'INTERPRETIVE': return 'fill-purple';
    case 'DATA': return 'fill-moderate';
    case 'VERIFIED': return 'fill-verified';
    default: return 'fill-high';
  }
}

function scoreColor(score, cls) {
  if (cls === 'INTERPRETIVE') return 'color-purple';
  if (score >= 86) return 'color-critical';
  if (score >= 80) return 'color-high';
  return 'color-elevated';
}

async function fetchJson(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error('Failed to load ' + path);
  return r.json();
}

async function loadDashboard() {
  const params = new URLSearchParams(location.search);
  const snap = params.get('snapshot');
  const path = snap ? '../data/archive/' + snap : '../data/latest.json';
  renderDashboard(await fetchJson(path), Boolean(snap));
}

function renderDashboard(data, isArchive) {
  const m = data.meta || {};
  const s = data.summary || {};
  const score = Number(m.score || 0);
  const delta = Number(m.delta || 0);

  // Header
  document.getElementById('dayBadge').textContent = m.day_label || 'DAY';
  document.getElementById('headerTimestamp').textContent = m.header_timestamp_label || formatDateTime(m.last_updated);

  // Alert tape
  document.getElementById('alertTape').textContent = data.alert_tape || (data.alerts || []).join(' — ');

  // Score
  const arc = document.getElementById('scoreArc');
  arc.style.strokeDasharray = SCORE_CIRCUMFERENCE;
  arc.style.strokeDashoffset = SCORE_CIRCUMFERENCE * (1 - Math.min(score, 100) / 100);
  document.getElementById('scoreNumber').textContent = score;
  document.getElementById('heroStatus').textContent = s.headline || m.status || '—';
  document.getElementById('heroSubheadline').textContent = s.subheadline || '';
  document.getElementById('scoreDelta').textContent = (delta >= 0 ? '▲ +' : '▼ ') + Math.abs(delta);
  document.getElementById('scoreChangeText').textContent = m.previous_score !== undefined
    ? 'pts in 5 days — fastest single-week jump recorded' : 'pts from prior snapshot';
  document.getElementById('summaryDescription').textContent = s.description || '';
  document.getElementById('lastUpdated').textContent = formatDateTime(m.last_updated);
  document.getElementById('nextUpdate').textContent = formatDateTime(m.next_update);
  document.getElementById('scoreConfidence').textContent = s.confidence || 'MODERATE';

  // Snapshot notice
  const notice = document.getElementById('snapshotNotice');
  if (isArchive || m.fallback_notice) {
    notice.classList.remove('is-hidden');
    notice.textContent = isArchive ? 'Archive view: ' + formatDateTime(m.last_updated) : (m.fallback_notice || 'Displaying most recent published snapshot.');
  }

  // Footer
  document.getElementById('footerVersion').textContent = [m.platform_name, m.product_name, m.version, m.day_label].filter(Boolean).join(' // ');
  document.getElementById('nextThreshold').textContent = m.threshold_watch || 'NEXT THRESHOLD: 90 / CRITICAL';
  document.getElementById('footerWatch').textContent = m.footer_watch || 'WATCHING FOR 90';

  // Changelog
  document.getElementById('changelog').innerHTML = (data.changelog || []).map(function(item) {
    return '<div class="change-item"><strong>Change</strong><br>' + esc(item) + '</div>';
  }).join('');

  // Vectors
  document.getElementById('vectors').innerHTML = (data.vectors || []).map(function(v) {
    var pct = Math.max(0, Math.min(v.score || 0, 100));
    return '<article class="vector-item">' +
      '<div class="vector-header"><div class="vector-name">' + esc(v.name) + '</div>' +
      '<div class="vector-score-badge ' + scoreColor(v.score, v.class) + '">' + v.score + '/100</div></div>' +
      '<div class="vector-badge-row">' + classBadge(v.class) + ' ' + confBadge(v.confidence) + '</div>' +
      '<div class="vector-bar-track"><div class="vector-bar-fill ' + vectorFill(v.class) + '" style="width:' + pct + '%"></div></div>' +
      '<div class="vector-change">' + (v.delta >= 0 ? '↑ +' : '↓ ') + Math.abs(v.delta) + ' // ' + esc(v.driver) + '</div>' +
      '<div class="vector-note">' + esc(v.note) + '</div></article>';
  }).join('');

  // Intel cards
  document.getElementById('intelCards').innerHTML = (data.intel_cards || []).map(function(c) {
    var sev = (c.severity || '').toLowerCase();
    return '<article class="intel-card ' + sev + '">' +
      '<div class="intel-tag-row">' + classBadge(c.class) + ' ' + sevBadge(c.severity) + ' ' + confBadge(c.confidence) + '</div>' +
      '<div class="intel-tag ' + sev + '">' + esc(c.timestamp_label || formatDateTime(c.timestamp)) + '</div>' +
      '<div class="intel-text">' + esc(c.summary) + '</div>' +
      (c.analyst_note ? '<div class="analyst-note">Analyst: ' + esc(c.analyst_note) + '</div>' : '') +
      '<div class="source-line"><span>Source: ' + esc(c.source_label || '—') + '</span>' +
      '<span>Type: ' + esc(c.source_type || '—') + '</span>' +
      (c.published_at ? '<span>Published: ' + esc(formatDateTime(c.published_at)) + '</span>' : '') +
      (c.source_url ? '<a href="' + esc(c.source_url) + '" target="_blank" rel="noreferrer">Open source</a>' : '') +
      '</div></article>';
  }).join('');

  // Doctrine
  var doc = data.doctrine || {};
  document.getElementById('doctrineTitle').textContent = doc.title || 'Netanyahu Messiah Doctrine';
  document.getElementById('doctrineQuote').textContent = doc.quote || '';
  document.getElementById('doctrineSource').textContent = doc.quote_source || '';
  document.getElementById('doctrineCards').innerHTML = (doc.cards || []).map(function(c) {
    return '<article class="intel-card theological">' +
      '<div class="intel-tag-row">' + classBadge(c.class || 'INTERPRETIVE') + '</div>' +
      '<div class="intel-tag theological">' + esc(c.tag) + '</div>' +
      '<div class="intel-text">' + esc(c.text) + '</div></article>';
  }).join('');

  // Axis chain — clean rendering without React fragments
  var axis = data.axis || {};
  document.getElementById('axisTitle').textContent = axis.title || 'Theological Command Axis';
  var nodes = axis.nodes || [];
  var axisHtml = '';
  for (var i = 0; i < nodes.length; i++) {
    axisHtml += '<div class="axis-node"><strong>' + esc(nodes[i].title) + '</strong>' + nl2br(nodes[i].body || '') + '</div>';
    if (i < nodes.length - 1) axisHtml += '<div class="axis-arrow">→</div>';
  }
  document.getElementById('axisChain').innerHTML = axisHtml;

  // Traditions table
  var trad = data.traditions || {};
  document.getElementById('traditionsTitle').textContent = trad.title || 'Four-Tradition Theological Convergence';
  document.getElementById('traditionsBody').innerHTML = (trad.rows || []).map(function(r) {
    return '<tr><td class="tradition-name">' + esc(r.tradition) + '</td>' +
      '<td><span class="tradition-status status-' + esc(r.status_class || 'high') + '">' + esc(r.status) + '</span></td>' +
      '<td class="tradition-signal">' + esc(r.signal) + '</td></tr>';
  }).join('');

  // Ramadan overlay
  var ov = data.overlay || {};
  document.getElementById('overlayTitle').textContent = ov.title || 'RAMADAN OVERLAY';
  document.getElementById('overlaySubtitle').textContent = ov.subtitle || '';
  document.getElementById('overlayDescription').innerHTML = esc(ov.description || '').replace(/this week/gi, '<strong>this week</strong>');
  document.getElementById('overlayTimeline').innerHTML = (ov.timeline || []).map(function(t) {
    var st = (t.state || '').toUpperCase();
    var cls = st.includes('ACTIVE') ? 'active' : st === 'PEAK' ? 'peak' : st === 'FINAL' ? 'final' : '';
    return '<article class="ramadan-node ' + cls + '">' +
      (st.includes('ACTIVE') ? '<div class="ramadan-active-badge">' + esc(t.state) + '</div>' : '') +
      '<div class="ramadan-date">' + esc(t.date) + '</div>' +
      '<div class="ramadan-event">' + esc(t.title) + '</div>' +
      '<div class="ramadan-desc">' + esc(t.description) + '</div></article>';
  }).join('');

  // Info warfare
  var iw = data.info_warfare || {};
  document.getElementById('infoWarfareTitle').textContent = iw.title || 'Information Warfare';
  document.getElementById('infoWarfareCards').innerHTML = (iw.cards || []).map(function(c) {
    return '<article class="intel-card high">' +
      '<div class="intel-tag-row">' + classBadge(c.class || 'ASSESSMENT') + '</div>' +
      '<div class="intel-tag high">' + esc(c.tag) + '</div>' +
      '<div class="intel-text">' + esc(c.text) + '</div></article>';
  }).join('');

  // Market data
  document.getElementById('marketData').innerHTML = (data.market_sections || []).map(function(sec) {
    return '<div class="market-block"><div class="market-heading">' + esc(sec.title) + '</div>' +
      (sec.rows || []).map(function(r) {
        return '<div class="data-row"><div class="data-label">' + esc(r.label) + '</div>' +
          '<div class="data-value ' + (r.direction || '').toLowerCase() + '">' + esc(r.value) + '</div></div>';
      }).join('') + '</div>';
  }).join('');

  // Triggers
  document.getElementById('triggers').innerHTML = (data.triggers || []).map(function(t) {
    return '<article class="trigger-item"><div class="trigger-num">' + String(t.id).padStart(2, '0') + '</div>' +
      '<div class="trigger-text">' + esc(t.text) + '</div></article>';
  }).join('');
}

async function loadArchive() {
  var index = await fetchJson('../data/archive/index.json');
  document.getElementById('archiveList').innerHTML = (index.snapshots || []).map(function(item) {
    return '<article class="archive-item"><h3>' + esc(item.status) + ' — ' + item.score + '/100</h3>' +
      '<div class="archive-meta">' + esc(formatDateTime(item.last_updated)) + ' // Δ ' + (item.delta >= 0 ? '+' : '') + item.delta + '</div>' +
      '<p>' + esc(item.summary || '') + '</p>' +
      '<div class="archive-drivers">' + (item.top_drivers || []).map(function(d) {
        return '<span class="archive-driver">' + esc(d) + '</span>';
      }).join('') + '</div>' +
      '<a class="archive-link" href="index.html?snapshot=' + encodeURIComponent(item.file) + '">Open snapshot →</a></article>';
  }).join('');
}

(async function boot() {
  var page = document.body.dataset.page;
  try {
    if (page === 'dashboard') await loadDashboard();
    else if (page === 'archive') await loadArchive();
  } catch (err) {
    console.error(err);
    var t = page === 'archive' ? document.getElementById('archiveList') : document.querySelector('main');
    if (t) t.insertAdjacentHTML('afterbegin',
      '<section class="panel panel-tight" style="border-color:rgba(255,34,51,0.3);margin:24px">' +
      '<div class="section-title">Load Error</div><p class="copy">' + esc(err.message) + '</p></section>');
  }
})();

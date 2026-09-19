/* KCA 연구보고서 현행화 — 브라우저 UI (바닐라 JS, ES2020)
 * 서버 계약: app/DESIGN.md 7절. fetch('/api/...')만 호출한다.
 * ?mock=1 이면 mock.js가 window.fetch / EventSource를 가로채 가짜 데이터로 동작한다. */
(() => {
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const IS_MOCK = new URLSearchParams(location.search).get('mock') === '1';
const LS_KEY = 'kca.currentReport';

/* ------------------------------------------------------------------ */
/* 상수                                                                 */
/* ------------------------------------------------------------------ */
const VIEWS = {
  dashboard: '대시보드', intake: '접수', run: '실행', table: '결론 대조표',
  impact: '영향 지도', outputs: '산출물', kb: '지식베이스', settings: '설정',
};
const VERDICT_ORDER = ['동일', '강화', '부분수정', '약화', '뒤집힘', '신규결론', '판정불가', '잠정'];
const VERDICT_CLASS = {
  '동일': 'good', '강화': 'good', '부분수정': 'warn', '약화': 'warn', '뒤집힘': 'bad',
  '신규결론': 'new', '판정불가': 'na', '잠정': 'prov', '': 'prov',
};
const KIND_LABEL = { RQ: '연구질문', F: '사실·현황', Fc: '전망', M: '계량', S: '설문', T: '기술', R: '제언', P: '정책', B: '배경' };
const LOCUS_LABEL = { P: '전제', E: '근거', M: '방법' };
const EFFECT_CLASS = { '강화': 'good', '유지': 'good', '약화': 'warn', '부분': 'warn', '소멸': 'bad', '반전': 'bad', '뒤집힘': 'bad', '무관': 'na', '불명': 'na' };
const DOMAIN_LABEL = {
  spectrum: '주파수', network_5g6g: '네트워크·5G/6G', private_5g: '이음5G', smart_factory: '스마트공장',
  industry_economics: '산업경제', broadcast_media: '방송·미디어', emf_inspection: '전자파·검사',
  ict_qualification: 'ICT 자격', kca_management: '기관 경영',
};
/* 단계 목록은 app/engine/stages.py 의 STAGE_ORDER 와 같아야 한다.
 * types: 이 단계를 켜는 결론 유형(03_argument_chains.json 의 conclusions[].types). 비면 유형과 무관.
 * option: run_config.options 의 켜기·끄기 항목. */
const STAGES = [
  { name: 'intake', ko: '접수', layer: '' },
  { name: 'classify', ko: '분류', layer: 'L0' },
  { name: 'chains', ko: '결론·사슬', layer: 'L0' },
  { name: 'delta', ko: '사건 조사', layer: 'L0' },
  { name: 'impact', ko: '영향 전파', layer: 'L0' },
  { name: 'verify_forecast', ko: '전망 검증', layer: 'L1', types: ['F', 'B', 'G'] },
  { name: 'verify_model', ko: '모형 재계산', layer: 'L1', types: ['M'] },
  { name: 'verify_policy', ko: '정책 추적', layer: 'L1', types: ['P'] },
  { name: 'design_survey', ko: '재설문 설계', layer: 'L1', types: ['S'], option: 'survey_redesign' },
  { name: 'design_experiment', ko: '재실험 계획', layer: 'L1', types: ['T'], option: 'experiment_plan' },
  { name: 'brief', ko: '브리프', layer: 'L2' },
  { name: 'blind', ko: '블라인드', layer: 'L2' },
  { name: 'compare', ko: '비교 판정', layer: 'L2' },
  { name: 'report', ko: '보고서', layer: '' },
  { name: 'critic', ko: '검토', layer: '' },
];
const STATUS_KO = { running: '실행 중', done: '완료', skipped: '건너뜀', failed: '실패', cancelled: '취소됨', queued: '대기', pending: '대기' };
/* 스테퍼 칸 수는 STAGES 길이를 따른다. style.css 는 건드리지 않고 여기서 규칙만 덧댄다. */
function injectStepperStyle() {
  if (document.getElementById('stepperStyle')) return;
  const st = document.createElement('style');
  st.id = 'stepperStyle';
  st.textContent = `
.stepper{grid-template-columns:repeat(${STAGES.length},1fr)}
.step-note{font-size:10px; color:var(--muted); min-height:12px}
.step[data-status="skipped"] .step-note{color:var(--muted)}
@media (max-width:1100px){.stepper{grid-template-columns:repeat(5,1fr)}}
@media (max-width:720px){.stepper{grid-template-columns:repeat(3,1fr)}}`;
  document.head.appendChild(st);
}

/* ------------------------------------------------------------------ */
/* 상태                                                                 */
/* ------------------------------------------------------------------ */
const state = {
  view: 'dashboard',
  reports: [],
  currentId: null,
  health: null,
  doctor: null,
  doctorAt: null,
  settings: null,
  models: [],
  runs: [],
  detail: {},      // report_id -> GET /api/reports/{id}
  data: {},        // report_id -> {comparison, chains, events, provisional}
  kbEvents: null,
  job: null,       // {job_id, report_id, stages:{name:status}, tokensIn, tokensOut, cost, startedAt, status}
  es: null,
  elapsedTimer: null,
  tableTab: 'conclusion',
  selectedRow: null,
  impactFocus: null,
  outTab: 'report',
};

/* ------------------------------------------------------------------ */
/* 유틸                                                                 */
/* ------------------------------------------------------------------ */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
function fmtInt(n) { return Number(n || 0).toLocaleString('ko-KR'); }
function fmtUsd(n) { return '$' + Number(n || 0).toFixed(4); }
function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return String(s).slice(0, 16);
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtBytes(n) {
  n = Number(n || 0);
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(2) + ' MB';
}
function truncate(s, n) { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
function todayISO() { return new Date().toISOString().slice(0, 10); }
function toast(msg, type = '') {
  const t = el(`<div class="toast ${type ? 'is-' + type : ''}">${esc(msg)}</div>`);
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), type === 'error' ? 6000 : 3500);
}
function pill(v) {
  const c = VERDICT_CLASS[v] ?? 'na';
  return `<span class="pill p-${c}">${esc(v || '잠정')}</span>`;
}
function gradeBadge(g) {
  g = (g || '').toString().trim();
  return g ? `<span class="grade grade-${esc(g[0])}">${esc(g)}</span>` : '<span class="grade">–</span>';
}
function maturityBadge(m) {
  m = (m || '-').toString();
  if (m === '-' || m === '') return '<span class="pill p-na">미실행</span>';
  let c = 'na';
  if (m.startsWith('L2')) c = m.includes('부분') ? 'new' : 'good';
  else if (m.startsWith('L1')) c = 'warn';
  else if (m.startsWith('L0')) c = 'na';
  return `<span class="pill p-${c}">${esc(m)}</span>`;
}
function statusBadge(s) {
  const map = { running: 'run', done: 'good', succeeded: 'good', failed: 'bad', cancelled: 'warn', skipped: 'na', queued: 'na', pending: 'na' };
  return `<span class="pill p-${map[s] || 'na'}">${esc(STATUS_KO[s] || s || '—')}</span>`;
}
function summaryBadges(summary, { clickable = false, active = '' } = {}) {
  if (!summary) return '';
  return VERDICT_ORDER.filter(k => k in summary).map(k => {
    const n = summary[k] || 0;
    const cls = `pill p-${VERDICT_CLASS[k]} badge-count ${n ? '' : 'is-off'} ${active === k ? 'is-filter' : ''}`;
    const inner = `${esc(k)} <b>${fmtInt(n)}</b>`;
    return clickable ? `<button type="button" class="${cls}" data-verdict="${esc(k)}">${inner}</button>` : `<span class="${cls}">${inner}</span>`;
  }).join('');
}
function isUrl(s) { return /^https?:\/\//i.test(s || ''); }
function evidenceLink(e) {
  const label = e.note || e.title || e.url || '';
  if (isUrl(e.url)) return `<a href="${esc(e.url)}" target="_blank" rel="noopener" title="${esc(e.url)}">${esc(label)}</a>`;
  return `<span title="${esc(e.url || '')}">${esc(label)}${e.url && !label.includes(e.url) ? ` <code class="muted">${esc(e.url)}</code>` : ''}</span>`;
}
function currentReport() { return state.reports.find(r => r.id === state.currentId) || null; }

/* ------------------------------------------------------------------ */
/* API                                                                  */
/* ------------------------------------------------------------------ */
async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    if (opts.body instanceof FormData) init.body = opts.body;
    else { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  }
  let res;
  try { res = await fetch(path, init); }
  catch (e) { throw new Error(`서버에 연결할 수 없습니다 (${path})`); }
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (_) { /* ignore */ }
    const err = new Error(msg); err.status = res.status; throw err;
  }
  if (opts.text) return res.text();
  if (ct.includes('application/json')) return res.json();
  return res.text();
}
api.get = p => api(p);
api.put = (p, body) => api(p, { method: 'PUT', body });
api.post = (p, body) => api(p, { method: 'POST', body });
api.del = p => api(p, { method: 'DELETE' });
api.text = p => api(p, { text: true });

function uploadWithProgress(path, fd, onProgress) {
  if (IS_MOCK || typeof XMLHttpRequest === 'undefined') {
    // mock: fetch를 쓰면서 진행률만 흉내
    return new Promise((resolve, reject) => {
      let p = 0;
      const t = setInterval(() => { p = Math.min(95, p + 12); onProgress(p); }, 90);
      api.post(path, fd).then(r => { clearInterval(t); onProgress(100); resolve(r); }).catch(e => { clearInterval(t); reject(e); });
    });
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', path);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100)); };
    xhr.onload = () => {
      let j = null; try { j = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(j);
      else reject(new Error((j && j.error) || `${xhr.status} ${xhr.statusText}`));
    };
    xhr.onerror = () => reject(new Error('업로드 중 연결이 끊겼습니다.'));
    xhr.send(fd);
  });
}

/* ------------------------------------------------------------------ */
/* 라우터 · 공통                                                        */
/* ------------------------------------------------------------------ */
function currentViewName() {
  const h = (location.hash || '#dashboard').slice(1).split('?')[0];
  return VIEWS[h] ? h : '404';
}
async function route() {
  const name = currentViewName();
  state.view = name;
  $$('.view').forEach(v => { v.hidden = v.id !== `view-${name}`; });
  $$('.nav-list a').forEach(a => a.classList.toggle('is-active', a.dataset.view === name));
  $('#pageTitle').textContent = VIEWS[name] || '없는 화면';
  closeDrawer();
  const renderers = { dashboard: renderDashboard, intake: renderIntake, run: renderRun, table: renderTable, impact: renderImpact, outputs: renderOutputs, kb: renderKb, settings: renderSettings };
  if (renderers[name]) {
    try { await renderers[name](); }
    catch (e) { console.error(e); toast(e.message || String(e), 'error'); }
  }
}

function setCurrentReport(id, { rerender = true } = {}) {
  if (!id || id === state.currentId) { syncReportSelectors(); return; }
  state.currentId = id;
  try { localStorage.setItem(LS_KEY, id); } catch (_) { /* ignore */ }
  state.selectedRow = null;
  syncReportSelectors();
  if (rerender) route();
}
function syncReportSelectors() {
  const opts = state.reports.map(r => `<option value="${esc(r.id)}">${esc(r.id)} · ${esc(truncate(r.title, 46))}</option>`).join('');
  for (const sel of [$('#reportSelect'), $('#runReport')]) {
    if (!sel) continue;
    sel.innerHTML = opts || '<option value="">(보고서 없음)</option>';
    sel.value = state.currentId || '';
  }
  const r = currentReport();
  const tm = $('#topMaturity');
  if (r) { tm.hidden = false; tm.outerHTML = `<span id="topMaturity">${maturityBadge(r.maturity)}</span>`; }
  else tm.hidden = true;
}

async function loadReports() {
  state.reports = await api.get('/api/reports');
  state.reports.sort((a, b) => a.id.localeCompare(b.id));
  let saved = null;
  try { saved = localStorage.getItem(LS_KEY); } catch (_) { /* ignore */ }
  if (!state.reports.some(r => r.id === state.currentId)) {
    const pick = state.reports.find(r => r.id === saved) || state.reports.find(r => r.maturity && r.maturity !== '-') || state.reports[0];
    state.currentId = pick ? pick.id : null;
  }
  syncReportSelectors();
}

async function loadHealth() {
  const h = $('#navHealth');
  try {
    state.health = await api.get('/api/health');
    h.innerHTML = `<span class="dot dot-good"></span><span class="nav-label">서버 연결됨${IS_MOCK ? ' (모의)' : ''}</span>`;
    $('#navVersion').textContent = state.health.version ? `v${state.health.version}` : '';
  } catch (e) {
    state.health = null;
    h.innerHTML = `<span class="dot dot-bad"></span><span class="nav-label">서버 없음</span>`;
  }
}

async function loadDoctor(force = false) {
  if (state.doctor && !force) return state.doctor;
  state.doctor = await api.get('/api/doctor');
  state.doctorAt = new Date();
  return state.doctor;
}

async function loadModels(force = false) {
  if (state.models.length && !force) return state.models;
  try { state.models = await api.get('/api/models'); }
  catch (e) { state.models = []; toast('모델 목록을 불러오지 못했습니다: ' + e.message, 'error'); }
  return state.models;
}

async function loadRuns() {
  try { state.runs = await api.get('/api/runs'); } catch (e) { state.runs = []; }
  state.runs.sort((a, b) => String(b.started_at || '').localeCompare(String(a.started_at || '')));
  return state.runs;
}

async function loadReportDetail(id, force = false) {
  if (!id) return null;
  if (state.detail[id] && !force) return state.detail[id];
  state.detail[id] = await api.get(`/api/reports/${encodeURIComponent(id)}`);
  return state.detail[id];
}

async function loadReportData(id, force = false) {
  if (!id) return null;
  if (state.data[id] && !force) return state.data[id];
  const tryGet = p => api.get(p).catch(() => null);
  const [comparison, chains, events, provisional] = await Promise.all([
    tryGet(`/api/reports/${id}/comparison`), tryGet(`/api/reports/${id}/chains`),
    tryGet(`/api/reports/${id}/events`), tryGet(`/api/reports/${id}/provisional`),
  ]);
  state.data[id] = { comparison, chains, events: Array.isArray(events) ? events : (events && events.events) || [], provisional: Array.isArray(provisional) ? provisional : [] };
  return state.data[id];
}

function notRunMessage(id) {
  return `${id}는 아직 실행되지 않았습니다. 「실행」에서 ① 바뀐 것 찾기(L0)부터 돌리면 여기가 채워집니다.`;
}

/* ------------------------------------------------------------------ */
/* 1. 대시보드                                                          */
/* ------------------------------------------------------------------ */
async function renderDashboard() {
  await loadRuns();
  const reports = state.reports;
  const done = reports.filter(r => (r.maturity || '').startsWith('L2')).length;
  const partial = reports.filter(r => r.maturity && r.maturity !== '-' && !(r.maturity || '').startsWith('L2')).length;
  const running = state.runs.filter(r => r.status === 'running').length;
  const totalCost = state.runs.reduce((s, r) => s + (Number(r.cost_usd) || 0), 0);
  $('#dashStats').innerHTML = `
    <div class="stat"><span class="k">접수된 보고서</span><span class="v">${reports.length}</span><span class="s">registry.csv</span></div>
    <div class="stat is-good"><span class="k">③까지 완료</span><span class="v">${done}</span><span class="s">L2 판정 보유 · 부분 ${partial}편</span></div>
    <div class="stat ${running ? 'is-accent' : ''}"><span class="k">실행 중</span><span class="v">${running}</span><span class="s">최근 실행 ${state.runs.length}건</span></div>
    <div class="stat"><span class="k">누적 비용</span><span class="v">${fmtUsd(totalCost)}</span><span class="s">runs/*.json 합계</span></div>`;

  const tb = $('#dashReports tbody');
  tb.innerHTML = reports.map(r => `
    <tr class="is-clickable ${r.id === state.currentId ? 'is-selected' : ''}" data-id="${esc(r.id)}">
      <td class="k">${esc(r.id)}</td>
      <td class="title-cell"><a href="#table" data-id="${esc(r.id)}">${esc(r.title)}</a><div class="loc">${esc((r.domain || '').split(',').map(d => DOMAIN_LABEL[d.trim()] || d).filter(Boolean).join(' · '))}</div></td>
      <td class="num">${esc(r.published || '—')}</td>
      <td class="num">${r.years_since != null ? esc(r.years_since) + '년' : '—'}</td>
      <td>${maturityBadge(r.maturity)}${r.running ? ' <span class="pill p-run">실행 중</span>' : ''}</td>
      <td>${r.summary ? `<div class="summary-badges">${summaryBadges(r.summary)}</div>` : '<span class="muted">—</span>'}</td>
      <td class="num muted">${esc(fmtDate(r.updated_at))}</td>
      <td><a class="btn btn-sm" href="#run" data-id="${esc(r.id)}">실행</a></td>
    </tr>`).join('');
  $('#dashReportsEmpty').hidden = reports.length > 0;
  $$('#dashReports tbody tr').forEach(tr => {
    tr.addEventListener('click', e => {
      const a = e.target.closest('a');
      setCurrentReport(tr.dataset.id, { rerender: !a });
      if (!a) location.hash = '#table';
    });
  });

  renderDashStatus();
  if (!state.doctor) loadDoctor().then(renderDashStatus).catch(() => renderDashStatus());

  const rb = $('#dashRuns tbody');
  rb.innerHTML = state.runs.slice(0, 8).map(r => `
    <tr>
      <td class="k">${esc(String(r.job_id || '').slice(0, 12))}</td>
      <td class="k">${esc(r.report_id)}</td>
      <td>${statusBadge(r.status)}</td>
      <td>${miniSteps(r.stages)}</td>
      <td class="num muted">${esc(fmtDate(r.started_at))}</td>
      <td class="num">${fmtUsd(r.cost_usd)}</td>
    </tr>`).join('');
  $('#dashRunsEmpty').hidden = state.runs.length > 0;
}

function miniSteps(stages) {
  const m = normalizeStages(stages);
  return `<span class="mini-steps" title="${esc(STAGES.map(s => `${s.ko}: ${STATUS_KO[m[s.name]] || '대기'}`).join(', '))}">${STAGES.map(s => `<i class="${esc(m[s.name] || '')}"></i>`).join('')}</span>`;
}
function normalizeStages(stages) {
  const m = {};
  if (!stages) return m;
  if (Array.isArray(stages)) {
    for (const s of stages) {
      if (typeof s === 'string') m[s] = 'done';
      else if (s && (s.name || s.stage)) m[s.name || s.stage] = s.status || 'done';
    }
  } else if (typeof stages === 'object') Object.assign(m, stages);
  return m;
}

function renderDashStatus() {
  const d = state.doctor, h = state.health;
  const ok = v => v === true ? '<span class="pill p-good">정상</span>' : v === false ? '<span class="pill p-bad">실패</span>' : '<span class="pill p-na">확인 중</span>';
  const rows = [];
  rows.push(`<tr><td>서버</td><td>${h ? `${ok(true)} <span class="muted">v${esc(h.version)} · ${esc(h.core_dir || '')}</span>` : ok(false)}</td></tr>`);
  if (d) {
    rows.push(`<tr><td>LLM</td><td>${ok(d.llm && d.llm.ok)} <code>${esc(d.llm && d.llm.model)}</code> <span class="muted">${esc(d.llm && d.llm.detail || '')}</span></td></tr>`);
    rows.push(`<tr><td>검색</td><td>${ok(d.search && d.search.ok)} <code>${esc(d.search && d.search.provider)}</code> <span class="muted">${esc(d.search && d.search.detail || '')}</span></td></tr>`);
    const src = d.sources || [];
    const conf = src.filter(s => s.configured).length, okc = src.filter(s => s.ok === true).length;
    rows.push(`<tr><td>근거 소스</td><td><b class="num">${conf}</b>/${src.length} 설정됨 · <b class="num">${okc}</b> 응답 확인 <a href="#settings" class="muted">상세</a></td></tr>`);
    rows.push(`<tr><td>파서</td><td>${['hwp', 'docx'].map(k => `${esc(k)} ${d.parsers && d.parsers[k] ? '<span class="pill p-good">사용 가능</span>' : '<span class="pill p-na">없음</span>'}`).join(' ')}</td></tr>`);
  } else {
    rows.push(`<tr><td>LLM · 검색 · 소스</td><td>${ok(null)}</td></tr>`);
  }
  $('#dashStatus tbody').innerHTML = rows.join('');
}

/* ------------------------------------------------------------------ */
/* 2. 접수                                                              */
/* ------------------------------------------------------------------ */
let intakeFile = null;
function setupIntake() {
  const dz = $('#dropzone'), fi = $('#fileInput');
  dz.addEventListener('click', () => fi.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); } });
  ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('is-over'); }));
  dz.addEventListener('drop', e => { const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) pickFile(f); });
  fi.addEventListener('change', () => { if (fi.files[0]) pickFile(fi.files[0]); });
  $('#intakeReset').addEventListener('click', resetIntake);
  $('#intakeForm').addEventListener('submit', submitIntake);
}
function pickFile(f) {
  const ext = (f.name.split('.').pop() || '').toLowerCase();
  if (!['pdf', 'hwpx', 'hwp', 'docx', 'txt', 'md'].includes(ext)) { toast('지원하지 않는 형식입니다: .' + ext, 'error'); return; }
  intakeFile = f;
  $('#dzFile').hidden = false;
  $('#dzFile').textContent = `${f.name} · ${fmtBytes(f.size)}`;
  $('#intakeSubmit').disabled = false;
  const t = $('#intakeTitle');
  if (!t.value) t.value = f.name.replace(/\.[^.]+$/, '').replace(/^\d+_?/, '').replace(/\[\d{4}\.\d{2}\]_?/, '').replace(/_/g, ' ').trim();
  const m = f.name.match(/\[(\d{4})\.(\d{2})\]/);
  if (m && !$('#intakePublished').value) $('#intakePublished').value = `${m[1]}-${m[2]}`;
}
function resetIntake() {
  intakeFile = null;
  $('#fileInput').value = '';
  $('#dzFile').hidden = true;
  $('#intakeSubmit').disabled = true;
  $('#intakeForm').reset();
  $('#intakeProgress').hidden = true;
  $('#intakeResult').hidden = true;
  $('#intakeResultEmpty').hidden = false;
  suggestId();
}
function suggestId() {
  const nums = state.reports.map(r => parseInt((r.id || '').replace(/\D/g, ''), 10)).filter(n => !isNaN(n));
  const next = (nums.length ? Math.max(...nums) : 0) + 1;
  $('#intakeId').placeholder = 'R' + String(next).padStart(2, '0');
  $('#intakeIdHint').textContent = `비워 두면 서버가 다음 번호(${'R' + String(next).padStart(2, '0')})를 붙입니다.`;
}
async function renderIntake() { suggestId(); }
async function submitIntake(e) {
  e.preventDefault();
  if (!intakeFile) { toast('먼저 파일을 선택하세요.', 'error'); return; }
  const fd = new FormData();
  fd.append('file', intakeFile, intakeFile.name);
  const rid = $('#intakeId').value.trim();
  if (rid) fd.append('report_id', rid);
  fd.append('title', $('#intakeTitle').value.trim());
  fd.append('published', $('#intakePublished').value.trim());
  const prog = $('#intakeProgress'), bar = $('.progress-bar', prog), lab = $('.progress-label', prog);
  prog.hidden = false; bar.style.width = '0%'; lab.textContent = '0%';
  $('#intakeSubmit').disabled = true;
  try {
    const res = await uploadWithProgress('/api/reports/intake', fd, p => { bar.style.width = p + '%'; lab.textContent = p + '%'; });
    lab.textContent = '파싱 완료';
    const meta = res.meta || {};
    $('#intakeResultEmpty').hidden = true;
    $('#intakeResult').hidden = false;
    $('#intakeScanWarn').hidden = !meta.scanned;
    $('#intakeMeta').innerHTML = [
      ['보고서 ID', `<code>${esc(res.report_id)}</code>`],
      ['제목', esc(meta.title || '')],
      ['발간', esc(meta.published || '—')],
      ['형식', `<code>${esc(meta.format || '')}</code>`],
      ['쪽수', `<span class="num">${fmtInt(meta.pages)}</span>`],
      ['글자 수', `<span class="num">${fmtInt(meta.chars)}</span>`],
      ['원본 파일', `<code>${esc(meta.source_pdf || meta.source || intakeFile.name)}</code>`],
    ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
    $('#intakeGoRun').addEventListener('click', () => setCurrentReport(res.report_id, { rerender: false }), { once: true });
    toast(`${res.report_id} 접수 완료`, 'ok');
    await loadReports();
    setCurrentReport(res.report_id, { rerender: false });
    $('#intakeSubmit').disabled = false;
  } catch (err) {
    prog.hidden = true;
    $('#intakeSubmit').disabled = false;
    toast('업로드 실패: ' + err.message, 'error');
  }
}

/* ------------------------------------------------------------------ */
/* 3. 실행                                                              */
/* ------------------------------------------------------------------ */
function setupRun() {
  injectStepperStyle();
  $('#stepper').innerHTML = STAGES.map(s => `
    <li class="step" data-stage="${s.name}" data-status="">
      <span class="step-layer">${esc(s.layer || ' ')}</span>
      <span class="step-bar"></span>
      <span class="step-name">${esc(s.ko)}</span>
      <span class="step-en">${esc(s.name)}</span>
      <span class="step-note"></span>
    </li>`).join('');
  $('#runForce').innerHTML += STAGES.map(s => `<option value="${s.name}">${esc(s.ko)} (${s.name})부터</option>`).join('');
  $('#runReport').addEventListener('change', e => {
    setCurrentReport(e.target.value, { rerender: false });
    // 보고서가 바뀌면 화면의 기록도 그 보고서 것으로 갈아 끼운다.
    $('#log').textContent = '';
    $('#log').dataset.loadedFor = '';
    loadPastLog(e.target.value);
  });
  $('#optSim').addEventListener('change', e => { $('#optSimRow').hidden = !e.target.checked; $('#optSimWarn').hidden = !e.target.checked; });
  $('#optBlind').addEventListener('change', e => { $('#optRepeats').disabled = !e.target.checked; });
  $('#runForm').addEventListener('submit', startRun);
  $('#runCancel').addEventListener('click', cancelRun);
  $('#logClear').addEventListener('click', () => {
    // 화면만 비운다. 파일(reports/<id>/logs/app_run.jsonl)은 그대로 남는다.
    $('#log').textContent = '';
    $('#log').dataset.loadedFor = '';
  });
}
async function renderRun() {
  syncReportSelectors();
  const r = currentReport();
  // 실행 화면을 열면 그 보고서의 지난 기록을 먼저 올린다(같은 보고서면 한 번만).
  // 처음 열 때는 state.currentId 가 아직 비어 있을 수 있어 선택 상자 값도 본다.
  loadPastLog(state.currentId || ($('#runReport') && $('#runReport').value));
  if (r && !$('#runSince').value) $('#runSince').value = r.published ? `${r.published}-01` : '';
  if (!$('#runUntil').value) $('#runUntil').value = todayISO();
  if (state.settings == null) { try { state.settings = await api.get('/api/settings'); } catch (_) { /* ignore */ } }
  const s = state.settings && state.settings.settings;
  if (s) {
    $('#runModelHint').textContent = `비워 두면 설정의 모델(${s.model || 'openrouter/auto'})을 씁니다.`;
    if (!$('#runProvider').dataset.touched) $('#runProvider').value = s.search_provider || 'auto';
  }
  loadModels().then(models => {
    $('#modelList').innerHTML = models.map(m => `<option value="${esc(m.id)}">${esc(m.name || m.id)}</option>`).join('');
  });
  // 진행 중인 작업이 있으면 붙는다
  if (!state.job || state.job.status !== 'running') {
    await loadRuns();
    const live = state.runs.find(x => x.status === 'running' && x.report_id === state.currentId) || state.runs.find(x => x.status === 'running');
    if (live) attachJob(live.job_id, live.report_id);
  }
  renderJob();
}
function collectRunConfig() {
  const layers = $$('input[name=layers]:checked', $('#runForm')).map(i => i.value);
  return {
    report_id: $('#runReport').value,
    layers,
    options: {
      blind_rerun: { enabled: $('#optBlind').checked, repeats: Math.max(1, parseInt($('#optRepeats').value, 10) || 1) },
      survey_redesign: $('#optSurvey').checked,
      experiment_plan: $('#optExperiment').checked,
      synthetic_sim: { enabled: $('#optSim').checked, panel_size: parseInt($('#optSimPanel').value, 10) || 200 },
      l0_rewrite_scope: 'env_and_desk_updatable',
    },
    sources: ['openalex', 'kosis', 'data_go_kr', 'law', 'naver', 'web'],
    output: ['html'],
    period: { since: $('#runSince').value || null, until: $('#runUntil').value || 'today' },
    search_provider: $('#runProvider').value || 'auto',
    model: $('#runModel').value.trim() || null,
  };
}
async function startRun(e) {
  e.preventDefault();
  const cfg = collectRunConfig();
  if (!cfg.report_id) { toast('보고서를 선택하세요.', 'error'); return; }
  if (!cfg.layers.length) { toast('층을 하나 이상 선택하세요.', 'error'); return; }
  if (cfg.options.synthetic_sim.enabled && !confirm('합성 시뮬레이션을 켭니다. 결과는 C등급·「시뮬레이션」 표기로만 남고 판정 근거로 쓰이지 않습니다. 계속할까요?')) return;
  const body = Object.assign({}, cfg, { force_from: $('#runForce').value || null });
  $('#runSubmit').disabled = true;
  try {
    const res = await api.post('/api/runs', body);
    // 예전에는 여기서 로그를 지웠다. 다시 실행할 때마다 지금까지 한 일이 사라져
    // "아까 뭐가 됐더라" 를 볼 수 없었다. 이제 구분선만 긋고 이어서 쌓는다.
    logDivider(`실행 시작 ${res.job_id}`);
    attachJob(res.job_id, cfg.report_id, cfg);
    toast(`실행 시작: ${res.job_id}`, 'ok');
  } catch (err) {
    $('#runSubmit').disabled = false;
    toast(err.status === 409 ? '이 보고서는 이미 실행 중입니다. 끝난 뒤 다시 시도하세요.' : '실행 요청 실패: ' + err.message, 'error');
  }
}
/* 이 실행에서 빠지는 단계(층·옵션·결론 유형) → {단계명: '해당 없음' 사유}. engine/stages.py stages_for 와 같은 규칙. */
function skippedStages(cfg, chains) {
  const out = {};
  if (!cfg) return out;
  const L = new Set(cfg.layers || []);
  const opts = cfg.options || {};
  const types = chainTypes(chains);
  for (const s of STAGES) {
    if (s.layer && !L.has(s.layer)) { out[s.name] = '층 제외'; continue; }
    if ((s.name === 'brief' || s.name === 'blind') && opts.blind_rerun && !opts.blind_rerun.enabled) { out[s.name] = '옵션 끔'; continue; }
    if (s.option && opts[s.option] === false) { out[s.name] = '옵션 끔'; continue; }
    if (s.types && types && !s.types.some(t => types.has(t))) out[s.name] = '해당 유형 없음';
  }
  return out;
}
function chainTypes(chains) {
  if (!chains || !Array.isArray(chains.conclusions)) return null;
  const set = new Set();
  for (const c of chains.conclusions) for (const t of (c && c.types) || []) if (t) set.add(String(t));
  return set;
}
function attachJob(jobId, reportId, cfg) {
  detachJob();
  state.job = { job_id: jobId, report_id: reportId, status: 'running', stages: {}, notes: {}, seen: {}, tokensIn: 0, tokensOut: 0, cost: 0, startedAt: Date.now(), cfg };
  // 층·옵션·결론 유형으로 빠지는 단계는 "해당 없음"으로 미리 표시
  if (cfg) {
    const chains = (state.data[reportId] || {}).chains || null;
    const skipped = skippedStages(cfg, chains);
    for (const [name, why] of Object.entries(skipped)) { state.job.stages[name] = 'skipped'; state.job.notes[name] = why; }
    if (!chains) {
      api.get(`/api/reports/${reportId}/chains`).then(ch => {
        if (!state.job || state.job.job_id !== jobId) return;
        for (const [name, why] of Object.entries(skippedStages(cfg, ch))) {
          if (state.job.seen[name]) continue;
          state.job.stages[name] = 'skipped';
          state.job.notes[name] = why;
        }
        renderJob();
      }).catch(() => { /* chains 가 아직 없으면 전 단계를 돈다 */ });
    }
  }
  api.get(`/api/runs/${jobId}`).then(j => applyJobSnapshot(j)).catch(() => { /* ignore */ });
  const es = new EventSource(`/api/runs/${jobId}/events`);
  state.es = es;
  const onEv = e => { try { handleProgress(JSON.parse(e.data)); } catch (err) { appendLog({ message: e.data }); } };
  es.onmessage = onEv;
  es.addEventListener('progress', onEv);
  // 서버는 시작 시 snapshot(작업 상태 dict), 끝날 때 end 이벤트를 추가로 보낸다
  es.addEventListener('snapshot', e => { try { applyJobSnapshot(JSON.parse(e.data)); } catch (_) { /* ignore */ } });
  es.addEventListener('end', e => {
    let j = null; try { j = JSON.parse(e.data); } catch (_) { /* ignore */ }
    if (j && j.status) { applyJobSnapshot(j); finishJob(j.status); }
    else api.get(`/api/runs/${jobId}`).then(x => { applyJobSnapshot(x); finishJob(x.status || 'done'); }).catch(() => finishJob('done'));
  });
  es.onerror = async () => {
    // 서버가 스트림을 닫았으면 최종 상태를 읽어 마무리한다
    try {
      const j = await api.get(`/api/runs/${jobId}`);
      if (j && ['done', 'failed', 'cancelled', 'succeeded'].includes(j.status)) { applyJobSnapshot(j); finishJob(j.status); }
    } catch (_) { /* 재연결 대기 */ }
  };
  state.elapsedTimer = setInterval(renderTally, 1000);
  renderJob();
}
function applyJobSnapshot(j) {
  if (!state.job || !j) return;
  Object.assign(state.job.stages, normalizeStages(j.stages));
  if (j.started_at) { const t = new Date(j.started_at).getTime(); if (!isNaN(t)) state.job.startedAt = t; }
  if (j.cost_usd != null) state.job.cost = Number(j.cost_usd) || state.job.cost;
  if (j.tokens) { state.job.tokensIn = tokIn(j.tokens) || state.job.tokensIn; state.job.tokensOut = tokOut(j.tokens) || state.job.tokensOut; }
  const msgs = j.messages || j.recent_messages || j.events || [];
  if (msgs.length && !$('#log').textContent) msgs.forEach(m => appendLog(typeof m === 'string' ? { message: m } : m));
  if (j.status && j.status !== 'running') state.job.status = j.status;
  renderJob();
}
function tokIn(t) { return t ? Number(t.in ?? t.prompt_tokens ?? t.tokens_in ?? t.input ?? 0) || 0 : 0; }
function tokOut(t) { return t ? Number(t.out ?? t.completion_tokens ?? t.tokens_out ?? t.output ?? 0) || 0 : 0; }
function handleProgress(ev) {
  const job = state.job;
  if (!job) return;
  if (ev.stage && ev.stage !== 'pipeline' && ev.stage !== '__end__') {
    job.stages[ev.stage] = ev.status || 'running';
    job.seen[ev.stage] = true;
    if (job.notes) delete job.notes[ev.stage];
  }
  // 서버가 보내는 ev.tokens / ev.cost_usd 는 **그 단계의 누적값**이고, 단계 하나가 진행되는 동안
  // 여러 번 온다. 그대로 더하면 같은 값을 반복해 더해 40배쯤 부풀려진다
  // (실제 $0.77 · 111만 토큰짜리 실행이 화면에는 $6.98 · 4,525만 토큰으로 나왔다).
  // 그래서 단계별 마지막 값을 기억해 **늘어난 만큼만** 더한다.
  if (ev.tokens_total) { job.tokensIn = tokIn(ev.tokens_total); job.tokensOut = tokOut(ev.tokens_total); }
  else if (ev.tokens) {
    job.lastSeen = job.lastSeen || {};
    const k = ev.stage || '';
    const prev = job.lastSeen[k] || { in: 0, out: 0 };
    const cur = { in: tokIn(ev.tokens), out: tokOut(ev.tokens) };
    job.tokensIn += Math.max(0, cur.in - prev.in);
    job.tokensOut += Math.max(0, cur.out - prev.out);
    job.lastSeen[k] = cur;
  }
  if (ev.cost_total_usd != null) job.cost = Number(ev.cost_total_usd) || 0;
  else if (ev.cost_usd != null) {
    job.lastCost = job.lastCost || {};
    const k = ev.stage || '';
    const cur = Number(ev.cost_usd) || 0;
    job.cost += Math.max(0, cur - (job.lastCost[k] || 0));
    job.lastCost[k] = cur;
  }
  appendLog(ev);
  const terminal = (ev.stage === 'pipeline' || ev.stage === '__end__') && ['done', 'failed', 'cancelled'].includes(ev.status);
  if (terminal) finishJob(ev.status);
  else if (ev.status === 'failed' && ev.fatal) finishJob('failed');
  renderJob();
}
function logDivider(text) {
  const log = $('#log');
  if (log.textContent.trim()) log.appendChild(document.createTextNode('\n'));
  log.appendChild(el(`<span class="ln"><span class="divider">──────── ${esc(text)} ────────</span></span>`));
  log.appendChild(document.createTextNode('\n'));
  if ($('#logAutoscroll').checked) log.scrollTop = log.scrollHeight;
}

/* 지난 실행 기록을 파일에서 불러와 화면에 올린다.
   기록은 이미 reports/<id>/logs/app_run.jsonl 에 계속 쌓이고 있었는데,
   화면이 실행할 때마다 비워져서 볼 수가 없었다. 보고서를 열 때 한 번 올려 준다. */
async function loadPastLog(reportId, { max = 1200 } = {}) {
  const log = $('#log');
  if (!reportId || log.dataset.loadedFor === reportId) return;
  log.dataset.loadedFor = reportId;
  let text = '';
  try {
    const q = new URLSearchParams({ path: 'logs/app_run.jsonl' });
    text = await api.text(`/api/reports/${encodeURIComponent(reportId)}/file?${q}`);
  } catch (e) { return; }                 // 기록이 아직 없으면 조용히 넘어간다
  const lines = text.split('\n').filter(Boolean);
  const shown = lines.slice(-max);
  if (!shown.length) return;
  log.textContent = '';
  logDivider(`지난 기록 ${shown.length}줄${lines.length > shown.length ? ` (전체 ${lines.length}줄 중 최근만)` : ''}`);
  shown.forEach(l => {
    let d; try { d = JSON.parse(l); } catch (e) { return; }
    appendLog({ ts: d.ts, stage: d.stage, step: d.step,
                message: d.note || d.event || '', status: d.event === 'error' ? 'failed' : '' });
  });
  logDivider('여기부터 이번 실행');
}

function appendLog(ev) {
  const log = $('#log');
  const ts = ev.ts ? new Date(ev.ts) : new Date();
  const p = n => String(n).padStart(2, '0');
  const t = isNaN(ts) ? String(ev.ts) : `${p(ts.getHours())}:${p(ts.getMinutes())}:${p(ts.getSeconds())}`;
  const cls = ev.status === 'failed' ? 'err' : ev.status === 'done' ? 'ok' : ev.status === 'skipped' ? 'skip' : '';
  const stage = ev.stage ? `<span class="st">${esc(ev.stage)}</span>` : '';
  const step = ev.step != null ? `<span class="muted">#${esc(ev.step)}</span>` : '';
  const line = el(`<span class="ln"><span class="ts">${esc(t)}</span> ${stage} ${step} <span class="${cls}">${esc(ev.message || ev.status || '')}</span></span>`);
  log.appendChild(line);
  log.appendChild(document.createTextNode('\n'));
  if ($('#logAutoscroll').checked) log.scrollTop = log.scrollHeight;
  while (log.childNodes.length > 4000) log.removeChild(log.firstChild);
}
function finishJob(status) {
  if (!state.job) return;
  state.job.status = status === 'succeeded' ? 'done' : status;
  for (const s of STAGES) {
    if (state.job.stages[s.name] === 'running') state.job.stages[s.name] = status === 'done' ? 'done' : status;
    // 끝났는데 한 번도 알려 오지 않은 단계는 이 실행에 없던 단계다
    else if (status === 'done' && !state.job.stages[s.name] && !state.job.seen[s.name]) {
      state.job.stages[s.name] = 'skipped';
      state.job.notes[s.name] = '이 실행에 없음';
    }
  }
  if (state.es) { state.es.close(); state.es = null; }
  if (state.elapsedTimer) { clearInterval(state.elapsedTimer); state.elapsedTimer = null; }
  toast(status === 'done' ? '실행이 끝났습니다. 대조표와 산출물을 확인하세요.' : status === 'cancelled' ? '실행이 취소됐습니다.' : '실행이 실패했습니다. 로그를 확인하세요.', status === 'done' ? 'ok' : 'error');
  delete state.data[state.job.report_id];
  delete state.detail[state.job.report_id];
  loadReports().catch(() => { /* ignore */ });
  renderJob();
}
function detachJob() {
  if (state.es) { state.es.close(); state.es = null; }
  if (state.elapsedTimer) { clearInterval(state.elapsedTimer); state.elapsedTimer = null; }
}
async function cancelRun() {
  if (!state.job || state.job.status !== 'running') return;
  if (!confirm('실행을 취소할까요? 현재 단계가 끝나는 지점에서 멈춥니다.')) return;
  try { await api.post(`/api/runs/${state.job.job_id}/cancel`); toast('취소 요청을 보냈습니다.'); }
  catch (e) { toast('취소 실패: ' + e.message, 'error'); }
}
function renderJob() {
  const job = state.job;
  const running = !!job && job.status === 'running';
  $('#runSubmit').disabled = running;
  $('#runCancel').disabled = !running;
  $('#jobId').textContent = job ? job.job_id : '';
  $('#jobBadge').outerHTML = job ? statusBadge(job.status).replace('<span class="pill', '<span id="jobBadge" class="pill') : '<span class="badge" id="jobBadge">대기</span>';
  $$('#stepper .step').forEach(li => {
    const name = li.dataset.stage;
    const st = job ? (job.stages[name] || '') : '';
    li.dataset.status = st;
    const note = li.querySelector('.step-note');
    if (note) {
      const why = job && job.notes ? job.notes[name] : '';
      note.textContent = st === 'skipped' ? (why ? '해당 없음' : '건너뜀') : '';
      note.title = st === 'skipped' && why ? why : '';
    }
  });
  renderTally();
}
function renderTally() {
  const job = state.job;
  $('#tallyIn').textContent = fmtInt(job ? job.tokensIn : 0);
  $('#tallyOut').textContent = fmtInt(job ? job.tokensOut : 0);
  $('#tallyCost').textContent = (job ? job.cost : 0).toFixed(4);
  if (job) {
    const end = job.status === 'running' ? Date.now() : (job.endedAt || Date.now());
    if (job.status !== 'running' && !job.endedAt) job.endedAt = Date.now();
    const s = Math.max(0, Math.floor((end - job.startedAt) / 1000));
    $('#tallyElapsed').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  } else $('#tallyElapsed').textContent = '00:00';
}

/* ------------------------------------------------------------------ */
/* 4. 결론 대조표                                                       */
/* ------------------------------------------------------------------ */
function setupTable() {
  $$('#view-table .tab').forEach(b => b.addEventListener('click', () => {
    state.tableTab = b.dataset.tab;
    $$('#view-table .tab').forEach(x => { x.classList.toggle('is-active', x === b); x.setAttribute('aria-selected', x === b); });
    closeDrawer();
    applyTableFilters();
  }));
  ['#fVerdict', '#fKind', '#fStatus', '#fAction'].forEach(s => $(s).addEventListener('change', applyTableFilters));
  $('#fSearch').addEventListener('input', applyTableFilters);
  $('#tblSummary').addEventListener('click', e => {
    const b = e.target.closest('button[data-verdict]');
    if (!b) return;
    const sel = $('#fVerdict');
    sel.value = sel.value === b.dataset.verdict ? '' : b.dataset.verdict;
    applyTableFilters();
  });
  $('#drawerClose').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
  $('#drawerToImpact').addEventListener('click', () => { state.impactFocus = state.selectedRow && state.selectedRow.conclusion_id; });
}
async function renderTable() {
  const id = state.currentId;
  const empty = $('#tblEmpty');
  const wrapC = $('#tblConclusionWrap'), wrapB = $('#tblBodyWrap');
  $('#tblSummary').innerHTML = '';
  if (!id) { empty.hidden = false; empty.textContent = '보고서가 없습니다. 「접수」에서 파일을 올려 시작하세요.'; wrapC.hidden = wrapB.hidden = true; return; }
  empty.hidden = false; empty.textContent = '불러오는 중…'; wrapC.hidden = wrapB.hidden = true;
  const d = await loadReportData(id);
  const cmp = d && d.comparison;
  if (!cmp || !Array.isArray(cmp.conclusion_rows)) { empty.textContent = notRunMessage(id); $('#tblFilters').hidden = true; return; }
  $('#tblFilters').hidden = false;
  empty.hidden = true;
  // 필터 옵션
  const rows = cmp.conclusion_rows;
  const fill = (sel, vals, label) => {
    const cur = sel.value;
    sel.innerHTML = '<option value="">전체</option>' + vals.map(v => `<option value="${esc(v)}">${esc(label ? label(v) : v)}</option>`).join('');
    sel.value = vals.includes(cur) ? cur : '';
  };
  fill($('#fVerdict'), VERDICT_ORDER.filter(v => rows.some(r => (r.verdict || '잠정') === v)));
  fill($('#fKind'), Array.from(new Set(rows.map(r => r.kind))).filter(Boolean), k => `${k} ${KIND_LABEL[k] || ''}`);
  fill($('#fStatus'), Array.from(new Set(rows.concat(cmp.body_rows || []).map(r => r.status))).filter(Boolean));
  fill($('#fAction'), Array.from(new Set(rows.map(r => r.next_action))).filter(Boolean));

  $('#tblConclusion tbody').innerHTML = rows.map((r, i) => `
    <tr class="is-clickable" data-i="${i}" data-verdict="${esc(r.verdict || '잠정')}" data-kind="${esc(r.kind || '')}" data-status="${esc(r.status || '')}" data-action="${esc(r.next_action || '')}">
      <td class="k">${esc(r.row_id)}<div class="loc">${esc(r.location || '')}</div><div><span class="chip">${esc(r.kind)} ${esc(KIND_LABEL[r.kind] || '')}</span></div></td>
      <td class="old"><div class="clamp">${esc(r.old)}</div></td>
      <td><div class="clamp">${esc(r.new)}</div></td>
      <td>${pill(r.verdict)} ${(r.reason_locus || []).map(l => `<span class="chip chip-${esc(l)}">${esc(l)}</span>`).join('')}<div class="why clamp">${esc(r.reason || '')}</div></td>
      <td>${gradeBadge(r.grade)}</td>
      <td>${esc(r.status || '—')}</td>
      <td>${esc(r.next_action || '—')}</td>
    </tr>`).join('');
  $$('#tblConclusion tbody tr').forEach(tr => tr.addEventListener('click', () => openDrawer(rows[+tr.dataset.i])));

  $('#tblBody tbody').innerHTML = (cmp.body_rows || []).map(r => `
    <tr data-verdict="" data-kind="" data-status="${esc(r.status || '')}" data-action="">
      <td class="k">${esc(r.row_id)}<div class="loc">${esc(r.location || '')}</div></td>
      <td class="old"><div class="clamp">${esc(r.old)}</div></td>
      <td><div class="clamp">${esc(r.new)}</div></td>
      <td><b>${esc(r.change_type || '')}</b><div class="why">${esc(r.reason || '')}</div></td>
      <td><ul class="ev-list">${(r.evidence || []).map(e => `<li>${gradeBadge(e.grade)} ${evidenceLink(e)}</li>`).join('')}</ul></td>
      <td>${gradeBadge(r.grade)}</td>
      <td>${esc(r.status || '')}<div class="loc">${esc((r.linked_conclusions || []).join(', '))}</div></td>
    </tr>`).join('');
  applyTableFilters();
}
function applyTableFilters() {
  const id = state.currentId, d = state.data[id], cmp = d && d.comparison;
  if (!cmp) return;
  const isC = state.tableTab === 'conclusion';
  $('#tblConclusionWrap').hidden = !isC;
  $('#tblBodyWrap').hidden = isC;
  $('#fVerdict').disabled = $('#fKind').disabled = $('#fAction').disabled = !isC;
  const f = { verdict: $('#fVerdict').value, kind: $('#fKind').value, status: $('#fStatus').value, action: $('#fAction').value };
  const q = $('#fSearch').value.trim().toLowerCase();
  const tbody = isC ? $('#tblConclusion tbody') : $('#tblBody tbody');
  let n = 0;
  $$('tr', tbody).forEach(tr => {
    let ok = true;
    if (isC) ok = (!f.verdict || tr.dataset.verdict === f.verdict) && (!f.kind || tr.dataset.kind === f.kind) && (!f.action || tr.dataset.action === f.action);
    ok = ok && (!f.status || tr.dataset.status === f.status);
    if (ok && q) ok = tr.textContent.toLowerCase().includes(q);
    tr.hidden = !ok; if (ok) n++;
  });
  $('#fCount').textContent = `${n}행 표시`;
  $('#tblSummary').innerHTML = summaryBadges(cmp.summary, { clickable: true, active: isC ? f.verdict : '' });
  const rowsTotal = isC ? cmp.conclusion_rows.length : (cmp.body_rows || []).length;
  const emptyEl = $('#tblEmpty');
  if (rowsTotal && n === 0) { emptyEl.hidden = false; emptyEl.textContent = '조건에 맞는 행이 없습니다. 필터를 풀어 보세요.'; }
  else if (!rowsTotal) { emptyEl.hidden = false; emptyEl.textContent = isC ? '결론 행이 없습니다.' : '본문 대조표 행이 없습니다.'; }
  else emptyEl.hidden = true;
}
function openDrawer(r) {
  state.selectedRow = r;
  const d = state.data[state.currentId] || {};
  $$('#tblConclusion tbody tr').forEach(tr => tr.classList.toggle('is-selected', d.comparison.conclusion_rows[+tr.dataset.i] === r));
  $('#drawerId').textContent = r.conclusion_id || r.row_id;
  $('#drawerVerdict').outerHTML = `<span id="drawerVerdict">${pill(r.verdict)} <span class="chip">${esc(r.kind)} ${esc(KIND_LABEL[r.kind] || '')}</span> ${gradeBadge(r.grade)} <span class="muted">${esc(r.status || '')} · ${esc(r.next_action || '')}</span></span>`;
  $('#drawerLoc').textContent = r.location || '';
  $('#drawerOld').textContent = r.old || '';
  $('#drawerNew').textContent = r.new || '';
  $('#drawerBlind').textContent = r.blind_new || '(블라인드 대응 항목 없음)';
  $('#drawerLocus').innerHTML = (r.reason_locus || []).map(l => `<span class="chip chip-${esc(l)}">${esc(l)} ${esc(LOCUS_LABEL[l] || '')}</span>`).join('') || '<span class="muted">—</span>';
  $('#drawerReason').textContent = r.reason || '';
  $('#drawerEvidence').innerHTML = (r.evidence || []).map(e => `<li>${gradeBadge(e.grade)}<span>${evidenceLink(e)}</span></li>`).join('') || '<li class="muted">근거 없음</li>';
  const prem = new Map(((d.chains && d.chains.premises) || []).map(p => [p.premise_id, p]));
  const claims = new Map(((d.chains && d.chains.claims) || []).map(c => [c.claim_id, c]));
  const evs = new Map((d.events || []).map(e => [e.event_id, e]));
  $('#drawerUpstream').innerHTML = (r.upstream || []).map(u => {
    if (prem.has(u)) { const p = prem.get(u); return `<li><span class="id">${esc(u)}</span><span>${esc(p.statement)} <small>${esc(p.section || '')} p.${esc(p.page ?? '')}</small></span></li>`; }
    if (evs.has(u)) { const e = evs.get(u); return `<li><span class="id ev">${esc(e.date)}</span><span>${esc(e.title)} ${gradeBadge(e.grade)}</span></li>`; }
    if (claims.has(u)) { const c = claims.get(u); return `<li><span class="id">${esc(u)}</span><span>${esc(c.statement)}</span></li>`; }
    return `<li><span class="id ${u.startsWith('E-') ? 'ev' : ''}">${esc(u)}</span><span class="muted">(사슬·사건 파일에 없음)</span></li>`;
  }).join('') || '<li class="muted">—</li>';
  $('#drawer').hidden = false;
  $('#drawerClose').focus({ preventScroll: true });
}
function closeDrawer() {
  const dr = $('#drawer');
  if (dr && !dr.hidden) { dr.hidden = true; $$('#tblConclusion tbody tr.is-selected').forEach(tr => tr.classList.remove('is-selected')); }
}

/* ------------------------------------------------------------------ */
/* 5. 영향 지도                                                          */
/* ------------------------------------------------------------------ */
const impact = { nodes: new Map(), edges: [], selected: null };
function setupImpact() {
  $('#impactReset').addEventListener('click', () => selectImpactNode(null));
}
async function renderImpact() {
  const id = state.currentId, empty = $('#impactEmpty'), svg = $('#impactSvg');
  svg.innerHTML = ''; empty.hidden = false; empty.textContent = '불러오는 중…';
  $('#impactDetailBody').hidden = true; $('#impactDetailEmpty').hidden = false;
  if (!id) { empty.textContent = '보고서가 없습니다.'; return; }
  const d = await loadReportData(id);
  if (!d || !d.chains) { empty.textContent = notRunMessage(id); return; }
  empty.hidden = true;
  buildImpactGraph(d);
  drawImpact();
  if (state.impactFocus) { selectImpactNode(state.impactFocus); state.impactFocus = null; }
}
function buildImpactGraph(d) {
  const nodes = new Map(), edges = [], edgeKeys = new Set();
  const addEdge = (from, to, kind) => {
    const k = `${from}>${to}`;
    if (!nodes.has(from) || !nodes.has(to) || edgeKeys.has(k)) return;
    edgeKeys.add(k); edges.push({ from, to, kind });
  };
  const rows = (d.comparison && d.comparison.conclusion_rows) || [];
  const rowBy = new Map(rows.map(r => [r.conclusion_id, r]));
  // 사건
  const events = (d.events || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  for (const e of events) nodes.set(e.event_id, { id: e.event_id, col: 0, label: e.title, sub: e.date, cls: `e-${e.grade === 'A' ? 'good' : e.grade === 'B' ? 'warn' : 'na'}`, data: e, type: 'event' });
  // 전제
  const premEffect = new Map();
  for (const pv of d.provisional || []) for (const h of pv.hit_premises || []) {
    const c = EFFECT_CLASS[h.effect] || 'na';
    const rank = { bad: 3, warn: 2, good: 1, na: 0 };
    if ((rank[c] || 0) > (rank[premEffect.get(h.premise_id)] || 0) || !premEffect.has(h.premise_id)) premEffect.set(h.premise_id, c);
  }
  for (const p of d.chains.premises || []) nodes.set(p.premise_id, { id: p.premise_id, col: 1, label: p.indicator || p.statement, sub: p.premise_id, cls: `e-${premEffect.get(p.premise_id) || 'na'}`, data: p, type: 'premise' });
  // 결론·제언
  const vclass = cid => { const r = rowBy.get(cid); return r ? `v-${VERDICT_CLASS[r.verdict || '잠정'] || 'na'}` : 'v-prov'; };
  for (const c of d.chains.conclusions || []) {
    const r = rowBy.get(c.conclusion_id);
    nodes.set(c.conclusion_id, { id: c.conclusion_id, col: c.kind === 'R' ? 3 : 2, label: (r && r.old) || c.statement, sub: c.conclusion_id.replace(/^R\d+-/, ''), cls: vclass(c.conclusion_id), data: { chain: c, row: r }, type: 'conclusion' });
  }
  for (const r of rows) if (!nodes.has(r.conclusion_id)) {
    nodes.set(r.conclusion_id, { id: r.conclusion_id, col: r.kind === 'R' ? 3 : 2, label: r.new, sub: r.row_id, cls: vclass(r.conclusion_id), data: { chain: null, row: r }, type: 'conclusion' });
  }
  impact.nodes = nodes;
  // 간선: 사건→전제 (provisional hit_premises)
  for (const pv of d.provisional || []) for (const h of pv.hit_premises || []) for (const eid of h.event_ids || []) addEdge(eid, h.premise_id, 'e-p');
  // 간선: 전제→결론, 결론→결론 (chains.edges)
  for (const e of d.chains.edges || []) {
    if (nodes.has(e.from) && nodes.has(e.to)) addEdge(e.from, e.to, nodes.get(e.from).type === 'conclusion' ? 'k-k' : 'p-k');
  }
  // 간선: 대조표 upstream (전제·사건 → 결론)
  for (const r of rows) for (const u of r.upstream || []) {
    if (u.startsWith('P-')) addEdge(u, r.conclusion_id, 'p-k');
    else if (u.startsWith('E-')) addEdge(u, r.conclusion_id, 'e-k');
  }
  impact.edges = edges;
  impact.selected = null;
}
function drawImpact() {
  const svg = $('#impactSvg');
  const cols = [[], [], [], []];
  for (const n of impact.nodes.values()) cols[n.col].push(n);
  cols[2].sort((a, b) => a.id.localeCompare(b.id)); cols[3].sort((a, b) => a.id.localeCompare(b.id));
  const W = 250, GAP = 78, H = 32, PAD = 20, TOP = 44;
  const maxN = Math.max(1, ...cols.map(c => c.length));
  const height = TOP + maxN * (H + 8) + PAD;
  const width = PAD * 2 + 4 * W + 3 * GAP;
  const colX = i => PAD + i * (W + GAP);
  const titles = ['사건 (L0)', '전제', '결론', '제언'];
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width); svg.setAttribute('height', height);
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; return e; };
  // 위치
  cols.forEach((list, ci) => {
    const span = height - TOP - PAD, step = span / Math.max(1, list.length);
    list.forEach((n, i) => { n.x = colX(ci); n.y = TOP + i * step + (step - H) / 2; n.w = W; n.h = H; });
  });
  const gE = mk('g', { class: 'edges' }), gN = mk('g', { class: 'nodes' });
  titles.forEach((t, i) => svg.appendChild(mk('text', { x: colX(i), y: 22, class: 'col-title' }, `${t} · ${cols[i].length}`)));
  for (const e of impact.edges) {
    const a = impact.nodes.get(e.from), b = impact.nodes.get(e.to);
    if (!a || !b || a.x == null || b.x == null) continue;
    let dPath;
    if (a.col === b.col) {
      const x = a.x + a.w, y1 = a.y + a.h / 2, y2 = b.y + b.h / 2, bulge = 46;
      dPath = `M${x},${y1} C${x + bulge},${y1} ${x + bulge},${y2} ${x},${y2}`;
    } else {
      const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2, mx = (x1 + x2) / 2;
      dPath = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    }
    const p = mk('path', { d: dPath, class: `edge ${e.kind}`, 'data-from': e.from, 'data-to': e.to });
    gE.appendChild(p);
  }
  for (const n of impact.nodes.values()) {
    const g = mk('g', { class: `node ${n.cls}`, 'data-id': n.id, tabindex: 0, role: 'button' });
    g.appendChild(mk('rect', { x: n.x, y: n.y, width: n.w, height: n.h }));
    if (n.type !== 'conclusion') g.appendChild(mk('rect', { x: n.x, y: n.y, width: 4, height: n.h, class: 'strip', rx: 2 }));
    g.appendChild(mk('text', { x: n.x + 10, y: n.y + 12, class: 'id' }, truncate(n.sub || '', 30)));
    g.appendChild(mk('text', { x: n.x + 10, y: n.y + 25 }, truncate(n.label || '', 34)));
    g.appendChild(mk('title', {}, `${n.sub || n.id}\n${n.label || ''}`));
    g.addEventListener('click', () => selectImpactNode(n.id));
    g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); selectImpactNode(n.id); } });
    gN.appendChild(g);
  }
  svg.appendChild(gE); svg.appendChild(gN);
}
function selectImpactNode(id) {
  const svg = $('#impactSvg');
  impact.selected = id;
  const on = new Set();
  if (id) {
    on.add(id);
    for (const e of impact.edges) { if (e.from === id) on.add(e.to); if (e.to === id) on.add(e.from); }
  }
  svg.classList.toggle('has-focus', !!id);
  $$('.node', svg).forEach(g => { g.classList.toggle('is-selected', g.dataset.id === id); g.classList.toggle('is-on', on.has(g.dataset.id)); });
  $$('.edge', svg).forEach(p => p.classList.toggle('is-on', !!id && (p.dataset.from === id || p.dataset.to === id)));
  renderImpactDetail(id, on);
  if (id) { const g = $(`.node[data-id="${CSS.escape(id)}"]`, svg); if (g && g.scrollIntoView) g.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
}
function renderImpactDetail(id, on) {
  const body = $('#impactDetailBody'), emp = $('#impactDetailEmpty');
  if (!id || !impact.nodes.has(id)) { body.hidden = true; emp.hidden = false; return; }
  const n = impact.nodes.get(id);
  const link = nid => { const m = impact.nodes.get(nid); return m ? `<li><button type="button" class="link" data-go="${esc(nid)}">${esc(m.sub || nid)}</button> ${esc(truncate(m.label, 40))}</li>` : ''; };
  const linked = Array.from(on).filter(x => x !== id);
  let html = '';
  if (n.type === 'event') {
    const e = n.data;
    html = `<h3>${esc(e.title)}</h3>
      <div class="kv"><span>일자</span><span class="num">${esc(e.date)}</span><span>도메인</span><span>${esc(DOMAIN_LABEL[e.domain] || e.domain)}</span><span>등급</span><span>${gradeBadge(e.grade)}</span></div>
      <p>${esc(e.summary)}</p>
      ${e.affected_indicators ? `<p class="muted">영향 지표: ${esc(e.affected_indicators.join(' · '))}</p>` : ''}
      <ul>${(e.sources || []).map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a></li>`).join('')}</ul>`;
  } else if (n.type === 'premise') {
    const p = n.data;
    const hits = [];
    for (const pv of (state.data[state.currentId] || {}).provisional || []) for (const h of pv.hit_premises || []) if (h.premise_id === id) hits.push({ c: pv.conclusion_id, h });
    html = `<h3>${esc(p.premise_id)} · ${esc(p.indicator || '')}</h3>
      <p>${esc(p.statement)}</p>
      <div class="kv"><span>위치</span><span>${esc(p.section || '')} p.${esc(p.page ?? '')}(인쇄 p.${esc(p.printed_page ?? '')})</span></div>
      ${hits.length ? `<h3>사건이 미친 영향</h3><ul>${hits.map(x => `<li><b class="pill p-${EFFECT_CLASS[x.h.effect] || 'na'}">${esc(x.h.effect)}</b> <span class="mono">${esc(x.c.replace(/^R\d+-/, ''))}</span> — ${esc(x.h.why)}</li>`).join('')}</ul>` : ''}`;
  } else {
    const { chain, row } = n.data;
    html = `<h3>${esc(n.sub)} ${row ? pill(row.verdict) : '<span class="pill p-prov">잠정</span>'}</h3>
      ${chain ? `<p>${esc(chain.statement)}</p><div class="kv"><span>방법</span><span>${esc(chain.method || '—')}</span><span>재수행 등급</span><span>${esc(chain.rerun_grade || '—')}</span><span>위치</span><span>p.${esc(chain.page ?? '')}(인쇄 p.${esc(chain.printed_page ?? '')})</span></div>` : ''}
      ${row ? `<h3>현행화(안)</h3><p>${esc(row.new)}</p><p class="muted">${esc((row.reason_locus || []).map(l => LOCUS_LABEL[l] || l).join('·'))} · ${esc(row.next_action || '')} · ${esc(row.status || '')}</p>` : ''}`;
  }
  html += `<h3>연결 (${linked.length})</h3><ul>${linked.map(link).join('') || '<li class="muted">없음</li>'}</ul>`;
  if (n.type === 'conclusion' && n.data.row) html += `<div class="form-actions"><a class="btn btn-sm" href="#table" data-open="${esc(n.data.row.conclusion_id)}">대조표에서 열기</a></div>`;
  body.innerHTML = html; body.hidden = false; emp.hidden = true;
  $$('[data-go]', body).forEach(b => b.addEventListener('click', () => selectImpactNode(b.dataset.go)));
  $$('[data-open]', body).forEach(a => a.addEventListener('click', () => {
    const cid = a.dataset.open;
    setTimeout(() => { const r = ((state.data[state.currentId] || {}).comparison || {}).conclusion_rows.find(x => x.conclusion_id === cid); if (r) openDrawer(r); }, 250);
  }));
}

/* ------------------------------------------------------------------ */
/* 6. 산출물                                                            */
/* ------------------------------------------------------------------ */
function setupOutputs() {
  $$('#view-outputs .tab').forEach(b => b.addEventListener('click', () => {
    state.outTab = b.dataset.out;
    $$('#view-outputs .tab').forEach(x => { x.classList.toggle('is-active', x === b); x.setAttribute('aria-selected', x === b); });
    renderOutputs();
  }));
}
async function renderOutputs() {
  const id = state.currentId, empty = $('#outEmpty'), frame = $('#outFrame');
  frame.hidden = true; empty.hidden = false; empty.textContent = '불러오는 중…';
  $('#outFiles').innerHTML = ''; $('#outFilesEmpty').hidden = true;
  if (!id) { empty.textContent = '보고서가 없습니다.'; return; }
  let det;
  try { det = await loadReportDetail(id); } catch (e) { empty.textContent = '보고서 정보를 읽지 못했습니다: ' + e.message; return; }
  const path = state.outTab === 'report' ? '07_report/report.html' : '07_report/comparison_table.html';
  const url = `/api/reports/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`;
  const files = det.files || [];
  const has = det.has || {};
  const exists = files.some(f => f.path === path) || (state.outTab === 'report' ? has.report : has.comparison);
  const openA = $('#outOpenNew'), dlA = $('#outDownload');
  if (IS_MOCK) { openA.setAttribute('aria-disabled', 'true'); openA.title = '모의 모드에서는 새 창 열기를 지원하지 않습니다'; dlA.setAttribute('aria-disabled', 'true'); openA.href = dlA.href = '#outputs'; }
  else { openA.href = url; dlA.href = url + '&download=1'; dlA.download = path.split('/').pop(); }
  if (!exists) {
    empty.textContent = state.outTab === 'report'
      ? `${id}의 현행화 보고서가 아직 없습니다. 「실행」에서 report 단계까지 돌리면 생성됩니다.`
      : `${id}의 대조표 HTML이 아직 없습니다. 「실행」에서 report 단계까지 돌리면 생성됩니다.`;
  } else {
    try {
      const html = await api.text(url);
      frame.srcdoc = html; frame.hidden = false; empty.hidden = true;
    } catch (e) { empty.textContent = '파일을 읽지 못했습니다: ' + e.message; }
  }
  renderFileList(id, files);
}
function renderFileList(id, files) {
  const groups = [
    ['보고서', f => f.startsWith('07_report/')],
    ['블라인드 브리프', f => f.startsWith('L2/blind_input/')],
    ['블라인드 산출', f => f.startsWith('L2/blind_output/')],
    ['검토 노트', f => f.startsWith('L2/compare/') || f.endsWith('critic_notes.md')],
    ['설계서', f => f.startsWith('L3/')],
    ['판정·검증', f => f.startsWith('L0/') || f.startsWith('L1/') || f.startsWith('L2/traced/') || f === 'comparison_table.json'],
    ['논증 사슬·분류', f => /^0[123]_/.test(f)],
    ['로그', f => f.startsWith('logs/')],
    ['원문', f => f.startsWith('00_source/')],
    ['기타', () => true],
  ];
  const used = new Set();
  let html = '';
  for (const [name, pred] of groups) {
    const list = files.filter(f => !used.has(f.path) && pred(f.path));
    if (!list.length) continue;
    list.forEach(f => used.add(f.path));
    html += `<div class="file-group"><h3>${esc(name)}</h3><ul class="file-list">${list.map(f => {
      const u = `/api/reports/${encodeURIComponent(id)}/file?path=${encodeURIComponent(f.path)}&download=1`;
      return `<li><span class="path" title="${esc(f.path)}${f.mtime ? ' · ' + esc(fmtDate(f.mtime)) : ''}">${esc(f.path)}</span><span class="size">${fmtBytes(f.size)}</span>${IS_MOCK ? '<span class="muted">내려받기</span>' : `<a class="dl" href="${esc(u)}" download="${esc(f.path.split('/').pop())}">내려받기</a>`}</li>`;
    }).join('')}</ul></div>`;
  }
  $('#outFiles').innerHTML = html;
  $('#outFilesEmpty').hidden = files.length > 0;
  $('#outFilesEmpty').textContent = '서랍에 파일이 없습니다.';
}

/* ------------------------------------------------------------------ */
/* 7. 지식베이스                                                        */
/* ------------------------------------------------------------------ */
function setupKb() {
  $('#kbDomain').addEventListener('change', () => renderKb(true));
  $('#kbSearch').addEventListener('input', () => renderKbList());
}
async function renderKb(refetch = false) {
  const sel = $('#kbDomain'), empty = $('#kbEmpty');
  if (!state.kbEvents || refetch) {
    empty.hidden = false; empty.textContent = '불러오는 중…'; $('#kbTimeline').innerHTML = '';
    const dom = sel.value;
    try { state.kbEvents = await api.get(`/api/kb/events${dom ? '?domain=' + encodeURIComponent(dom) : ''}`); }
    catch (e) { empty.textContent = '사건을 읽지 못했습니다: ' + e.message; return; }
    const domains = new Set(Object.keys(DOMAIN_LABEL));
    (state.kbEvents || []).forEach(e => e.domain && domains.add(e.domain));
    const cur = sel.value;
    sel.innerHTML = '<option value="">전체</option>' + Array.from(domains).map(d => `<option value="${esc(d)}">${esc(DOMAIN_LABEL[d] || d)}</option>`).join('');
    sel.value = cur;
  }
  renderKbList();
}
function renderKbList() {
  const q = $('#kbSearch').value.trim().toLowerCase();
  const dom = $('#kbDomain').value;
  const list = (state.kbEvents || []).filter(e => (!dom || e.domain === dom) && (!q || `${e.title} ${e.summary}`.toLowerCase().includes(q)))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  $('#kbCount').textContent = `${list.length}건`;
  const empty = $('#kbEmpty');
  if (!list.length) { empty.hidden = false; empty.textContent = state.kbEvents && state.kbEvents.length ? '조건에 맞는 사건이 없습니다.' : '기록된 사건이 없습니다. 실행(delta 단계)이 끝나면 kb/events/에 쌓입니다.'; $('#kbTimeline').innerHTML = ''; return; }
  empty.hidden = true;
  let year = null, html = '';
  for (const e of list) {
    const y = String(e.date || '').slice(0, 4);
    if (y !== year) { year = y; html += `<li class="tl-year">${esc(y || '연도 미상')}</li>`; }
    html += `<li class="tl-item g-${esc(e.grade || 'C')}">
      <div class="tl-head"><span class="tl-date">${esc(e.date)}</span><span class="tl-title">${esc(e.title)}</span><span class="tl-domain">${esc(DOMAIN_LABEL[e.domain] || e.domain || '')}</span>${gradeBadge(e.grade)}</div>
      <p class="tl-summary">${esc(e.summary || '')}</p>
      ${e.affected_indicators && e.affected_indicators.length ? `<div class="tl-ind">영향 지표: ${esc(e.affected_indicators.join(' · '))}</div>` : ''}
      <ul class="tl-src">${(e.sources || []).map(s => typeof s === 'string' ? `<li><a href="${esc(s)}" target="_blank" rel="noopener">${esc(s)}</a></li>` : `<li><a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.url)}">${esc(s.title || s.url)}</a>${s.retrieved_at ? ` <small>조회 ${esc(s.retrieved_at)}</small>` : ''}</li>`).join('')}</ul>
    </li>`;
  }
  $('#kbTimeline').innerHTML = html;
}

/* ------------------------------------------------------------------ */
/* 8. 설정                                                              */
/* ------------------------------------------------------------------ */
function setupSettings() {
  $('#envForm').addEventListener('submit', saveEnv);
  $('#settingsForm').addEventListener('submit', saveSettings);
  $('#doctorBtn').addEventListener('click', () => runDoctor());
  $('#dashDoctorBtn').addEventListener('click', async () => { await runDoctor(); renderDashStatus(); });
  $('#modelsRefresh').addEventListener('click', async () => { await loadModels(true); fillModelSelects(); toast(`모델 ${state.models.length}개 조회`, 'ok'); });
  $('#setModelSearch').addEventListener('input', fillModelSelects);
}
async function renderSettings() {
  try { state.settings = await api.get('/api/settings'); }
  catch (e) { $('#envTable tbody').innerHTML = `<tr><td colspan="2" class="empty is-error">설정을 읽지 못했습니다: ${esc(e.message)}</td></tr>`; return; }
  const { settings, env, env_keys } = state.settings;
  const keys = env_keys && env_keys.length ? env_keys : Object.keys(env || {});
  $('#envTable tbody').innerHTML = keys.map(k => {
    const cur = env && env[k];
    return `<tr><td>${esc(k)}</td><td>
      <span class="cur ${cur ? '' : 'is-empty'}">${cur ? esc(cur) : '(없음)'}</span>
      <input type="password" name="${esc(k)}" placeholder="새 값 입력 (비우면 유지)" autocomplete="new-password" spellcheck="false">
      <label class="check check-sm" style="margin-top:4px"><input type="checkbox" name="del:${esc(k)}"> 이 키 삭제</label>
    </td></tr>`;
  }).join('') || '<tr><td colspan="2" class="empty">허용된 키 이름이 없습니다.</td></tr>';
  $('#setProvider').value = settings.search_provider || 'auto';
  $('#setTemp').value = settings.temperature ?? 0.2;
  $('#setSteps').value = settings.max_steps ?? 25;
  $('#setMaxChars').value = settings.max_source_chars ?? 120000;
  $('#setLang').value = settings.language || 'ko';
  await loadModels();
  fillModelSelects();
  if (state.doctor) renderDoctorTable();
}
function fillModelSelects() {
  const s = (state.settings && state.settings.settings) || {};
  const q = $('#setModelSearch').value.trim().toLowerCase();
  const list = state.models.filter(m => !q || `${m.id} ${m.name || ''}`.toLowerCase().includes(q));
  $('#setModelCount').textContent = state.models.length ? `${list.length}/${state.models.length}개` : '모델 목록이 비어 있습니다. 키를 저장한 뒤 「모델 목록 다시 조회」를 누르세요.';
  const fmtPrice = p => p == null || p === '' ? '' : ` · $${(Number(p) * 1e6).toFixed(2)}/M`;
  const opt = m => `<option value="${esc(m.id)}">${esc(m.name || m.id)} (${esc(m.id)})${m.context_length ? ' · ' + fmtInt(m.context_length) : ''}${fmtPrice(m.prompt_price)}</option>`;
  const ensure = (id) => id && !list.some(m => m.id === id) ? `<option value="${esc(id)}">${esc(id)} (목록에 없음)</option>` : '';
  const sm = $('#setModel'), sc = $('#setModelCheap');
  sm.innerHTML = ensure(s.model) + list.map(opt).join('');
  sm.value = s.model || (list[0] && list[0].id) || '';
  sc.innerHTML = '<option value="">(현재 모델과 같게)</option>' + ensure(s.model_cheap) + list.map(opt).join('');
  sc.value = s.model_cheap || '';
}
async function saveEnv(e) {
  e.preventDefault();
  const env = {};
  $$('#envTable input[type=password]').forEach(i => { if (i.value.trim()) env[i.name] = i.value.trim(); });
  $$('#envTable input[type=checkbox]:checked').forEach(c => { env[c.name.slice(4)] = ''; });
  if (!Object.keys(env).length) { toast('바뀐 값이 없습니다.'); return; }
  try {
    state.settings = await api.put('/api/settings', { settings: {}, env });
    toast('키를 저장했습니다.', 'ok');
    state.doctor = null; state.models = [];
    await renderSettings();
  } catch (err) { toast('저장 실패: ' + err.message, 'error'); }
}
async function saveSettings(e) {
  e.preventDefault();
  const settings = {
    model: $('#setModel').value, model_cheap: $('#setModelCheap').value,
    search_provider: $('#setProvider').value, temperature: parseFloat($('#setTemp').value) || 0,
    max_steps: parseInt($('#setSteps').value, 10) || 25, max_source_chars: parseInt($('#setMaxChars').value, 10) || 120000,
    language: $('#setLang').value,
  };
  try {
    state.settings = await api.put('/api/settings', { settings, env: {} });
    toast('설정을 저장했습니다.', 'ok');
    state.doctor = null;
  } catch (err) { toast('저장 실패: ' + err.message, 'error'); }
}
async function runDoctor() {
  const btns = [$('#doctorBtn'), $('#dashDoctorBtn')];
  btns.forEach(b => { b.disabled = true; b.textContent = '확인 중…'; });
  try { await loadDoctor(true); renderDoctorTable(); toast('연결 확인을 마쳤습니다.', 'ok'); }
  catch (e) { toast('연결 확인 실패: ' + e.message, 'error'); }
  finally { btns.forEach(b => { b.disabled = false; b.textContent = '연결 확인'; }); }
}
function renderDoctorTable() {
  const d = state.doctor; if (!d) return;
  const okb = (ok, configured) => ok === true ? '<span class="pill p-good">정상</span>' : ok === false ? '<span class="pill p-bad">실패</span>' : configured === false ? '<span class="pill p-na">키 없음</span>' : '<span class="pill p-na">미확인</span>';
  const yn = v => v ? '<span class="pill p-good">예</span>' : '<span class="pill p-na">아니오</span>';
  const rows = [];
  rows.push(`<tr class="row-group"><td colspan="8">LLM · 검색</td></tr>`);
  rows.push(`<tr><td>LLM</td><td><code>${esc(d.llm && d.llm.model)}</code></td><td>—</td><td>chat</td><td><code>OPENROUTER_API_KEY</code></td><td>—</td><td>${okb(d.llm && d.llm.ok)}</td><td class="muted">${esc(d.llm && d.llm.detail || '')}</td></tr>`);
  rows.push(`<tr><td>검색</td><td><code>${esc(d.search && d.search.provider)}</code></td><td>—</td><td>web</td><td>—</td><td>—</td><td>${okb(d.search && d.search.ok)}</td><td class="muted">${esc(d.search && d.search.detail || '')}</td></tr>`);
  rows.push(`<tr class="row-group"><td colspan="8">근거 소스 (${(d.sources || []).length})</td></tr>`);
  for (const s of d.sources || []) {
    rows.push(`<tr><td>소스</td><td><code>${esc(s.name)}</code></td><td>${esc(s.tier || '')}</td><td>${esc(s.kind || '')}</td><td class="k">${(s.env_vars || []).map(v => `<code>${esc(v)}</code>`).join(' ') || '<span class="muted">불필요</span>'}</td><td>${yn(s.configured)}${s.implemented === false ? ' <span class="pill p-na">미구현</span>' : ''}</td><td>${okb(s.ok, s.configured)}</td><td class="muted">${esc(s.detail || '')}</td></tr>`);
  }
  rows.push(`<tr class="row-group"><td colspan="8">파서</td></tr>`);
  for (const k of Object.keys(d.parsers || {})) rows.push(`<tr><td>파서</td><td><code>${esc(k)}</code></td><td>—</td><td>parser</td><td>—</td><td>${yn(d.parsers[k])}</td><td>${d.parsers[k] ? '<span class="pill p-good">사용 가능</span>' : '<span class="pill p-na">없음</span>'}</td><td class="muted">${esc(k === 'hwp' ? 'pyhwp(hwp5txt) 필요' : 'markitdown 또는 python-docx')}</td></tr>`);
  $('#doctorTable tbody').innerHTML = rows.join('');
  $('#doctorTable').hidden = false; $('#doctorEmpty').hidden = true;
  $('#doctorAt').textContent = state.doctorAt ? `확인 시각 ${fmtDate(state.doctorAt.toISOString())}` : '';
}

/* ------------------------------------------------------------------ */
/* 초기화                                                               */
/* ------------------------------------------------------------------ */
async function init() {
  $('#mockBadge').hidden = !IS_MOCK;
  $('#reportSelect').addEventListener('change', e => setCurrentReport(e.target.value));
  setupIntake(); setupRun(); setupTable(); setupImpact(); setupOutputs(); setupKb(); setupSettings();
  window.addEventListener('hashchange', route);
  await loadHealth();
  try { await loadReports(); }
  catch (e) { toast('보고서 목록을 읽지 못했습니다: ' + e.message, 'error'); }
  if (!location.hash) location.hash = '#dashboard';
  await route();
}
document.addEventListener('DOMContentLoaded', init);
})();

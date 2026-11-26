// Bol-ke-Order frontend: voice in, read-back out, nothing saved until "haan, pakka".
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const IS_ANDROID = /Android/i.test(navigator.userAgent);
const SILENCE_MS = 8000;
const LOW_CONFIDENCE = 0.4;

const state = { cfg: null, draft: null, blob: null, blobName: null, order: null, dispatch: null, autoTimer: null };

// ------------------------------------------------------------------ network
async function api(path, opts = {}, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(path, opts);
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (r.status >= 500 && r.status < 502 && i < tries - 1) { await sleep(800 * (i + 1)); continue; }
        const e = new Error(data.detail || data.message || `HTTP ${r.status}`);
        e.status = r.status; e.data = data; throw e;
      }
      return data;
    } catch (e) {
      if (e.status) throw e;
      if (i === tries - 1) { e.network = true; throw e; }
      await sleep(800 * (i + 1)); // network blip: wait and retry
    }
  }
}
const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function toast(msg, ms = 3000) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add('hidden'), ms);
}

// ---------------------------------------------------------------------- TTS
let voices = [];
if ('speechSynthesis' in window) {
  const load = () => { voices = speechSynthesis.getVoices(); };
  load(); speechSynthesis.onvoiceschanged = load;
}
function speak(text) {
  return new Promise((resolve) => {
    if (!text || !('speechSynthesis' in window)) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = voices.find((x) => x.lang === 'hi-IN') || voices.find((x) => x.lang === 'en-IN');
    if (v) u.voice = v;
    u.lang = v ? v.lang : 'hi-IN';
    u.rate = 1.02;
    u.onend = resolve; u.onerror = resolve;
    speechSynthesis.speak(u);
    setTimeout(resolve, 12000); // never hang if the engine is silent
  });
}

// ----------------------------------------------------------- speech capture
// Starts browser speech recognition (+ a recording kept for retries).
function startCapture({ onInterim, onAutoStop }) {
  const ctl = { finals: [], conf: [], interim: '', blob: null, autoStop: false, prompted: false, stopping: false };
  let rec = null, recorder = null, chunks = [], stream = null, silenceTimer = null, quietTimer = null;

  const resetSilence = () => {
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(async () => {
      if (ctl.stopping) return;
      if (!ctl.prompted) { // prompt once, gently
        ctl.prompted = true;
        onInterim && onInterim('… Boliye, main sun raha hoon.');
        await speak('Boliye, main sun raha hoon.');
        resetSilence();
      } else if (ctl.autoStop) onAutoStop && onAutoStop();
    }, SILENCE_MS);
  };

  const wantRecorder = !SR || !IS_ANDROID; // Android Chrome can't share the mic with SR
  if (wantRecorder && navigator.mediaDevices && window.MediaRecorder) {
    ctl.recorderReady = navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
      stream = s; recorder = new MediaRecorder(s);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.start();
    }).catch(() => toast('Mic permission chahiye'));
  }

  if (SR) {
    rec = new SR();
    rec.lang = localStorage.getItem('bko-lang') || 'hi-IN';
    rec.interimResults = true; rec.continuous = true;
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) { ctl.finals.push(r[0].transcript); ctl.conf.push(r[0].confidence || 0); }
        else interim += r[0].transcript;
      }
      ctl.interim = interim;
      onInterim && onInterim((ctl.finals.join(' ') + ' ' + interim).trim());
      resetSilence();
      if (ctl.autoStop) { // tap mode: stop after a short pause once something was said
        clearTimeout(quietTimer);
        quietTimer = setTimeout(() => ctl.finals.length && !ctl.stopping && onAutoStop && onAutoStop(), 1800);
      }
    };
    rec.onerror = (e) => { if (e.error === 'not-allowed') toast('Mic permission chahiye'); };
    rec.onend = () => { if (!ctl.stopping) { try { rec.start(); } catch (_) {} } }; // Chrome stops on pauses
    try { rec.start(); } catch (_) {}
  }
  resetSilence();

  ctl.stop = async () => {
    ctl.stopping = true;
    clearTimeout(silenceTimer); clearTimeout(quietTimer);
    if (rec) { try { rec.stop(); } catch (_) {} }
    if (ctl.recorderReady) await ctl.recorderReady;
    if (recorder && recorder.state !== 'inactive') {
      await new Promise((res) => { recorder.onstop = res; recorder.stop(); });
      ctl.blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
    }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    await sleep(SR ? 350 : 0); // let the last final result arrive
    const text = (ctl.finals.join(' ') + ' ' + (ctl.interim || '')).trim();
    const conf = ctl.conf.length ? ctl.conf.reduce((a, b) => a + b, 0) / ctl.conf.length : null;
    return { text, conf, blob: ctl.blob };
  };
  return ctl;
}

// Hold to speak, or tap once to start and it stops by itself after you finish.
function bindMic(btn, { onInterim, onResult }) {
  let ctl = null, t0 = 0, mode = null;
  const begin = (m) => {
    window.speechSynthesis?.cancel();
    ctl = startCapture({ onInterim, onAutoStop: finish });
    mode = m; ctl.autoStop = m === 'toggle';
    btn.classList.add('listening');
  };
  async function finish() {
    if (!ctl) return;
    const c = ctl; ctl = null; mode = null;
    btn.classList.remove('listening');
    onResult(await c.stop());
  }
  btn.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    if (ctl && mode === 'toggle') return finish();
    t0 = Date.now(); begin('hold');
  });
  const up = () => {
    if (!ctl || mode !== 'hold') return;
    if (Date.now() - t0 < 400) { mode = 'toggle'; ctl.autoStop = true; } else finish();
  };
  btn.addEventListener('pointerup', up);
  btn.addEventListener('pointercancel', up);
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
  return { listen: () => { if (!ctl) begin('toggle'); }, busy: () => !!ctl };
}

// ------------------------------------------------------------------ screens
function show(name) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === `screen-${name}`));
  window.scrollTo(0, 0);
  if (name === 'home') loadOrders();
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ------------------------------------------------------------ order capture
async function handleCaptured(res, source) {
  state.blob = res.blob || state.blob;
  state.blobName = res.blob ? 'mic.webm' : state.blobName;
  if (!SR && res.blob) return sendRecording(); // no browser speech: server does it
  const unclear = !res.text || res.text.split(/\s+/).length < 2 || (res.conf !== null && res.conf > 0 && res.conf < LOW_CONFIDENCE);
  showTranscript(res.text, unclear);
}

function showTranscript(text, unclear, statusMsg) {
  show('transcript');
  $('trText').value = text || '';
  const st = $('trStatus');
  if (unclear) {
    st.className = 'status bad'; st.textContent = 'Awaaz saaf nahi aayi, dobara bolein. (Recording rakhi hai)';
    speak('Awaaz saaf nahi aayi, dobara bolein.');
  } else {
    st.className = 'status info'; st.textContent = statusMsg || 'Samajh raha hoon…';
  }
  const audio = $('trAudio');
  if (state.blob) { audio.src = URL.createObjectURL(state.blob); audio.classList.remove('hidden'); } else audio.classList.add('hidden');
  $('trRetry').classList.toggle('hidden', !(state.blob && state.cfg?.server_stt));
  clearTimeout(state.autoTimer);
  if (!unclear && text) state.autoTimer = setTimeout(parseTranscript, 1200); // continue hands-free
}

async function sendRecording() {
  if (!state.blob) return;
  show('transcript');
  $('trText').value = '';
  const st = $('trStatus');
  st.className = 'status info'; st.textContent = 'Recording bhej rahe hain… lambi recording parts mein chalti hai.';
  $('trRetry').classList.add('hidden');
  const fd = new FormData();
  fd.append('file', state.blob, state.blobName || 'audio.webm');
  try {
    const r = await api('/api/transcribe', { method: 'POST', body: fd });
    showTranscript(r.transcript, r.unclear, `Suna: ${r.seconds}s audio, ${r.chunks} part(s).`);
  } catch (e) {
    st.className = 'status bad';
    if (e.data?.error === 'key_not_set') st.textContent = 'Speech key not set on server (SARVAM_API_KEY). Type the order, or use live mic in Chrome.';
    else if (e.network) st.textContent = 'Network nahi hai. Recording rakhi hai — "Send again" dabayein.';
    else st.textContent = e.message;
    $('trRetry').classList.toggle('hidden', !state.blob);
  }
}

async function parseTranscript() {
  clearTimeout(state.autoTimer);
  const text = $('trText').value.trim();
  if (!text) return toast('Pehle order bolein ya likhein');
  try {
    const d = await post('/api/parse', { text });
    state.draft = d;
    if (d.notice === 'unclear') return showTranscript(text, true);
    renderConfirm(true);
  } catch (e) {
    toast(e.network ? 'Network nahi hai, dobara try karein' : e.message);
  }
}

// ---------------------------------------------------------------- confirm
function lineHtml(ln) {
  const qty = ln.qty !== null && ln.qty !== undefined ? ln.qty : (ln.qty_alts.length ? ln.qty_alts.join(' / ') : '?');
  const name = ln.item ? ln.item.name : (ln.group ? `${ln.group}?` : (ln.item_text || '?'));
  const flag = ln.uncertain ? '<div class="flag">⚠ Pakka nahi hoon.</div>' : '';
  return `<div class="line ${ln.uncertain ? 'unsure' : ''}">
    <div class="qty">${esc(qty)}<small>${esc(ln.unit || '')}</small></div>
    <div class="name">${esc(name)}${ln.item ? ` <small>(${esc(ln.item.code)})</small>` : ''}</div>
    <div class="heard-as">heard: "${esc(ln.heard)}"</div>${flag}</div>`;
}

let answerMic;
function renderConfirm(speakIt) {
  const d = state.draft;
  show('confirm');
  $('cfHeard').textContent = d.heard;
  $('cfParty').innerHTML = d.party.status === 'ok' ? esc(d.party.party.name) : '<span class="miss">Party ?</span>';
  $('cfDate').innerHTML = d.delivery ? `Delivery: ${esc(d.delivery.label)} (${esc(d.delivery.date)})` : '<span class="miss">Delivery ?</span>';
  $('cfLines').innerHTML = d.lines.map(lineHtml).join('');
  const q = d.question, qb = $('cfQuestion');
  if (q) {
    qb.classList.remove('hidden');
    const opts = (q.options || []).slice(0, q.type === 'party' && q.options.length > 4 ? 8 : 3)
      .map((o) => `<button class="btn btn-outline" data-opt="${esc(o.name)}">${esc(o.name)}</button>`).join('');
    qb.innerHTML = `${esc(q.text)}${opts ? `<div class="opts">${opts}</div>` : ''}`;
    qb.querySelectorAll('[data-opt]').forEach((b) => b.onclick = () => sendAnswer(b.dataset.opt));
  } else qb.classList.add('hidden');
  $('cfSay').textContent = `🔊 ${d.say}`;
  $('cfConfirm').disabled = !d.ready;
  if (speakIt) speak(d.say).then(() => { if (SR && $('screen-confirm').classList.contains('active')) answerMic.listen(); });
}

async function sendAnswer(text) {
  if (!text) return;
  $('answerLive').textContent = `"${text}"`;
  try {
    const r = await post('/api/answer', { draft: state.draft, text });
    state.draft = r.draft;
    if (r.action === 'confirm') return saveOrder();
    renderConfirm(true);
  } catch (e) {
    toast(e.network ? 'Network nahi hai. Jawab dobara bolein.' : e.message);
  }
}

async function saveOrder() {
  if (!state.draft?.ready) return toast('Pehle sawaal ka jawab dein');
  try {
    state.order = await post('/api/orders', { draft: state.draft });
    renderDone();
    speak(`Order ${state.order.id} save ho gaya.`);
  } catch (e) {
    toast(e.network ? 'Network nahi hai. Order abhi save nahi hua, dobara dabayein.' : e.message, 4000);
  }
}

function renderDone() {
  const o = state.order;
  show('done');
  const rows = o.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.name)}<br><small>${esc(l.code)}</small></td><td><b>${esc(l.qty)}</b> ${esc(l.unit)}</td></tr>`).join('');
  $('parchi').innerHTML = `<h2>PARCHI #${o.id}</h2>
    <div class="meta"><span><b>${esc(o.party)}</b></span><span>Delivery: ${esc(o.delivery_date)}</span></div>
    <div class="meta"><small>Created ${esc(o.created_at.replace('T', ' '))}</small><small>Status: ${esc(o.status)}</small></div>
    <table><tr><th>#</th><th>Item</th><th>Qty</th></tr>${rows}</table>
    <p><small>Heard: "${esc(o.heard_text)}"</small></p>`;
  $('dnCsv').href = `/api/orders/${o.id}/csv`;
}

// --------------------------------------------------------------- dispatch
let dispatchMic;
async function handleDispatch(res) {
  const box = $('dispatchBox');
  box.classList.remove('hidden');
  if (!res.text) { box.textContent = 'Awaaz saaf nahi aayi, dobara bolein.'; return speak(box.textContent); }
  if (state.dispatch?.ok && /pakka|haan|han|confirm|yes/i.test(res.text)) return doDispatch();
  try {
    const r = await post('/api/dispatch/parse', { text: res.text });
    state.dispatch = r;
    let html = `<div><i>Heard: "${esc(res.text)}"</i></div><p><b>${esc(r.say)}</b></p>`;
    if (r.ok) {
      html += `<div>${esc(r.items)}</div><div class="actions"><button class="btn" id="dsYes">✔ Haan, pakka</button><button class="btn btn-outline" id="dsNo">Cancel</button></div>`;
    } else if (r.order) {
      html += `<div class="opts">${['rickshaw', 'tempo', 'truck', 'auto', 'self pickup'].map((m) => `<button class="btn btn-outline" data-mode="${m}">${m}</button>`).join('')}</div>`;
    }
    box.innerHTML = html;
    box.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => { state.dispatch = { ...r, ok: true, mode: b.dataset.mode }; doDispatch(); });
    if (r.ok) {
      $('dsYes').onclick = doDispatch;
      $('dsNo').onclick = () => { state.dispatch = null; box.classList.add('hidden'); };
    }
    await speak(r.say);
    if (r.ok && SR) dispatchMic.listen();
  } catch (e) { toast(e.network ? 'Network nahi hai, dobara bolein' : e.message); }
}

async function doDispatch() {
  const r = state.dispatch;
  if (!r?.order) return;
  try {
    const o = await post(`/api/orders/${r.order.id}/dispatch`, { mode: r.mode });
    $('dispatchBox').innerHTML = `<b>✔ Order #${o.id} dispatched by ${esc(o.dispatch_mode)} on ${esc(o.dispatch_date)}.</b>`;
    speak(`Order ${o.id} dispatch ho gaya.`);
    state.dispatch = null;
    loadOrders();
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ theme
function applyTheme(t, save) {
  document.documentElement.setAttribute('data-theme', t);
  const b = $('themeBtn');
  b.textContent = t === 'dark' ? '☀' : '🌙';
  b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  if (save) { try { localStorage.setItem('bko-theme', t); } catch (_) {} }
}
function initTheme() {
  applyTheme(document.documentElement.getAttribute('data-theme') || 'light', false);
  $('themeBtn').onclick = () => applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);
  const mq = window.matchMedia && matchMedia('(prefers-color-scheme: dark)');
  mq && mq.addEventListener && mq.addEventListener('change', (e) => {
    let saved = null; try { saved = localStorage.getItem('bko-theme'); } catch (_) {}
    if (!saved) applyTheme(e.matches ? 'dark' : 'light', false); // follow the phone until the user picks
  });
}

// ------------------------------------------------------------------ misc
async function loadOrders() {
  try {
    const rows = await api('/api/orders');
    $('orders').innerHTML = rows.length ? rows.slice(0, 8).map((o) => `<div class="order"><div><b>#${o.id} ${esc(o.party)}</b><br><small>${o.lines.map((l) => `${l.qty} ${l.unit} ${esc(l.name)}`).join(', ')} · ${esc(o.delivery_date)}</small></div>
      <span class="badge ${o.status}">${esc(o.status)}${o.dispatch_mode ? ' · ' + esc(o.dispatch_mode) : ''}</span></div>`).join('') : '<small>No orders yet.</small>';
  } catch (_) { $('orders').innerHTML = '<small>Could not load orders (offline?).</small>'; }
}

async function init() {
  initTheme();
  try { state.cfg = await api('/api/config'); } catch (_) { state.cfg = { test_phrases: [] }; }
  const c = state.cfg;
  $('pills').innerHTML = [
    SR ? '<span class="pill">Mic: browser</span>' : '<span class="pill off">Mic: no browser speech</span>',
    c.server_stt ? '<span class="pill">Uploads: on</span>' : '<span class="pill off" title="' + esc(c.stt_message) + '">Speech key not set</span>',
    c.llm ? '<span class="pill">LLM: on</span>' : '<span class="pill off" title="' + esc(c.llm_message) + '">LLM key not set · rules</span>',
  ].join('');
  $('samples').innerHTML = (c.test_phrases || []).map((p, i) => `<button class="chip" data-i="${i}">${esc(p.text)}</button>`).join('');
  $('samples').querySelectorAll('.chip').forEach((b) => b.onclick = () => showTranscript(c.test_phrases[b.dataset.i].text, false));

  bindMic($('micOrder'), { onInterim: (t) => ($('liveText').textContent = t), onResult: (r) => { $('liveText').textContent = ''; handleCaptured(r, 'mic'); } });
  answerMic = bindMic($('micAnswer'), { onInterim: (t) => ($('answerLive').textContent = t), onResult: (r) => {
    if (!r.text) { $('answerLive').textContent = ''; return; }
    sendAnswer(r.text);
  } });
  dispatchMic = bindMic($('micDispatch'), { onInterim: (t) => { $('dispatchBox').classList.remove('hidden'); $('dispatchBox').textContent = t; }, onResult: handleDispatch });

  $('fileInput').onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    state.blob = f; state.blobName = f.name; e.target.value = '';
    sendRecording();
  };
  $('typedGo').onclick = () => showTranscript($('typed').value, false);
  $('trGo').onclick = parseTranscript;
  $('trText').addEventListener('focus', () => clearTimeout(state.autoTimer));
  $('trRetry').onclick = sendRecording;
  $('trAgain').onclick = () => { clearTimeout(state.autoTimer); show('home'); };
  $('ansGo').onclick = () => { sendAnswer($('ansTyped').value); $('ansTyped').value = ''; };
  $('cfConfirm').onclick = saveOrder;
  $('cfBack').onclick = () => { showTranscript(state.draft?.heard || '', false, 'Text theek karein, phir Samjho dabayein.'); clearTimeout(state.autoTimer); };
  $('dnPrint').onclick = () => window.print();
  $('dnNew').onclick = () => { state.draft = null; state.blob = null; show('home'); };
  $('goHome').onclick = () => show('home');
  loadOrders();
}
init();

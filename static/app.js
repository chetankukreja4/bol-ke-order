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
        if (r.status === 401 && data.error === 'pin' && await askPin()) { i--; continue; } // shop PIN, then retry
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
// Optional shop PIN (BKO_PIN on the server): asked once, then kept as a cookie.
let pinTries = 0;
async function askPin() {
  if (pinTries++ > 3) return false;
  const pin = window.prompt('Shop PIN daalein');
  if (!pin) return false;
  const r = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }) });
  if (r.ok) { pinTries = 0; return true; }
  toast('PIN galat hai');
  return askPin();
}
const post = (p, body) => api(p,{ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

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
// The app's voice: the server's local Hindi voice (Piper) when installed,
// else the browser's own voice. Either way speak() resolves when it is done.
let currentAudio = null;
function stopSpeaking() {
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  if (currentAudio) { const a = currentAudio; currentAudio = null; a.pause(); a.dispatchEvent(new Event('ended')); }
}
async function speak(text) {
  if (!text) return;
  stopSpeaking();
  if (state.cfg?.server_tts) {
    try {
      const r = await fetch('/api/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      if (r.ok) {
        const url = URL.createObjectURL(await r.blob());
        const played = await new Promise((resolve) => {
          const a = new Audio(url);
          currentAudio = a;
          let done = false;
          const finish = (ok) => { if (done) return; done = true; URL.revokeObjectURL(url); if (currentAudio === a) currentAudio = null; resolve(ok); };
          a.onended = () => finish(true);
          a.onerror = () => finish(false);
          setTimeout(() => finish(true), 30000); // never hang
          a.play().catch(() => finish(false)); // e.g. the phone blocked autoplay
        });
        if (played) return;
      }
    } catch (_) { /* network: fall back to the browser voice */ }
  }
  return browserSpeak(text);
}
function browserSpeak(text) {
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
// Two engines:
//  * "sarvam": record the mic and send the clip to the server (Sarvam saaras:v4),
//    used whenever the server has SARVAM_API_KEY. Much better with Hinglish and
//    shop noise than the browser recogniser. A level meter decides when you stop.
//  * "browser": Web Speech (hi-IN), used when no key is set or the user picks it.
const hasRecorder = () => !!(navigator.mediaDevices && window.MediaRecorder);
function micEngine() {
  let pick = null; try { pick = localStorage.getItem('bko-mic'); } catch (_) {}
  const sarvamOk = state.cfg?.server_stt && hasRecorder();
  if (pick === 'browser' && SR) return 'browser';
  if (sarvamOk) return 'sarvam';
  return SR ? 'browser' : (hasRecorder() ? 'record' : 'none');
}
const micAvailable = () => micEngine() !== 'none';
const blobExt = (type) => (/mp4|aac|m4a/.test(type) ? 'm4a' : /ogg/.test(type) ? 'ogg' : 'webm');

// Starts capture (+ a recording kept for retries).
function startCapture({ onInterim, onAutoStop }) {
  const engine = micEngine();
  const ctl = { finals: [], conf: [], interim: '', blob: null, autoStop: false, prompted: false, stopping: false,
    heard: false, engine };
  let rec = null, recorder = null, chunks = [], stream = null, silenceTimer = null, quietTimer = null;
  let audioCtx = null, levelTimer = null;
  const t0 = Date.now();

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

  // Voice-activity detection from the mic level: knows when someone is talking
  // and when they stopped, without needing the browser recogniser.
  const watchLevel = (s) => {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const an = audioCtx.createAnalyser(); an.fftSize = 1024;
      audioCtx.createMediaStreamSource(s).connect(an);
      const buf = new Float32Array(an.fftSize);
      let floor = 0.01, lastLoud = 0, loudRun = 0;
      levelTimer = setInterval(() => {
        an.getFloatTimeDomainData(buf);
        let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length), now = Date.now();
        const thr = Math.max(0.015, floor * 2.8);
        if (rms > thr) {
          loudRun++;
          if (loudRun >= 2) { // ~200 ms of sound = speech, not a click
            lastLoud = now;
            if (!ctl.heard) { ctl.heard = true; if (engine !== 'browser') onInterim && onInterim('🎙 Sun raha hoon…'); }
            resetSilence();
          }
        } else {
          loudRun = 0;
          floor = floor * 0.95 + rms * 0.05; // follows the shop's background noise
        }
        if (engine !== 'browser' && ctl.autoStop && ctl.heard && !ctl.stopping && now - lastLoud > 1600 && now - t0 > 1200) {
          onAutoStop && onAutoStop();
        }
      }, 100);
    } catch (_) { /* no level meter: hold-to-speak and the 8 s timeout still work */ }
  };

  const useSR = SR && (engine === 'browser' || (engine === 'sarvam' && !IS_ANDROID)); // desktop: live preview too
  const wantRecorder = hasRecorder() && (engine !== 'browser' || !IS_ANDROID); // Android can't share the mic with SR
  if (wantRecorder) {
    ctl.recorderReady = navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    }).then((s) => {
      stream = s; recorder = new MediaRecorder(s);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.start();
      watchLevel(s);
      if (engine !== 'browser' && !ctl.heard) onInterim && onInterim('🎙 Boliye…');
    }).catch(() => toast('Mic permission chahiye'));
  }

  if (useSR) {
    rec = new SR();
    rec.lang = localStorage.getItem('bko-lang') || 'hi-IN';
    rec.interimResults = true; rec.continuous = true; rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) { ctl.finals.push(r[0].transcript); ctl.conf.push(r[0].confidence || 0); }
        else interim += r[0].transcript;
      }
      ctl.interim = interim;
      ctl.heard = true;
      onInterim && onInterim((ctl.finals.join(' ') + ' ' + interim).trim());
      resetSilence();
      if (ctl.autoStop && engine === 'browser') { // tap mode: stop after a short pause once something was said
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
    clearTimeout(silenceTimer); clearTimeout(quietTimer); clearInterval(levelTimer);
    if (rec) { try { rec.stop(); } catch (_) {} }
    if (ctl.recorderReady) await ctl.recorderReady;
    if (recorder && recorder.state !== 'inactive') {
      await new Promise((res) => { recorder.onstop = res; recorder.stop(); });
      ctl.blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
    }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (audioCtx) audioCtx.close().catch(() => {});
    await sleep(rec ? 350 : 0); // let the last final result arrive
    const browserText = (ctl.finals.join(' ') + ' ' + (ctl.interim || '')).trim();
    const conf = ctl.conf.length ? ctl.conf.reduce((a, b) => a + b, 0) / ctl.conf.length : null;
    const blobName = ctl.blob ? `mic.${blobExt(ctl.blob.type)}` : null;
    const base = { text: browserText, conf, blob: ctl.blob, blobName, source: 'browser' };

    if (engine === 'sarvam' && ctl.blob && ctl.blob.size > 1500) {
      if (!ctl.heard && !browserText) return { ...base, text: '' }; // nothing said: don't spend a call
      onInterim && onInterim('⏳ Samajh raha hoon… (Sarvam AI)');
      const fd = new FormData(); fd.append('file', ctl.blob, blobName);
      try {
        const r = await api('/api/transcribe', { method: 'POST', body: fd }, 2);
        if (r.transcript && r.transcript.trim()) return { ...base, text: r.transcript.trim(), conf: null, source: 'server' };
        return { ...base, conf: null }; // Sarvam heard nothing: keep the browser's text, if any
      } catch (e) {
        toast(e.network ? 'Network slow hai — browser wala text use kar rahe hain' : `Sarvam: ${e.message}`);
        return base;
      }
    }
    return base;
  };
  return ctl;
}

// Hold to speak, or tap once to start and it stops by itself after you finish.
function bindMic(btn, { onInterim, onResult }) {
  let ctl = null, t0 = 0, mode = null;
  const begin = (m) => {
    stopSpeaking(); // pressing the mic stops the app talking
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
// Pages: Order (with its flow screens), Orders, Dispatch, Items. One per tab.
const TABS = ['order', 'orders', 'dispatch', 'items', 'pilot'];
function show(name) {
  let tab = 'order';
  document.querySelectorAll('.screen').forEach((sc) => {
    const on = sc.id === `screen-${name}`;
    sc.classList.toggle('active', on);
    if (on) tab = sc.dataset.tab;
  });
  document.querySelectorAll('.tab').forEach((t) => {
    const on = t.dataset.tab === tab;
    t.classList.toggle('active', on);
    if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
  });
  if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
  window.scrollTo(0, 0);
  if (name === 'orders' || name === 'dispatch') loadOrders();
  if (name === 'items') loadItems();
  if (name === 'pilot') loadPilot();
}
function route() {
  const tab = location.hash.replace('#', '');
  show(TABS.includes(tab) ? tab : 'order');
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ------------------------------------------------------------ order capture
async function handleCaptured(res, source) {
  state.source = 'mic';
  state.blob = res.blob || state.blob;
  state.blobName = res.blob ? res.blobName : state.blobName;
  if (res.source !== 'server' && !res.text && res.blob && micEngine() === 'record') return sendRecording(); // no browser speech: server does it
  const unclear = !res.text || res.text.split(/\s+/).length < 2 || (res.conf !== null && res.conf > 0 && res.conf < LOW_CONFIDENCE);
  showTranscript(res.text, unclear);
}

function showTranscript(text, unclear, statusMsg) {
  state.textKind = null; // spoken or typed text
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
    const d = await post('/api/parse', {
      text, kind: state.textKind || null, source: state.source || 'typed', test: $('testOrder').checked,
      elapsed: state.startedAt ? (Date.now() - state.startedAt) / 1000 : null,
      carry: state.carry || null, // after "Back": same order, same clock
    });
    state.carry = null;
    state.draft = d;
    if (d.notice === 'unclear') {
      if (state.textKind === 'transcript') return toast('Is transcript mein koi item nahi mila. Text check karein.', 4000);
      return showTranscript(text, true);
    }
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
  const note = ln.note ? `<div class="flag cond">❓ Shart: "${esc(ln.note)}" — party se poochh kar tay karein</div>` : '';
  return `<div class="line ${ln.uncertain ? 'unsure' : ''}">
    <div class="qty">${esc(qty)}<small>${esc(ln.unit || '')}</small></div>
    <div class="name">${esc(name)}${ln.item ? ` <small>(${esc(ln.item.code)})</small>` : ''}</div>
    <div class="heard-as">heard: "${esc(ln.heard)}"</div>${note}${flag}</div>`;
}

let answerMic;
function renderConfirm(speakIt) {
  const d = state.draft;
  show('confirm');
  const tag = document.querySelector('#screen-confirm .pill.pending');
  if (tag) tag.textContent = d.edit_of != null ? `Order #${d.edit_of} badal rahe hain` : 'Not saved';
  $('cfHeard').textContent = d.heard;
  $('cfParty').innerHTML = d.party.status === 'ok' ? esc(d.party.party.name) : '<span class="miss">Party ?</span>';
  $('cfDate').innerHTML = d.delivery ? `Delivery: ${esc(d.delivery.label)} (${esc(d.delivery.date)})` : '<span class="miss">Delivery ?</span>';
  $('cfLines').innerHTML = d.lines.map(lineHtml).join('');
  const q = d.question, qb = $('cfQuestion');
  if (q) {
    qb.classList.remove('hidden');
    const opts = (q.options || []).slice(0, 8) // server already caps unsure matches at 3; a brand group shows all
      .map((o) => `<button class="btn btn-outline" data-opt="${esc(o.name)}">${esc(o.name)}</button>`).join('');
    qb.innerHTML = `${esc(q.text)}${opts ? `<div class="opts">${opts}</div>` : ''}`;
    qb.querySelectorAll('[data-opt]').forEach((b) => b.onclick = () => sendAnswer(b.dataset.opt));
  } else qb.classList.add('hidden');
  $('cfSay').textContent = `🔊 ${d.say}`;
  $('cfConfirm').disabled = !d.ready;
  if (speakIt) speak(d.say).then(() => { if (micAvailable() && $('screen-confirm').classList.contains('active')) answerMic.listen(); });
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
  if (state.saving) return; // a second tap (or "haan pakka" + tap) must not save twice
  state.saving = true;
  $('cfConfirm').disabled = true;
  try {
    state.order = await post('/api/orders', { draft: state.draft });
    if (state.draft?.draft_id) writeQueue(readQueue().filter((x) => x.draft.draft_id !== state.draft.draft_id));
    state.startedAt = null; // the next order starts its own clock
    renderDone();
    speak(`Order ${state.order.id} save ho gaya.`);
  } catch (e) {
    if (e.network && state.draft?.draft_id && state.draft.edit_of == null) {
      // keep it on the phone; it is sent when the network is back
      writeQueue([...readQueue().filter((x) => x.draft.draft_id !== state.draft.draft_id), { draft: state.draft, at: Date.now() }]);
      toast('Network nahi hai. Order phone mein rakha hai, network aate hi save ho jayega.', 5000);
      state.draft = null; state.blob = null; state.startedAt = null;
      show('order');
      return;
    }
    toast(e.network ? 'Network nahi hai. Order abhi save nahi hua, dobara dabayein.' : e.message, 4000);
    $('cfConfirm').disabled = !state.draft?.ready; // a retry sends the same draft: still one order
  } finally {
    state.saving = false;
  }
}

function renderDone(viewOnly) {
  const o = state.order;
  show('done');
  $('dnTitle').textContent = viewOnly ? `Parchi #${o.id}` : '✔ Order saved';
  $('dnNew').textContent = viewOnly ? '← Back to orders' : '+ New order';
  $('dnNew').onclick = viewOnly ? () => show('orders') : () => { state.draft = null; state.blob = null; state.startedAt = null; show('order'); };
  const rows = o.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.name)}<br><small>${esc(l.code)}</small></td><td><b>${esc(l.qty)}</b> ${esc(l.unit)}</td></tr>`).join('');
  const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  const created = new Date(o.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  $('parchi').innerHTML = `<h2>PARCHI #${o.id}</h2>
    <div class="meta"><span><b>${esc(o.party)}</b></span><span>Delivery: <b>${esc(fmtDate(o.delivery_date))}</b></span></div>
    <div class="meta"><small>Order taken ${esc(created)}</small>${o.dispatch_mode ? `<small>Sent by ${esc(o.dispatch_mode)}</small>` : ''}</div>
    <table><tr><th>#</th><th>Item</th><th>Qty</th></tr>${rows}</table>`;
  // What the app heard is for staff to check on screen only; it is not printed.
  $('dnHeard').innerHTML = o.heard_text ? `<b>App ne suna:</b> "${esc(o.heard_text)}"` : '';
  $('dnCsv').href = `/api/orders/${o.id}/csv`;
  const open = o.status === 'confirmed';
  $('dnEdit').classList.toggle('hidden', !open);
  $('dnCancel').classList.toggle('hidden', !open);
  $('dnTitle').textContent = o.status === 'cancelled' ? `Parchi #${o.id} · cancelled` : $('dnTitle').textContent;
  $('dnWa').onclick = () => window.open(`https://wa.me/?text=${encodeURIComponent(parchiText(o))}`, '_blank', 'noopener');
  $('dnEdit').onclick = () => editOrder(o.id);
  $('dnCancel').onclick = () => cancelOrder(o);
  renderWrong();
}

// Parchi as plain text for WhatsApp (the shop picks the contact in WhatsApp).
function parchiText(o) {
  const lines = o.lines.map((l, i) => `${i + 1}. ${l.name} — ${l.qty} ${l.unit}`).join('\n');
  return `*Parchi #${o.id}*\n${o.party}\nDelivery: ${o.delivery_date}\n\n${lines}\n\n— Bol-ke-Order`;
}

// Edit: the saved order comes back to "Check the order"; voice or taps change it; Confirm saves under the same number.
async function editOrder(id) {
  try {
    state.draft = await api(`/api/orders/${id}/draft`);
    state.startedAt = null;
    renderConfirm(true);
  } catch (e) { toast(e.network ? 'Network nahi hai, dobara try karein' : e.message, 4000); }
}

async function cancelOrder(o) {
  if (!window.confirm(`Order #${o.id} (${o.party}) cancel karein? Ye wapas nahi hoga.`)) return;
  try {
    state.order = await post(`/api/orders/${o.id}/cancel`, {});
    toast(`Order #${o.id} cancel ho gaya`);
    renderDone(true);
    loadOrders();
  } catch (e) { toast(e.network ? 'Network nahi hai, dobara try karein' : e.message, 4000); }
}

// Offline: a confirmed order that could not reach the server waits on the phone
// and is sent when the network is back. The draft id stops it being saved twice.
const QUEUE_KEY = 'bko-queue';
const readQueue = () => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch (_) { return []; } };
const writeQueue = (q) => { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch (_) {} renderQueuePill(); };
function renderQueuePill() {
  const q = readQueue();
  const stuck = q.filter((x) => x.error);
  let p = document.querySelector('#pills [data-queue]');
  if (!q.length) { p?.remove(); return; }
  if (!p) {
    p = document.createElement('button'); p.type = 'button'; p.className = 'pill queue'; p.dataset.queue = '1';
    p.onclick = openStuck; $('pills').appendChild(p);
  }
  p.textContent = stuck.length ? `${stuck.length} order atka hai · kholein` : `${q.length} order ruka hai`;
  p.title = stuck.length ? stuck[0].error : 'Network aate hi save hoga';
}
// An order the server refused after waiting offline (say its date has passed) is never
// thrown away: it opens in "Check the order" to fix and confirm again.
function openStuck() {
  const item = readQueue().find((x) => x.error);
  if (!item) return toast('Network aate hi save hoga');
  state.draft = item.draft;
  state.startedAt = null;
  renderConfirm(false);
  toast(`Save nahi hua: ${item.error}. Theek karke Confirm karein.`, 6000);
}
let flushing = false;
async function flushQueue() {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    for (const item of readQueue().filter((x) => !x.error)) {
      try {
        // the time it waited for the network is not time spent taking the order
        const draft = { ...item.draft, stats: item.draft.stats ? { ...item.draft.stats, offline_seconds: (Date.now() - item.at) / 1000 } : item.draft.stats };
        const o = await api('/api/orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ draft }) }, 1);
        writeQueue(readQueue().filter((x) => x.draft.draft_id !== item.draft.draft_id));
        toast(`Ruka hua order #${o.id} save ho gaya`);
      } catch (e) {
        if (e.network) break; // still offline: try later
        // keep it, marked, so it can be opened and fixed (never lost)
        writeQueue(readQueue().map((x) => (x.draft.draft_id === item.draft.draft_id ? { ...x, error: e.message } : x)));
        toast(`Ruka hua order save nahi hua: ${e.message}. Upar "order atka hai" dabayein.`, 6000);
      }
    }
  } finally { flushing = false; }
  if (location.hash === '#orders' || location.hash === '#dispatch') loadOrders();
}

// "Galat nikla": the saved order turned out wrong. Counted in the pilot numbers.
const WRONG = { item: 'Item galat', qty: 'Quantity galat', party: 'Party galat', missing: 'Item chhoot gaya', other: 'Kuch aur' };
function renderWrong(open) {
  const o = state.order, box = $('dnWrong');
  if (o.wrong_reason) {
    box.innerHTML = `<div class="status bad">✗ Galat nikla: ${esc(WRONG[o.wrong_reason] || o.wrong_reason)}
      <button class="btn btn-outline btn-xs" id="wrongUndo">Undo</button></div>`;
    $('wrongUndo').onclick = async () => {
      try {
        state.order = await api(`/api/orders/${o.id}/wrong`, { method: 'DELETE' });
        renderWrong(); toast('Hata diya');
      } catch (e) { toast(e.network ? 'Network nahi hai, dobara try karein' : e.message); }
    };
    return;
  }
  if (!open) {
    box.innerHTML = '<button class="btn btn-outline btn-sm" id="wrongOpen">✗ Galat nikla?</button>';
    $('wrongOpen').onclick = () => renderWrong(true);
    return;
  }
  box.innerHTML = `<div class="card small"><b>Kya galat tha?</b><div class="opts">${
    Object.entries(WRONG).map(([k, v]) => `<button class="btn btn-outline btn-sm" data-r="${k}">${v}</button>`).join('')
  }</div></div>`;
  box.querySelectorAll('[data-r]').forEach((b) => b.onclick = async () => {
    try {
      state.order = await post(`/api/orders/${o.id}/wrong`, { reason: b.dataset.r });
      renderWrong();
      toast('Note ho gaya');
    } catch (e) { toast(e.network ? 'Network nahi hai, dobara try karein' : e.message); }
  });
}

// ------------------------------------------------------------------ pilot
const fmtSec = (s) => (s === null || s === undefined ? '–' : s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`);
const fmtPct = (p) => (p === null || p === undefined ? '–' : `${p}%`);
async function loadPilot() {
  let p;
  try { p = await api('/api/pilot'); } catch (e) { $('pilotTiles').innerHTML = empty('Numbers nahi aaye. Network check karein.'); return; }
  const tile = (big, label) => `<div class="stat"><b>${big}</b><span>${label}</span></div>`;
  $('pilotTiles').innerHTML = [
    tile(`${p.today} / ${p.orders}`, 'Orders (aaj / kul)'),
    tile(fmtSec(p.median_seconds), 'App: order shuru se pakka (median)'),
    tile(fmtSec(p.baseline_median), 'Pehle: parchi + Busy (median)'),
    tile(fmtPct(p.pct_right_after_save), 'Save ke baad sahi nikle'),
    tile(fmtPct(p.pct_no_questions), 'Bina sawaal ke pakke'),
    tile(p.corrections_per_order ?? '–', 'Sudhaar per order'),
  ].join('');
  const src = Object.entries(p.by_source).map(([k, v]) => `${esc(k)} ${v}`).join(' · ') || '–';
  const wrong = Object.entries(p.wrong_by_reason).map(([k, v]) => `${esc(WRONG[k] || k)} ${v}`).join(' · ') || 'koi nahi';
  $('pilotMore').innerHTML = `<div><b>Order kaise aaye:</b> ${src}</div><div><b>Galat nikle:</b> ${wrong}</div>
    <div><b>Average time:</b> ${fmtSec(p.avg_seconds)} · <b>Pehle ke naap:</b> ${p.baseline_count}</div>`;
  $('baseInput').value = (p.baseline || []).join(', ');
}
async function saveBaseline() {
  const seconds = $('baseInput').value.split(/[,\s]+/).filter(Boolean).map(Number);
  if (seconds.some((n) => !Number.isFinite(n))) return toast('Sirf numbers likhein, jaise 180, 240');
  try {
    await api('/api/pilot/baseline', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ seconds }) });
    toast('Save ho gaya'); loadPilot();
  } catch (e) { toast(e.network ? 'Network nahi hai' : e.message); }
}

// --------------------------------------------------------------- dispatch
let dispatchMic;
async function handleDispatch(res) {
  const box = $('dispatchBox');
  box.classList.remove('hidden');
  if (!res.text) { box.textContent = 'Awaaz saaf nahi aayi, dobara bolein.'; return speak(box.textContent); }
  const prev = state.dispatch || {};
  try {
    // Send the order and mode we are already talking about, so "truck se" and "haan pakka" continue it.
    const r = await post('/api/dispatch/parse', { text: res.text, order_ids: (prev.orders || []).map((o) => o.id), mode: prev.mode || null });
    if (r.action === 'confirm') { state.dispatch = { ...r, ok: true }; return doDispatch(); }
    if (r.action === 'cancel') {
      state.dispatch = null;
      box.innerHTML = `<div><i>Heard: "${esc(res.text)}"</i></div><p><b>${esc(r.say)}</b></p>`;
      return speak(r.say);
    }
    state.dispatch = r;
    let html = `<div><i>Heard: "${esc(res.text)}"</i></div><p><b>${esc(r.say)}</b></p>`;
    if (r.ok) {
      html += `<ul class="ds-items">${r.items.map((t) => `<li>${esc(t)}</li>`).join('')}</ul><div class="actions"><button class="btn" id="dsYes">✔ Haan, pakka</button><button class="btn btn-outline" id="dsNo">Cancel</button></div>`;
    } else if (r.orders?.length) {
      html += `<div class="opts">${MODES.map((m) => `<button class="btn btn-outline" data-mode="${m}">${m}</button>`).join('')}</div>`;
    } else if (r.options) {
      html += `<div class="opts">${r.options.map((o) => `<button class="btn btn-outline" data-party="${esc(o.name)}">${esc(o.name)}</button>`).join('')}</div>`;
    }
    box.innerHTML = html;
    box.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => { state.dispatch = { ...r, ok: true, mode: b.dataset.mode }; doDispatch(); });
    box.querySelectorAll('[data-party]').forEach((b) => b.onclick = () => handleDispatch({ text: `${b.dataset.party} ${r.mode || ''}` }));
    if (r.ok) {
      $('dsYes').onclick = doDispatch;
      $('dsNo').onclick = () => { state.dispatch = null; box.classList.add('hidden'); };
    }
    await speak(r.say);
    if ((r.ok || r.orders?.length || r.options) && micAvailable() && $('screen-dispatch').classList.contains('active')) dispatchMic.listen();
  } catch (e) { toast(e.network ? 'Network nahi hai, dobara bolein' : e.message); }
}

async function doDispatch() {
  const r = state.dispatch;
  if (!r?.orders?.length) return;
  const box = $('dispatchBox');
  box.classList.remove('hidden');
  const sent = [];
  try {
    for (const ord of r.orders) { // one truck can carry several orders
      sent.push(await post(`/api/orders/${ord.id}/dispatch`, { mode: r.mode }));
    }
  } catch (e) {
    toast(e.network ? 'Network nahi hai, dobara dabayein' : e.message);
  }
  if (sent.length) {
    const ids = sent.map((o) => `#${o.id}`).join(', ');
    box.innerHTML = `<b>✔ Order ${esc(ids)} dispatched by ${esc(sent[0].dispatch_mode)} on ${esc(sent[0].dispatch_date)}.</b>`;
    speak(sent.length > 1 ? `${sent.length} order dispatch ho gaye.` : `Order ${sent[0].id} dispatch ho gaya.`);
    // keep any that failed, so "Haan pakka" again retries only those
    state.dispatch = sent.length < r.orders.length ? { ...r, orders: r.orders.slice(sent.length) } : null;
  }
  loadOrders();
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
const MODES = ['rickshaw', 'tempo', 'truck', 'auto', 'self pickup'];
const orderSummary = (o) => o.lines.map((l) => `${esc(l.qty)} ${esc(l.unit)} ${esc(l.name)}`).join(', ');
const badge = (o) => `<span class="badge ${o.status}">${o.status === 'confirmed' ? 'pending' : o.status === 'cancelled' ? 'cancelled' : 'dispatched'}${o.dispatch_mode ? ' · ' + esc(o.dispatch_mode) : ''}</span>`;
const empty = (msg) => `<div class="empty">${msg}</div>`;

async function loadOrders() {
  try {
    state.orders = await api('/api/orders');
  } catch (_) {
    state.orders = null;
  }
  renderOrders(); renderPending();
}

function renderOrders() {
  const box = $('orders');
  if (!state.orders) { box.innerHTML = empty('Could not load orders (offline?).'); return; }
  const f = state.filter || 'all';
  const today = state.cfg?.today || new Date().toISOString().slice(0, 10);
  const rows = f === 'today' // waiting to go and due today (or already late), earliest first
    ? state.orders.filter((o) => o.status === 'confirmed' && o.delivery_date <= today).sort((a, b) => a.delivery_date.localeCompare(b.delivery_date) || a.id - b.id)
    : state.orders.filter((o) => f === 'all' || o.status === f);
  box.innerHTML = rows.length ? rows.map((o) => `<button class="row-card" data-id="${o.id}">
      <div class="rc-main"><b>#${o.id} ${esc(o.party)}</b><small>${orderSummary(o)}</small><small class="muted">Delivery ${esc(o.delivery_date)}</small></div>
      ${badge(o)}</button>`).join('') : empty(f === 'all' ? 'No orders yet. Speak one on the Order tab.' : 'Nothing here.');
  box.querySelectorAll('[data-id]').forEach((b) => b.onclick = () => {
    state.order = state.orders.find((o) => String(o.id) === b.dataset.id);
    renderDone(true);
  });
}

function renderPending() {
  const box = $('pending');
  const rows = (state.orders || []).filter((o) => o.status === 'confirmed');
  $('pendingCount').textContent = rows.length || '';
  box.innerHTML = rows.length ? rows.map((o) => `<div class="row-card static">
      <div class="rc-main"><b>#${o.id} ${esc(o.party)}</b><small>${orderSummary(o)}</small><small class="muted">Delivery ${esc(o.delivery_date)}</small>
      <div class="opts small">${MODES.map((m) => `<button class="btn btn-outline btn-xs" data-id="${o.id}" data-mode="${m}">${m}</button>`).join('')}</div></div></div>`).join('')
    : empty(state.orders ? 'All orders have gone out. 🎉' : 'Could not load orders (offline?).');
  box.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => {
    // one tap only proposes; "Haan, pakka" sends (a mis-tap must not mark an order as gone)
    const order = state.orders.find((o) => String(o.id) === b.dataset.id);
    state.dispatch = { ok: true, orders: [order], mode: b.dataset.mode };
    const ds = $('dispatchBox');
    ds.classList.remove('hidden');
    ds.innerHTML = `<p><b>#${esc(order.id)} ${esc(order.party)}, ${esc(b.dataset.mode)} se gaya. Pakka?</b></p>
      <ul class="ds-items"><li>${orderSummary(order)}</li></ul>
      <div class="actions"><button class="btn" id="dsYes">✔ Haan, pakka</button><button class="btn btn-outline" id="dsNo">Cancel</button></div>`;
    $('dsYes').onclick = doDispatch;
    $('dsNo').onclick = () => { state.dispatch = null; ds.classList.add('hidden'); };
    ds.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
}

// ------------------------------------------------------------------ items
function initItems() {
  const c = state.cfg || {};
  $('fUnit').innerHTML = (c.units || ['carton', 'bag', 'packet', 'piece', 'kg', 'litre']).map((u) => `<option>${esc(u)}</option>`).join('');
  $('fGroup').innerHTML = '<option value="">— none —</option>' + (c.groups || []).map((g) => `<option value="${esc(g.key)}">${esc(g.label)} (says "${esc(g.words[0])}")</option>`).join('');
  $('itemSearch').addEventListener('input', renderItems);
  $('itemAdd').onclick = () => openItem(null);
  $('itemClose').onclick = () => $('itemDlg').close();
  $('itemForm').onsubmit = (e) => { e.preventDefault(); saveItem(); };
  $('itemDelete').onclick = deleteItem;
  $('partySearch').addEventListener('input', renderParties);
  [['impItems', 'items'], ['impParties', 'parties']].forEach(([id, kind]) => $(id).onchange = (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (f) previewImport(kind, f);
  });
}

async function loadItems() {
  try { state.items = await api('/api/items'); } catch (_) { state.items = null; }
  renderItems();
  try { state.parties = await api('/api/parties'); } catch (_) { state.parties = null; }
  renderParties();
}

function renderParties() {
  const box = $('partiesList');
  if (!state.parties) { box.innerHTML = empty('Could not load parties (offline?).'); return; }
  const q = $('partySearch').value.trim().toLowerCase();
  const rows = state.parties.filter((p) => !q || [p.code, p.name, ...p.aliases].some((t) => t.toLowerCase().includes(q)));
  $('partiesCount').textContent = state.parties.length;
  box.innerHTML = rows.length ? rows.map((p) => `<div class="row-card static">
      <span class="code">${esc(p.code)}</span>
      <div class="rc-main"><b>${esc(p.name)}</b><small class="muted">${esc(p.aliases.join(', '))}</small></div>
    </div>`).join('') : empty(q ? `No party matches "${esc(q)}".` : 'No parties yet.');
}

// Busy import: first a preview, then "haan" replaces the whole list.
const IMPORT_LABEL = { items: 'items', parties: 'parties' };
async function previewImport(kind, file) {
  const box = $('impBox');
  box.classList.remove('hidden');
  box.innerHTML = 'File padh rahe hain…';
  const send = (commit) => {
    const fd = new FormData(); fd.append('file', file, file.name);
    return api(`/api/${kind}/import${commit ? '?commit=1' : ''}`, { method: 'POST', body: fd });
  };
  let p;
  try { p = await send(false); } catch (e) {
    box.innerHTML = `<div class="status bad">${esc(e.network ? 'Network nahi hai' : e.message)}</div>`; return;
  }
  const skipped = p.skipped.length ? `<details><summary>${p.skipped.length} line(s) chhodi</summary><ul>${
    p.skipped.slice(0, 50).map((s) => `<li>Line ${s.row}: ${esc(s.name || '(khaali)')} — ${esc(s.reason)}</li>`).join('')}</ul></details>` : '';
  const names = p.sample.map((x) => `<li>${esc(x.name)}${x.unit ? ` <small>(${esc(x.unit)})</small>` : ''}</li>`).join('');
  box.innerHTML = `<b>${p.count} ${IMPORT_LABEL[kind]} mile</b> <small>(${p.total_rows} lines mein se)</small>
    <ul>${names}</ul>${p.count > 10 ? `<small>…aur ${p.count - 10}</small>` : ''}${skipped}
    ${p.count ? `<div class="actions"><button class="btn btn-outline" id="impNo">Rehne do</button>
      <button class="btn" id="impYes">Haan, purani list hata kar ye daalein</button></div>` : '<div class="status bad">Is file mein kuch nahi mila.</div>'}`;
  if (!p.count) return;
  $('impNo').onclick = () => box.classList.add('hidden');
  $('impYes').onclick = async () => {
    try {
      const r = await send(true);
      box.classList.add('hidden');
      toast(`${r.count} ${IMPORT_LABEL[kind]} daal diye`);
      try { state.cfg = await api('/api/config'); } catch (_) {}
      loadItems();
    } catch (e) { toast(e.network ? 'Network nahi hai, dobara try karein' : e.message, 4000); }
  };
}

function renderItems() {
  const box = $('itemsList');
  if (!state.items) { box.innerHTML = empty('Could not load items (offline?).'); return; }
  const q = $('itemSearch').value.trim().toLowerCase();
  const rows = state.items.filter((i) => !q || [i.code, i.name, ...i.aliases].some((t) => t.toLowerCase().includes(q)));
  $('itemsCount').textContent = state.items.length;
  const groupLabel = (g) => ((state.cfg?.groups || []).find((x) => x.key === g) || {}).label || g;
  box.innerHTML = rows.length ? rows.map((i) => `<button class="row-card" data-code="${esc(i.code)}">
      <span class="code">${esc(i.code)}</span>
      <div class="rc-main"><b>${esc(i.name)}</b><small class="muted">${esc(i.aliases.join(', ')) || '<i>no spoken names</i>'}</small></div>
      <div class="rc-side"><span class="badge">${esc(i.unit)}</span>${i.group ? `<span class="badge grp">${esc(groupLabel(i.group))}</span>` : ''}</div>
    </button>`).join('') : empty(q ? `No item matches "${esc(q)}".` : 'No items yet. Tap “+ Add item”.');
  box.querySelectorAll('[data-code]').forEach((b) => b.onclick = () => openItem(state.items.find((i) => i.code === b.dataset.code)));
}

function nextCode() {
  const nums = (state.items || []).map((i) => i.code.match(/^IT(\d+)$/)).filter(Boolean).map((m) => +m[1]);
  return `IT${String((nums.length ? Math.max(...nums) : 0) + 1).padStart(2, '0')}`;
}

function openItem(item) {
  state.editing = item ? item.code : null;
  $('itemDlgTitle').textContent = item ? `Edit ${item.code}` : 'Add item';
  $('fCode').value = item ? item.code : nextCode();
  $('fName').value = item ? item.name : '';
  $('fUnit').value = item ? item.unit : 'carton';
  $('fGroup').value = item?.group || '';
  $('fAliases').value = item ? item.aliases.join(', ') : '';
  $('fErr').classList.add('hidden');
  $('itemDelete').classList.toggle('hidden', !item);
  $('itemDlg').showModal();
  (item ? $('fName') : $('fName')).focus();
}

async function saveItem() {
  const body = {
    code: $('fCode').value, name: $('fName').value, unit: $('fUnit').value,
    group: $('fGroup').value || null,
    aliases: $('fAliases').value.split(/[,\n]/).map((a) => a.trim()).filter(Boolean),
  };
  const err = $('fErr');
  if (!body.name.trim()) { err.textContent = 'Item name chahiye.'; err.classList.remove('hidden'); return; }
  const was = state.editing;
  try {
    const saved = await api(was ? `/api/items/${encodeURIComponent(was)}` : '/api/items', {
      method: was ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }, 1);
    $('itemDlg').close();
    toast(was ? `${saved.name} updated` : `${saved.name} added`);
    loadItems();
  } catch (e) {
    err.textContent = e.network ? 'Network nahi hai, dobara Save dabayein.' : e.message;
    err.classList.remove('hidden');
  }
}

async function deleteItem() {
  const code = state.editing;
  const it = (state.items || []).find((i) => i.code === code);
  if (!code || !confirm(`Remove ${it ? it.name : code}? Old orders keep their item names.`)) return;
  try {
    await api(`/api/items/${encodeURIComponent(code)}`, { method: 'DELETE' }, 1);
    $('itemDlg').close();
    toast(`${it ? it.name : code} removed`);
    loadItems();
  } catch (e) { $('fErr').textContent = e.message; $('fErr').classList.remove('hidden'); }
}

function micPill() {
  const e = micEngine();
  const label = { sarvam: 'Mic: Sarvam AI', browser: 'Mic: browser', record: 'Mic: record only', none: 'Mic: not available' }[e];
  const canSwitch = state.cfg?.server_stt && SR && hasRecorder();
  return `<span class="pill ${e === 'none' ? 'off' : ''}" data-mic ${canSwitch ? 'role="button" tabindex="0" title="Tap to switch speech engine" style="cursor:pointer"' : ''}>${label}${canSwitch ? ' ⇄' : ''}</span>`;
}
function toggleMic() {
  if (!(state.cfg?.server_stt && SR && hasRecorder())) return;
  const next = micEngine() === 'sarvam' ? 'browser' : 'sarvam';
  try { localStorage.setItem('bko-mic', next); } catch (_) {}
  $('pills').querySelector('[data-mic]').outerHTML = micPill();
  $('pills').querySelector('[data-mic]').addEventListener('click', toggleMic);
  toast(next === 'sarvam' ? 'Ab Sarvam AI sunega' : 'Ab browser sunega');
}

async function init() {
  initTheme();
  try { state.cfg = await api('/api/config'); } catch (_) { state.cfg = { test_phrases: [] }; }
  const c = state.cfg;
  $('pills').innerHTML = [
    micPill(),
    c.server_stt ? '<span class="pill">Uploads: on</span>' : '<span class="pill off" title="' + esc(c.stt_message) + '">Speech key not set</span>',
  ].join('');
  $('pills').querySelector('[data-mic]')?.addEventListener('click', toggleMic);
  $('samples').innerHTML = (c.test_phrases || []).map((p, i) => `<button class="chip" data-i="${i}">${esc(p.text)}</button>`).join('');
  $('samplesCount').textContent = (c.test_phrases || []).length || '';
  $('samples').querySelectorAll('.chip').forEach((b) => b.onclick = () => { state.source = 'typed'; showTranscript(c.test_phrases[b.dataset.i].text, false); });

  bindMic($('micOrder'), { onInterim: (t) => ($('liveText').textContent = t), onResult: (r) => { $('liveText').textContent = ''; handleCaptured(r, 'mic'); } });
  answerMic = bindMic($('micAnswer'), { onInterim: (t) => ($('answerLive').textContent = t), onResult: (r) => {
    if (!r.text) { $('answerLive').textContent = ''; return; }
    sendAnswer(r.text);
  } });
  dispatchMic = bindMic($('micDispatch'), { onInterim: (t) => { $('dispatchBox').classList.remove('hidden'); $('dispatchBox').textContent = t; }, onResult: handleDispatch });

  $('fileInput').onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    state.blob = f; state.blobName = f.name; e.target.value = '';
    state.source = 'upload';
    sendRecording();
  };
  $('typedGo').onclick = () => { state.source = 'typed'; showTranscript($('typed').value, false); };
  $('baseSave').onclick = saveBaseline;
  // Pilot clock: starts when staff begin an order (mic, recording, paste, type, sample).
  const startClock = () => { if (!state.startedAt) state.startedAt = Date.now(); };
  ['micOrder', 'pasteOpen', 'typedOpen'].forEach((id) => {
    $(id).addEventListener('pointerdown', startClock);
    $(id).addEventListener('click', startClock);
  });
  $('fileInput').addEventListener('click', startClock);
  $('samples').addEventListener('click', startClock, true);
  try { $('testOrder').checked = localStorage.getItem('bko-test') === '1'; } catch (_) {}
  $('testOrder').onchange = () => { try { localStorage.setItem('bko-test', $('testOrder').checked ? '1' : '0'); } catch (_) {} };
  $('trGo').onclick = parseTranscript;
  $('trText').addEventListener('focus', () => clearTimeout(state.autoTimer));
  $('trRetry').onclick = sendRecording;
  $('trAgain').onclick = () => { clearTimeout(state.autoTimer); show('order'); };
  $('ansGo').onclick = () => { sendAnswer($('ansTyped').value); $('ansTyped').value = ''; };
  $('cfConfirm').onclick = saveOrder;
  $('cfBack').onclick = () => { state.carry = state.draft?.stats || null; showTranscript(state.draft?.heard || '', false, 'Text theek karein, phir Samjho dabayein.'); clearTimeout(state.autoTimer); };
  $('dnPrint').onclick = () => window.print();
  $('dnNew').onclick = () => { state.draft = null; state.blob = null; state.startedAt = null; show('order'); };
  const openCard = (id, field) => {
    ['pasteCard', 'typedCard'].forEach((c) => { if (c !== id) $(c).classList.add('hidden'); });
    const c = $(id); c.classList.toggle('hidden');
    if (!c.classList.contains('hidden')) { $(field).focus(); c.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  };
  $('typedOpen').onclick = () => openCard('typedCard', 'typed');
  $('pasteOpen').onclick = () => openCard('pasteCard', 'pasted');
  if (navigator.clipboard?.readText) {
    $('pasteClip').classList.remove('hidden');
    $('pasteClip').onclick = async () => {
      try { $('pasted').value = await navigator.clipboard.readText(); } catch (_) { toast('Clipboard nahi khula. Box mein long-press karke Paste karein.'); }
    };
  }
  $('pasteGo').onclick = () => {
    const t = $('pasted').value.trim();
    if (!t) return toast('Pehle transcript paste karein');
    state.blob = null; state.textKind = 'transcript';
    $('trText').value = t;
    parseTranscript();
  };
  $('ordFilter').querySelectorAll('button').forEach((b) => b.onclick = () => {
    state.filter = b.dataset.f;
    $('ordFilter').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    renderOrders();
  });
  initItems();
  renderQueuePill();
  flushQueue();
  window.addEventListener('online', flushQueue);
  setInterval(() => { if (readQueue().length) flushQueue(); }, 30000);
  if (c.demo) {
    $('demoCard').classList.remove('hidden');
    $('demoReset').onclick = async () => {
      if ($('demoConfirm').value.trim() !== 'RESET') return toast('Pakka karne ke liye RESET likhein');
      try { await post('/api/demo/reset', { confirm: 'RESET' }); toast('Demo data saaf ho gaya'); setTimeout(() => location.reload(), 800); }
      catch (e) { toast(e.message, 4000); }
    };
  }
  window.addEventListener('hashchange', route);
  route();
}
init();

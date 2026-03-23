'use strict';

// ===== VOICES =====
const VOICES = ['alloy','ash','ballad','coral','echo','fable','nova','onyx','sage','shimmer','verse'];
const DEFAULT_VOICE = 'coral';

// ===== DOM REFS =====
const $ = id => document.getElementById(id);

const modalOverlay   = $('modal-overlay');
const inputApiKey    = $('input-api-key');
const btnSaveKey     = $('btn-save-key');
const btnOpenKey     = $('btn-open-key');
const btnCloseModal  = $('btn-close-modal');
const btnCloseModal2 = $('btn-close-modal-2');
const modalFeedback  = $('modal-feedback');
const keyIndicator   = $('key-indicator');

const tabs          = document.querySelectorAll('.tab');
const panelIA       = $('panel-ia');
const inputTema     = $('input-tema');
const inputLinhas   = $('input-linhas');
const btnGerarHist  = $('btn-gerar-historia');
const iaSpinner     = $('ia-spinner');

const inputTitulo   = $('input-titulo');
const inputTexto    = $('input-texto');

const inputUrl      = $('input-url');
const inputPasta    = $('input-pasta');
const selectVoz     = $('select-voz');
const btnOuvir      = $('btn-ouvir');
const audioPreview  = $('audio-preview');
const audioBar      = $('audio-bar');
const audioProgress = $('audio-progress');
const audioLabel    = $('audio-label');
const inputInst     = $('input-instrucoes');
const formError     = $('form-error');
const btnGerarVid   = $('btn-gerar-videos');

const sectionProg   = $('section-progress');
const progressBadge = $('progress-badge');
const logEl         = $('log');

const sectionResult = $('section-result');
const videoVertical = $('video-vertical');
const videoPaisagem = $('video-paisagem');
const dlVertical    = $('dl-vertical');
const dlPaisagem    = $('dl-paisagem');

// ===== STATE =====
let currentTab = 'manual';
let isPlaying  = false;

// ===== INIT =====
function init() {
  populateVoices();
  checkKeyStatus();
  setupAudioProgress();
}

// ===== VOICES =====
function populateVoices() {
  VOICES.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v.charAt(0).toUpperCase() + v.slice(1);
    if (v === DEFAULT_VOICE) opt.selected = true;
    selectVoz.appendChild(opt);
  });
}

// ===== API KEY =====
async function checkKeyStatus() {
  try {
    const res = await fetch('/api/key-status');
    const data = await res.json();
    keyIndicator.classList.toggle('ok', data.configured);
  } catch {}
}

function openModal() {
  modalOverlay.classList.remove('hidden');
  inputApiKey.focus();
  clearModalFeedback();
}

function closeModal() {
  modalOverlay.classList.add('hidden');
  clearModalFeedback();
}

function clearModalFeedback() {
  modalFeedback.textContent = '';
  modalFeedback.className = 'hidden';
}

function showModalFeedback(msg, type) {
  modalFeedback.textContent = msg;
  modalFeedback.className = type === 'error' ? 'alert alert-error' : 'alert alert-success';
}

async function saveKey() {
  const key = inputApiKey.value.trim();
  if (!key.startsWith('sk-')) {
    showModalFeedback('A chave deve comecar com sk-', 'error');
    return;
  }
  btnSaveKey.disabled = true;
  btnSaveKey.textContent = 'Salvando...';
  try {
    const res = await fetch('/api/save-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    if (res.ok) {
      showModalFeedback('Chave salva com sucesso!', 'success');
      keyIndicator.classList.add('ok');
      setTimeout(closeModal, 1200);
    } else {
      const err = await res.json();
      showModalFeedback(err.detail || 'Erro ao salvar.', 'error');
    }
  } catch {
    showModalFeedback('Erro de conexao com o servidor.', 'error');
  } finally {
    btnSaveKey.disabled = false;
    btnSaveKey.textContent = 'Salvar';
  }
}

// ===== TABS =====
function switchTab(tab) {
  currentTab = tab;
  tabs.forEach(btn => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active);
  });
  panelIA.classList.toggle('hidden', tab !== 'ia');
}

// ===== AUDIO PREVIEW =====
function setupAudioProgress() {
  audioPreview.addEventListener('timeupdate', () => {
    if (!audioPreview.duration) return;
    const pct = (audioPreview.currentTime / audioPreview.duration) * 100;
    audioProgress.style.width = pct + '%';
  });
  audioPreview.addEventListener('ended', () => {
    audioProgress.style.width = '0%';
    btnOuvir.textContent = '\u25B6 Ouvir';
    isPlaying = false;
  });
}

function playVoiceSample() {
  const voz = selectVoz.value;
  if (isPlaying) {
    audioPreview.pause();
    audioPreview.currentTime = 0;
    audioProgress.style.width = '0%';
    btnOuvir.textContent = '\u25B6 Ouvir';
    isPlaying = false;
    return;
  }
  audioPreview.src = `/api/voice-sample/${voz}`;
  audioLabel.textContent = voz;
  audioBar.classList.remove('hidden');
  audioPreview.play().then(() => {
    btnOuvir.textContent = '\u23F8 Parar';
    isPlaying = true;
  }).catch(() => {
    showError('Amostra de voz nao disponivel para ' + voz);
  });
}

selectVoz.addEventListener('change', () => {
  if (isPlaying) {
    audioPreview.pause();
    audioPreview.currentTime = 0;
    audioProgress.style.width = '0%';
    btnOuvir.textContent = '\u25B6 Ouvir';
    isPlaying = false;
  }
  audioBar.classList.add('hidden');
});

// ===== GENERATE STORY =====
async function gerarHistoria() {
  const tema = inputTema.value.trim();
  if (!tema) { inputTema.focus(); return; }

  btnGerarHist.disabled = true;
  iaSpinner.classList.remove('hidden');

  try {
    const res = await fetch('/api/generate-story', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tema, num_linhas: parseInt(inputLinhas.value) || 10 }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Erro ao gerar historia.');
      return;
    }
    const data = await res.json();
    inputTitulo.value = data.titulo;
    inputTexto.value  = data.texto;
    inputTitulo.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch {
    alert('Erro de conexao com o servidor.');
  } finally {
    btnGerarHist.disabled = false;
    iaSpinner.classList.add('hidden');
  }
}

// ===== FORM ERROR =====
function showError(msg) {
  formError.textContent = msg;
  formError.classList.remove('hidden');
  formError.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
function clearError() {
  formError.textContent = '';
  formError.classList.add('hidden');
}

// ===== GENERATE VIDEOS =====
async function gerarVideos() {
  clearError();

  const url     = inputUrl.value.trim();
  const titulo  = inputTitulo.value.trim();
  const texto   = inputTexto.value.trim();
  const pasta   = inputPasta.value.trim() || 'video_narrado';
  const voz     = selectVoz.value;
  const inst    = inputInst.value.trim();

  if (!url)    { showError('Informe o link do video do YouTube.'); return; }
  if (!titulo) { showError('Informe o titulo.'); return; }
  if (!texto)  { showError('Informe o texto da narracao.'); return; }

  btnGerarVid.disabled = true;
  btnGerarVid.textContent = 'Iniciando...';
  sectionResult.classList.add('hidden');
  resetLog();
  showSection(sectionProg);
  setBadge('running');

  let jobId;
  try {
    const res = await fetch('/api/generate-videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, titulo, texto, pasta_saida: pasta, voz, instrucoes: inst }),
    });
    if (!res.ok) {
      const err = await res.json();
      showError(err.detail || 'Erro ao iniciar geracao.');
      btnGerarVid.disabled = false;
      btnGerarVid.textContent = 'Gerar videos';
      sectionProg.classList.add('hidden');
      return;
    }
    const data = await res.json();
    jobId = data.job_id;
  } catch {
    showError('Erro de conexao com o servidor.');
    btnGerarVid.disabled = false;
    btnGerarVid.textContent = 'Gerar videos';
    sectionProg.classList.add('hidden');
    return;
  }

  btnGerarVid.textContent = 'Gerando...';
  listenJobStream(jobId);
}

// ===== SSE STREAM =====
function listenJobStream(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);

  es.onmessage = e => {
    appendLog(JSON.parse(e.data));
  };

  es.addEventListener('done', e => {
    es.close();
    const data = JSON.parse(e.data);
    appendLog('Renderizacao concluida!', false);
    setBadge('done');
    showVideos(data.result);
    btnGerarVid.disabled = false;
    btnGerarVid.textContent = 'Gerar videos';
  });

  es.addEventListener('error-event', e => {
    es.close();
    const data = JSON.parse(e.data);
    appendLog('ERRO: ' + data.error, true);
    setBadge('error');
    btnGerarVid.disabled = false;
    btnGerarVid.textContent = 'Gerar videos';
  });

  // Fallback: SSE connection error
  es.onerror = () => {
    es.close();
    appendLog('Conexao interrompida.', true);
    setBadge('error');
    btnGerarVid.disabled = false;
    btnGerarVid.textContent = 'Gerar videos';
  };
}

// ===== LOG =====
function resetLog() {
  logEl.innerHTML = '';
}
function appendLog(msg, isError = false) {
  const line = document.createElement('div');
  line.className = 'log-line' + (isError ? ' error' : '');
  line.textContent = msg;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

// ===== BADGE =====
function setBadge(state) {
  progressBadge.className = 'badge badge-' + state;
  const labels = { running: 'Processando', done: 'Concluido', error: 'Erro' };
  progressBadge.textContent = labels[state] || state;
}

// ===== SHOW VIDEOS =====
function showVideos(paths) {
  // paths = ["video_narrado/video_vertical.mp4", "video_narrado/video_paisagem.mp4"]
  const vertical = paths.find(p => p.includes('video_vertical'));
  const paisagem = paths.find(p => p.includes('video_paisagem'));

  if (vertical) {
    videoVertical.src = '/files/' + vertical;
    dlVertical.href   = '/files/' + vertical;
    dlVertical.download = 'video_vertical.mp4';
  }
  if (paisagem) {
    videoPaisagem.src = '/files/' + paisagem;
    dlPaisagem.href   = '/files/' + paisagem;
    dlPaisagem.download = 'video_paisagem.mp4';
  }

  showSection(sectionResult);
  sectionResult.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ===== HELPERS =====
function showSection(el) {
  el.classList.remove('hidden');
  el.style.animation = 'fadeIn .2s ease';
}

// ===== EVENT LISTENERS =====
btnOpenKey.addEventListener('click', openModal);
btnCloseModal.addEventListener('click', closeModal);
btnCloseModal2.addEventListener('click', closeModal);
modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeModal(); });
inputApiKey.addEventListener('keydown', e => { if (e.key === 'Enter') saveKey(); });
btnSaveKey.addEventListener('click', saveKey);

tabs.forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

btnGerarHist.addEventListener('click', gerarHistoria);
inputTema.addEventListener('keydown', e => { if (e.key === 'Enter') gerarHistoria(); });

btnOuvir.addEventListener('click', playVoiceSample);
btnGerarVid.addEventListener('click', gerarVideos);

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !modalOverlay.classList.contains('hidden')) closeModal();
});

// ===== START =====
init();

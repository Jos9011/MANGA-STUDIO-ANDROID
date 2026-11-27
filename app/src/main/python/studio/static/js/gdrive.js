// Google Drive no app Android: login pelo Android (window.MangaDrive), dados por /api/gdrive/*.
// Fora do app (navegador comum), a seção fica escondida.
let gdriveItems = [];
let gdriveLoaded = false;
let gdriveInitDone = false;
let gdrivePollTimer = null;
let gdriveNotice = '';  // aviso do último download; vale mais que o contador por alguns segundos
let gdriveNoticeTimer = null;

function showGdriveNotice(text) {
  gdriveNotice = text;
  setGdriveMsg(text);
  clearTimeout(gdriveNoticeTimer);
  gdriveNoticeTimer = setTimeout(() => { gdriveNotice = ''; if (gdriveLoaded) renderGoogleDriveGrid(); }, 8000);
}

function gdriveAvailable() {
  try { return !!(window.MangaDrive && window.MangaDrive.isAvailable()); } catch (e) { return false; }
}

function setGdriveMsg(text) {
  const el = document.getElementById('gdrive-msg');
  if (el) el.textContent = text || '';
}

async function initGoogleDriveSection() {
  if (gdriveInitDone) return;
  gdriveInitDone = true;
  const sec = document.getElementById('gdrive-section');
  if (!sec || !gdriveAvailable()) return;
  sec.hidden = false;
  try {
    const st = await (await fetch('/api/gdrive/status')).json();
    if (st.root) document.getElementById('gdrive-root-name').textContent = st.root;
    if (st.connected) return loadGoogleDrive();
  } catch (e) { /* segue para a mensagem abaixo */ }
  setGdriveMsg('Toque em "Conectar" para ver aqui as obras da sua pasta do Google Drive.');
}

function connectGoogleDrive() {
  if (!gdriveAvailable()) return;
  setGdriveMsg('Abrindo o login do Google...');
  window.MangaDrive.connect();
}

window.onDriveAuthResult = function (ok, message) {
  if (ok) {
    setGdriveMsg('Carregando obras do Google Drive...');
    loadGoogleDrive();
  } else {
    setGdriveMsg(message || 'Não foi possível conectar ao Google Drive.');
  }
};

async function loadGoogleDrive() {
  const btn = document.getElementById('gdrive-connect-btn');
  try {
    const res = await fetch('/api/gdrive/list');
    const data = await res.json();
    if (res.status === 401) {
      gdriveLoaded = false;
      if (btn) btn.textContent = 'Conectar';
      setGdriveMsg('A conexão com o Google Drive expirou. Toque em "Conectar".');
      return;
    }
    if (!res.ok) {
      setGdriveMsg(data.message || 'Erro ao listar o Google Drive.');
      return;
    }
    gdriveItems = data.items || [];
    gdriveLoaded = true;
    if (btn) btn.textContent = 'Recarregar';
    renderGoogleDriveGrid();
  } catch (e) {
    setGdriveMsg('Erro ao listar o Google Drive: ' + e);
  }
}

function formatDriveSize(bytes) {
  if (!bytes) return '';
  return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
}

function gdriveCard(it) {
  const id = escapeHtml(it.id);
  const sub = it.kind === 'folder' ? 'Pasta de imagens' : ('Arquivo ' + formatDriveSize(it.size));
  const action = it.local_path
    ? `<button class="card-action-btn primary" onclick="event.stopPropagation(); inspectFolder('${escapeQuotes(it.local_path)}'); switchTab('translate');">Traduzir</button>`
    : `<button class="card-action-btn primary" onclick="event.stopPropagation(); downloadFromDrive('${escapeQuotes(it.id)}');">Baixar</button>`;
  const icon = it.kind === 'folder'
    ? '<path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>'
    : '<path d="M20 6h-4V4c0-1.1-.9-2-2-2h-4c-1.1 0-2 .9-2 2v2H4c-1.1 0-2 .9-2 2v11c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 0h-4V4h4v2z"/>';
  return `
    <div class="manga-card">
      <div class="card-thumb gdrive-thumb"><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>
        <div class="card-tags"><span class="tag info">Google Drive</span>${it.local_path ? '<span class="tag ok">No celular</span>' : ''}</div>
      </div>
      <div class="card-title" title="${escapeHtml(it.name)}">${escapeHtml(it.name)}</div>
      <div class="card-subtitle" id="gdl-${id}">${escapeHtml(sub)}</div>
      <div class="card-actions-row">${action}</div>
    </div>`;
}

function renderGoogleDriveGrid() {
  const grid = document.getElementById('gdrive-grid');
  if (!grid) return;
  const q = (document.getElementById('library-search')?.value || '').trim();
  const items = gdriveItems.filter(it => mangaMatchesSearch(it.name, q));
  grid.innerHTML = items.map(gdriveCard).join('') ||
    `<div class="library-empty">${q ? `Nenhuma obra do Drive encontrada para "${escapeHtml(q)}".` : 'Nenhuma pasta ou arquivo ZIP/CBZ na pasta do Drive.'}</div>`;
  setGdriveMsg(gdriveNotice || (q ? `Encontrados: ${items.length} de ${gdriveItems.length} no Google Drive`
    : `${gdriveItems.length} obra(s) no Google Drive. "Baixar" copia a obra para o celular.`));
}

async function downloadFromDrive(id) {
  const it = gdriveItems.find(x => x.id === id);
  if (!it) return;
  const res = await fetch('/api/gdrive/download', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: it.id, name: it.name, kind: it.kind })
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) { setGdriveMsg('A conexão expirou. Conectando de novo...'); return connectGoogleDrive(); }
  if (!res.ok) { setGdriveMsg(data.message || 'Não foi possível iniciar o download.'); return; }
  setGdriveMsg('Baixando "' + it.name + '"...');
  clearInterval(gdrivePollTimer);
  gdrivePollTimer = setInterval(async () => {
    const st = await (await fetch('/api/gdrive/download_status')).json().catch(() => ({}));
    const label = document.getElementById('gdl-' + it.id);
    if (st.state === 'running') {
      if (label) label.textContent = st.total ? `Baixando ${st.done}/${st.total}...` : 'Baixando...';
      return;
    }
    clearInterval(gdrivePollTimer);
    if (st.state === 'done') {
      it.local_path = st.path;
      showGdriveNotice('"' + it.name + '" foi baixada para o celular. Toque em "Traduzir".');
      renderGoogleDriveGrid();
      loadLibrary();
    } else if (st.state === 'error') {
      showGdriveNotice('Falha ao baixar "' + it.name + '": ' + (st.error || 'erro desconhecido'));
      if (label) label.textContent = 'Falha no download';
    }
  }, 1000);
}

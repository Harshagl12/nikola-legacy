/*
 * Legacy renderer retained only for source-history compatibility.
 * index.html loads app-v2.js, whose API calls are centralized in
 * services/api-client.js.
 */
/* const API_BASE = 'http://127.0.0.1:8000';
const ballView = document.getElementById('ball-view');
const workspaceView = document.getElementById('workspace-view');
const ball = document.getElementById('assistant-ball');
const messages = document.getElementById('messages');
const input = document.getElementById('chat-input');
const composer = document.getElementById('composer');
const typing = document.getElementById('typing');
const stopButton = document.getElementById('stop-btn');
const fileInput = document.getElementById('file-input');
const runtimeLabel = document.getElementById('runtime-label');
const runtimeDot = document.getElementById('runtime-dot');
const connectionCopy = document.getElementById('connection-copy');
let conversationId = null;
let activeController = null;
let mediaRecorder = null;
let audioChunks = [];

function setMode(mode) {
  const workspace = mode === 'workspace';
  ballView.classList.toggle('hidden', workspace);
  workspaceView.classList.toggle('hidden', !workspace);
  if (workspace) input.focus();
}

function setRuntime(state, copy) {
  runtimeLabel.textContent = state;
  runtimeDot.className = `state-dot ${state === 'READY' ? 'ready' : state === 'OFFLINE' || state === 'ERROR' ? 'error' : ''}`;
  connectionCopy.textContent = copy;
  document.getElementById('backend-dot').className = `state-dot ${state === 'READY' ? 'ready' : 'error'}`;
}

async function api(path, options = {}) {
  const controller = options.signal ? null : new AbortController();
  const signal = options.signal || controller.signal;
  const timer = setTimeout(() => controller?.abort(), options.timeout || 8000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      signal,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    if (!response.ok) throw new Error(response.status === 401 ? 'Local backend authentication failed.' : `Backend request failed (${response.status}).`);
    return response;
  } finally { clearTimeout(timer); }
}

async function refreshStatus() {
  try {
    const response = await api('/status');
    const data = await response.json();
    setRuntime('READY', `Backend ready · ${data.indexed_files || 0} indexed files`);
    document.getElementById('rag-dot').className = 'state-dot ready';
    document.getElementById('voice-dot').className = data.voice_enabled ? 'state-dot ready' : 'state-dot';
    document.getElementById('model-label').textContent = data.models_loaded?.[0] || 'Qwen3 local';
  } catch (error) {
    setRuntime('OFFLINE', 'Unable to connect to Nikola local backend');
    document.getElementById('rag-dot').className = 'state-dot error';
  }
}

function clearEmpty() { document.querySelector('.empty-state')?.remove(); }
function appendMessage(role, text) {
  clearEmpty();
  const element = document.createElement('article');
  element.className = `message ${role}`;
  element.textContent = text;
  messages.appendChild(element);
  messages.scrollTop = messages.scrollHeight;
  return element;
}
function setGenerating(active) {
  typing.classList.toggle('hidden', !active);
  stopButton.classList.toggle('hidden', !active);
  document.getElementById('send-btn').classList.toggle('hidden', active);
}

async function streamAsk(query) {
  activeController = new AbortController();
  setGenerating(true);
  const response = await api('/ask', {
    method: 'POST',
    signal: activeController.signal,
    body: JSON.stringify({ query, use_rag: false, stream: true, conversation_id: conversationId })
  });
  if (response.headers.get('content-type')?.includes('application/json')) {
    const data = await response.json();
    conversationId = data.conversation_id || conversationId;
    appendMessage('ai', data.answer || 'Nikola returned no answer.');
    return;
  }
  const output = appendMessage('ai', '');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';
    for (const event of events) {
      if (!event.startsWith('data: ')) continue;
      const data = JSON.parse(event.slice(6));
      if (data.token) { output.textContent += data.token; messages.scrollTop = messages.scrollHeight; }
      if (data.conversation_id) conversationId = data.conversation_id;
      if (data.error) throw new Error(data.error);
    }
  }
  return output;
}

async function sendMessage() {
  const query = input.value.trim();
  if (!query || activeController) return;
  input.value = ''; input.style.height = 'auto';
  appendMessage('user', query);
  try { await streamAsk(query); }
  catch (error) { if (error.name !== 'AbortError') appendMessage('ai', error.message || 'Nikola could not complete the local request.'); }
  finally { activeController = null; setGenerating(false); input.focus(); }
}

async function loadDocuments() {
  const list = document.getElementById('documents-list');
  try {
    const data = await (await api('/rag/files')).json();
    list.textContent = '';
    for (const file of data.files || []) {
      const card = document.createElement('article'); card.className = 'document-card';
      const title = document.createElement('h3'); title.textContent = file.filename;
      const meta = document.createElement('p'); meta.textContent = `${file.chunks} chunks · ${(file.size_bytes / 1048576).toFixed(1)} MB`;
      const remove = document.createElement('button'); remove.textContent = 'Remove'; remove.onclick = async () => { await api('/rag/remove', { method: 'POST', body: JSON.stringify({ filename: file.filename }) }); loadDocuments(); };
      card.append(title, meta, remove); list.appendChild(card);
    }
    if (!list.children.length) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'No documents indexed yet.'; list.appendChild(empty); }
  } catch (error) { list.textContent = 'Document vault is unavailable.'; }
}

async function uploadFiles(files) {
  for (const file of files) {
    try { await api('/index', { method: 'POST', body: JSON.stringify({ file_path: file.path || file.name }) }); }
    catch (error) { appendMessage('ai', `Could not index ${file.name}: ${error.message}`); }
  }
  loadDocuments();
}

function showView(name) {
  document.querySelectorAll('.view').forEach(view => view.classList.remove('active-view'));
  document.getElementById(`${name}-view`).classList.add('active-view');
  document.getElementById('view-title').textContent = name === 'chat' ? 'Conversation' : name === 'documents' ? 'Document vault' : 'Workflows';
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === name));
  if (name === 'documents') loadDocuments();
}

ball.addEventListener('click', event => {
  if (dragging) { dragging = false; return; }
  window.api.openWorkspace();
});
ball.addEventListener('dblclick', () => window.api.openWorkspace());
ball.addEventListener('contextmenu', event => { event.preventDefault(); window.api.showBallMenu(); });
let dragging = false;
let dragOffset = null;
ball.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  dragging = false;
  dragOffset = { x: event.screenX - window.screenX, y: event.screenY - window.screenY };
  ball.setPointerCapture(event.pointerId);
});
ball.addEventListener('pointermove', event => {
  if (!dragOffset || !ball.hasPointerCapture(event.pointerId)) return;
  if (Math.abs(event.movementX) + Math.abs(event.movementY) > 1) dragging = true;
  window.api.moveBall({ x: event.screenX - dragOffset.x, y: event.screenY - dragOffset.y });
});
ball.addEventListener('pointerup', event => {
  if (ball.hasPointerCapture(event.pointerId)) ball.releasePointerCapture(event.pointerId);
  dragOffset = null;
  if (dragging) { event.stopPropagation(); }
});
document.getElementById('hide-btn').onclick = () => window.api.showBall();
document.getElementById('quit-btn').onclick = () => window.api.quit();
document.getElementById('new-chat-btn').onclick = () => { messages.textContent = ''; conversationId = null; showView('chat'); input.focus(); };
document.querySelectorAll('[data-view]').forEach(item => item.onclick = () => showView(item.dataset.view));
document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => { input.value = button.dataset.prompt; input.focus(); sendMessage(); });
composer.addEventListener('submit', event => { event.preventDefault(); sendMessage(); });
input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; });
input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } if (event.key === 'Escape' && activeController) activeController.abort(); });
stopButton.onclick = () => activeController?.abort();
document.getElementById('attach-btn').onclick = () => fileInput.click();
fileInput.onchange = () => uploadFiles(fileInput.files);
document.getElementById('add-docs-btn').onclick = () => fileInput.click();
document.getElementById('clear-docs-btn').onclick = async () => { if (confirm('Clear all indexed documents?')) { await api('/rag/clear-all', { method: 'POST', body: JSON.stringify({ confirm: true }) }); loadDocuments(); } };

window.api.onWindowMode(setMode);
window.api.onNewChat(() => { messages.textContent = ''; conversationId = null; showView('chat'); });
window.api.onRestartBackend(() => refreshStatus());
window.api.onOpenView(view => { setMode('workspace'); showView(view); });
setMode('ball');
refreshStatus();
setInterval(refreshStatus, 15000); */

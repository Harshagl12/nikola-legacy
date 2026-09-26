(function startNikolaWorkspace() {
  'use strict';

  const api = window.NikolaApi;
  const ui = window.NikolaUi;
  const desktop = window.api;
  if (!api || !ui || !desktop) return;

  const state = {
    conversationId: null,
    activeController: null,
    lastPrompt: '',
    mode: 'ball',
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
  };

  document.body.innerHTML = `
    <div id="nikola-shell" data-mode="ball">
      <main id="assistant-ball-view" aria-label="Nikola assistant">
        <button id="assistant-ball" class="assistant-orb" type="button" title="Open Nikola">
          <span class="orb-halo"></span><span class="orb-core"><i></i></span>
          <span class="orb-wordmark">N</span><span id="orb-status" class="orb-status">INITIALIZING</span>
        </button>
      </main>
      <main id="workspace" class="workspace hidden" aria-label="Nikola workspace">
        <header class="desktop-titlebar">
          <button id="brand-home" class="brand-lockup" type="button" title="Return to conversation"><span>✦</span><b>NIKOLA</b><em>PRIVATE LOCAL AI</em></button>
          <div class="header-conversation"><span id="conversation-title">New conversation</span><small>Private on this device</small></div>
          <div class="header-runtime"><span id="header-dot" class="runtime-dot pending"></span><span id="header-state">INITIALIZING</span><span id="header-model">Local model</span></div>
          <button id="command-center-toggle" class="header-panel-toggle" type="button" aria-expanded="false" title="Open Command Center">Command Center</button>
          <div class="desktop-controls"><button id="hide-workspace" type="button" title="Return to assistant orb">−</button><button id="quit-nikola" type="button" title="Quit Nikola">×</button></div>
        </header>
        <div class="desktop-layout">
          <aside id="sidebar" class="workspace-sidebar">
            <div class="sidebar-top"><button id="sidebar-toggle" class="icon-button" type="button" title="Collapse navigation">☰</button><button id="new-chat" class="new-chat-button" type="button"><span>＋</span><b>New chat</b></button></div>
            <label class="sidebar-search"><span>⌕</span><input id="conversation-search" type="search" placeholder="Search chats" autocomplete="off"></label>
            <nav class="workspace-nav" aria-label="Workspace navigation">
              <p class="nav-caption">CONVERSATIONS</p>
              <button class="nav-link active" data-panel="chat" type="button" title="Conversation"><span>◈</span><b>Conversation</b></button>
              <div class="conversation-stub"><small>TODAY</small><button type="button" class="chat-history-item active">New conversation</button></div>
              <p class="nav-caption">WORKSPACE</p>
              <button class="nav-link" data-panel="documents" type="button" title="Document vault"><span>▧</span><b>Documents</b></button>
              <button class="nav-link" data-panel="vision" type="button" title="Vision"><span>◉</span><b>Vision</b></button>
              <button class="nav-link" data-panel="voice" type="button" title="Voice"><span>◌</span><b>Voice</b></button>
              <button class="nav-link" data-panel="workflows" type="button" title="Workflows"><span>◇</span><b>Workflows</b></button>
            </nav>
            <section class="system-health" aria-label="Verified system status"><p class="nav-caption">SYSTEM</p><div><i id="side-backend" class="runtime-dot pending"></i><span>Backend</span><small id="side-backend-label">Starting</small></div><div><i id="side-model" class="runtime-dot pending"></i><span>Model</span><small id="side-model-label">Loading</small></div><div><i id="side-rag" class="runtime-dot pending"></i><span>RAG</span><small id="side-rag-label">Loading</small></div><div><i id="side-vision" class="runtime-dot muted"></i><span>Vision</span><small id="side-vision-label">Unavailable</small></div></section>
            <button class="nav-link settings-link" data-panel="settings" type="button" title="Settings"><span>⚙</span><b>Settings</b></button>
          </aside>
          <section class="workspace-content">
            <section id="panel-chat" class="content-panel active">
              <div class="panel-header chat-panel-header"><div><p class="eyebrow">CONVERSATION</p><h1>Ask Nikola</h1></div><label class="rag-control" title="Use only verified material from your indexed documents"><input id="rag-toggle" type="checkbox"><span>Use document vault</span></label></div>
              <div id="command-palette" class="command-palette hidden" role="listbox" aria-label="Nikola commands"></div>
              <div id="connection-banner" class="connection-banner hidden"><span></span><p>Unable to connect to Nikola’s local backend.</p><button id="reconnect" type="button">Reconnect</button><button id="restart-backend" type="button">Restart backend</button></div>
              <div id="messages" class="message-scroll" aria-live="polite"></div>
              <div id="generation-state" class="generation-state hidden"><span></span><span></span><span></span><b>Generating locally</b></div>
              <form id="composer" class="ai-composer"><button id="attach-document" type="button" class="composer-icon" title="Add a document">＋</button><textarea id="prompt-input" rows="1" placeholder="Ask Nikola anything…" aria-label="Message Nikola"></textarea><button id="voice-trigger" type="button" class="composer-icon" title="Start voice input">◌</button><button id="stop-generation" type="button" class="composer-stop hidden" title="Stop generation">■</button><button id="send-message" type="submit" class="composer-send" title="Send message">↑</button></form>
              <p class="composer-hint">Enter to send · Shift + Enter for a new line · Esc to stop</p>
            </section>
            <section id="panel-documents" class="content-panel"><div class="panel-header"><div><p class="eyebrow">LOCAL KNOWLEDGE</p><h1>Document vault</h1><p id="vault-summary" class="quiet-copy">Loading document inventory…</p></div><button id="add-documents" class="primary-action" type="button">＋ Add documents</button></div><div id="document-list" class="vault-grid"></div><button id="clear-vault" class="quiet-danger" type="button">Clear all vault data</button></section>
            <section id="panel-vision" class="content-panel"><div class="panel-header"><div><p class="eyebrow">LOCAL VISION</p><h1>Screen assistant</h1><p class="quiet-copy">Nikola can analyze the current desktop when the installed local model supports it.</p></div></div><div class="feature-card"><label for="vision-prompt">What would you like Nikola to inspect?</label><textarea id="vision-prompt" rows="3" placeholder="Explain what is on my current screen…"></textarea><button id="analyze-screen" class="primary-action" type="button">Analyze current screen</button><pre id="vision-result" class="feature-result hidden"></pre></div></section>
            <section id="panel-voice" class="content-panel"><div class="panel-header"><div><p class="eyebrow">VOICE</p><h1>Voice input</h1><p class="quiet-copy">Microphone access starts only after you select the control below.</p></div></div><div class="feature-card voice-card"><button id="voice-record" class="voice-orb" type="button"><span>◉</span></button><h2 id="voice-state">Ready when you are</h2><p class="quiet-copy">Record a question, then Nikola will place the local transcription in the composer.</p></div></section>
            <section id="panel-workflows" class="content-panel"><div class="panel-header"><div><p class="eyebrow">AUTOMATION</p><h1>My workflows</h1><p class="quiet-copy">Only workflows confirmed through Nikola are shown here.</p></div></div><div id="workflow-list" class="workflow-grid"></div></section>
            <section id="panel-settings" class="content-panel"><div class="panel-header"><div><p class="eyebrow">SETTINGS</p><h1>Local configuration</h1><p class="quiet-copy">Nikola is configured for local processing. No cloud model or telemetry is enabled here.</p></div></div><div class="settings-grid"><article class="settings-card"><h2>Models</h2><div id="model-list" class="model-list"><p class="quiet-copy">Loading configured local models…</p></div></article><article class="settings-card"><h2>Privacy</h2><p>Processing stays on this device.</p><p>No cloud LLM configured.</p><p>No telemetry configured.</p></article><article class="settings-card"><h2>Appearance</h2><p>Dark desktop workspace with a collapsible navigation rail.</p></article></div></section>
          </section>
          <aside id="command-center" class="command-center" aria-label="Command Center">
            <div class="command-center-header"><div><p class="eyebrow">COMMAND CENTER</p><h2>Local pipeline</h2></div><button id="command-center-close" class="icon-button" type="button" title="Close Command Center">×</button></div>
            <section class="command-section"><h3>Runtime</h3><div class="command-status-row"><span id="center-backend-dot" class="runtime-dot pending"></span><span>Backend</span><b id="center-backend-label">Starting</b></div><div class="command-status-row"><span id="center-model-dot" class="runtime-dot pending"></span><span>Model</span><b id="center-model-label">Loading</b></div><div class="command-status-row"><span id="center-rag-dot" class="runtime-dot pending"></span><span>RAG</span><b id="center-rag-label">Loading</b></div><div class="command-status-row"><span id="center-vision-dot" class="runtime-dot muted"></span><span>Vision</span><b id="center-vision-label">Unavailable</b></div></section>
            <section class="command-section"><h3>Activity</h3><p id="center-activity" class="command-empty">Waiting for a local task.</p></section>
            <section class="command-section"><h3>Sources</h3><div id="center-sources" class="command-sources"><p class="command-empty">No retrieved sources.</p></div></section>
            <section class="command-section"><h3>Privacy</h3><p class="offline-badge"><span class="runtime-dot ready"></span> OFFLINE MODE</p><p class="command-copy">Inference, retrieval, and file indexing stay on this device.</p></section>
          </aside>
        </div>
      </main>
      <div id="confirm-dialog" class="dialog-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><div class="confirm-dialog"><p class="eyebrow">DESTRUCTIVE ACTION</p><h2 id="confirm-title">Clear document vault?</h2><p>This permanently removes all indexed documents and their local retrieval data.</p><div><button id="cancel-clear" class="secondary-action" type="button">Cancel</button><button id="confirm-clear" class="danger-action" type="button">Clear vault</button></div></div></div>
      <div id="toast" class="toast hidden" role="status"></div>
    </div>`;

  const $ = (selector) => document.querySelector(selector);
  const messages = $('#messages');
  const input = $('#prompt-input');
  const toast = $('#toast');
  let toastTimer;
  const commands = [
    { name: '/ask', description: 'Ask Nikola a local question', action: () => input.focus() },
    { name: '/docs', description: 'Open the document vault', action: () => activatePanel('documents') },
    { name: '/files', description: 'Add local documents', action: chooseDocuments },
    { name: '/vision', description: 'Open screen assistant', action: () => activatePanel('vision') },
    { name: '/voice', description: 'Open voice input', action: () => activatePanel('voice') },
    { name: '/tools', description: 'Open local pipeline activity', action: () => $('#command-center-toggle').click() },
    { name: '/memory', description: 'Open local configuration', action: () => activatePanel('settings') },
    { name: '/status', description: 'Open Command Center', action: () => $('#command-center-toggle').click() },
  ];
  let activeCommand = -1;

  function showToast(message) {
    toast.textContent = message;
    toast.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add('hidden'), 4_000);
  }

  function setCenterActivity(message) {
    $('#center-activity').textContent = message;
  }

  function setCenterSources(sources) {
    const target = $('#center-sources');
    target.replaceChildren();
    if (!sources?.length) { target.append(ui.element('p', 'command-empty', 'No retrieved sources.')); return; }
    sources.forEach((source) => target.append(ui.element('span', 'source-chip', source)));
  }

  function localErrorMessage(error) {
    const message = String(error?.message || error || '').toLowerCase();
    if (message.includes('model') || message.includes('llama')) return 'Local model is unavailable. Check model initialization and Nikola logs.';
    if (message.includes('rag') || message.includes('index')) return 'Document retrieval is unavailable. Check the local document vault.';
    if (message.includes('vision') || message.includes('screen')) return 'Local vision is unavailable. Check the configured vision model.';
    if (message.includes('fetch') || message.includes('network') || message.includes('connect')) return 'Nikola’s local backend is unreachable. Reconnect or restart the backend.';
    return 'Nikola could not complete this local request.';
  }

  function setMode(mode) {
    state.mode = mode;
    $('#nikola-shell').dataset.mode = mode;
    $('#assistant-ball-view').classList.toggle('hidden', mode !== 'ball');
    $('#workspace').classList.toggle('hidden', mode !== 'workspace');
    if (mode === 'workspace') setTimeout(() => input.focus(), 160);
  }

  function updateDot(id, current) {
    const dot = $(id);
    const normalized = String(current || '').toLowerCase();
    dot.className = `runtime-dot ${normalized.includes('ready') ? 'ready' : normalized.includes('error') || normalized.includes('offline') ? 'error' : normalized.includes('unavailable') ? 'muted' : 'pending'}`;
  }

  function updateSystemStatus(status) {
    const allReady = status.backend_state === 'BACKEND_READY' && status.model_state === 'MODEL_READY' && status.rag_state === 'RAG_READY';
    const headline = allReady ? 'READY' : status.model_state === 'MODEL_ERROR' ? 'MODEL ERROR' : 'INITIALIZING';
    $('#header-state').textContent = headline;
    $('#header-model').textContent = status.models_loaded?.[0] || 'Local model';
    $('#orb-status').textContent = headline;
    $('#assistant-ball').dataset.state = allReady ? 'ready' : headline === 'MODEL ERROR' ? 'error' : 'pending';
    updateDot('#header-dot', headline);
    [['backend', status.backend_state], ['model', status.model_state], ['rag', status.rag_state], ['vision', status.vision_state]].forEach(([name, value]) => {
      updateDot(`#side-${name}`, value);
      $(`#side-${name}-label`).textContent = String(value || 'Unavailable').replace(/^[A-Z]+_/, '').replaceAll('_', ' ').toLowerCase();
      updateDot(`#center-${name}-dot`, value);
      $(`#center-${name}-label`).textContent = String(value || 'Unavailable').replace(/^[A-Z]+_/, '').replaceAll('_', ' ').toLowerCase();
    });
    $('#connection-banner').classList.toggle('hidden', allReady);
    if (!allReady) $('#connection-banner').querySelector('p').textContent = status.startup_error || 'Nikola is still preparing its local services.';
    $('#center-activity').textContent = status.startup_error || (allReady ? 'Ready for a local task.' : 'Preparing local services.');
  }

  async function refreshStatus() {
    try {
      updateSystemStatus(await api.status());
    } catch {
      const offline = { backend_state: 'BACKEND_OFFLINE', model_state: 'MODEL_ERROR', rag_state: 'RAG_ERROR', vision_state: 'VISION_UNAVAILABLE', startup_error: 'Unable to connect to Nikola’s local backend.' };
      updateSystemStatus(offline);
      $('#header-state').textContent = 'OFFLINE';
      $('#orb-status').textContent = 'OFFLINE';
      $('#assistant-ball').dataset.state = 'error';
    }
  }

  function scrollMessages() { messages.scrollTop = messages.scrollHeight; }

  function executeCommand(command) {
    input.value = '';
    $('#command-palette').classList.add('hidden');
    activeCommand = -1;
    command.action();
  }

  function renderCommandPalette() {
    const palette = $('#command-palette');
    const query = input.value.trim().toLowerCase();
    if (!query.startsWith('/')) { palette.classList.add('hidden'); activeCommand = -1; return; }
    const matches = commands.filter((command) => command.name.startsWith(query.split(' ')[0]));
    palette.replaceChildren();
    matches.forEach((command, index) => {
      const option = ui.element('button', `command-option${index === activeCommand ? ' active' : ''}`);
      option.type = 'button';
      option.setAttribute('role', 'option');
      option.append(ui.element('b', '', command.name), ui.element('span', '', command.description));
      option.addEventListener('click', () => executeCommand(command));
      palette.append(option);
    });
    palette.classList.toggle('hidden', !matches.length);
    if (activeCommand >= matches.length) activeCommand = matches.length - 1;
  }

  function showEmptyState() {
    messages.replaceChildren();
    const empty = ui.element('section', 'empty-stage');
    empty.append(ui.element('span', 'empty-star', '✦'), ui.element('h2', '', 'NIKOLA'), ui.element('p', '', 'Your private local AI assistant'));
    const prompts = ui.element('div', 'suggestion-grid');
    [['Explain a concept', 'Explain a concept clearly with a practical example.'], ['Analyze a document', 'Summarize the most relevant indexed documents.'], ['Write code', 'Help me write a clean implementation for this task.']].forEach(([label, prompt]) => {
      const button = ui.element('button', '', label);
      button.type = 'button';
      button.addEventListener('click', () => { input.value = prompt; sendMessage(); });
      prompts.append(button);
    });
    empty.append(prompts);
    messages.append(empty);
  }

  function appendMessage(role, text) {
    messages.querySelector('.empty-stage')?.remove();
    const message = ui.createMessage(role, text);
    messages.append(message.article);
    scrollMessages();
    return message;
  }

  function setGenerating(active) {
    $('#generation-state').classList.toggle('hidden', !active);
    $('#stop-generation').classList.toggle('hidden', !active);
    $('#send-message').classList.toggle('hidden', active);
    $('#assistant-ball').classList.toggle('generating', active);
  }

  async function sendMessage() {
    const query = input.value.trim();
    if (!query || state.activeController) return;
    state.lastPrompt = query;
    input.value = '';
    resizeComposer();
    appendMessage('user', query);
    const answer = appendMessage('assistant', '');
    const controller = new AbortController();
    state.activeController = controller;
    setGenerating(true);
    setCenterSources([]);
    setCenterActivity('Generating a local response.');
    let pendingScroll = false;
    const scheduleScroll = () => {
      if (pendingScroll) return;
      pendingScroll = true;
      requestAnimationFrame(() => { pendingScroll = false; scrollMessages(); });
    };
    try {
      await api.streamAnswer({ query, use_rag: $('#rag-toggle').checked, conversation_id: state.conversationId }, (event) => {
        if (event.conversation_id) state.conversationId = event.conversation_id;
        if (event.event) setCenterActivity(String(event.event).replaceAll('_', ' '));
        if (event.token) { answer.body.dataset.raw += event.token; answer.body.textContent += event.token; scheduleScroll(); }
        if (event.answer) { answer.body.dataset.raw = event.answer; answer.body.textContent = event.answer; }
        if (event.event === 'complete') ui.renderMarkdown(answer.body, answer.body.dataset.raw || answer.body.textContent);
        if (event.sources?.length) { ui.renderSources(answer, event.sources); setCenterSources(event.sources); }
      }, controller.signal);
      if (!answer.body.textContent.trim()) { answer.body.dataset.raw = 'Nikola returned no response.'; answer.body.textContent = answer.body.dataset.raw; }
    } catch (error) {
      if (error.name === 'AbortError') { answer.body.dataset.raw = answer.body.textContent || 'Generation stopped.'; answer.body.textContent = answer.body.dataset.raw; }
      else { answer.body.dataset.raw = localErrorMessage(error); answer.body.textContent = answer.body.dataset.raw; setCenterActivity(answer.body.dataset.raw); }
    } finally {
      state.activeController = null;
      setGenerating(false);
      setCenterActivity('Ready for a local task.');
      input.focus();
      scrollMessages();
    }
  }

  function resizeComposer() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(Math.max(input.scrollHeight, 46), 156)}px`;
  }

  function newChat() {
    state.conversationId = null;
    state.lastPrompt = '';
    $('#conversation-title').textContent = 'New conversation';
    activatePanel('chat');
    showEmptyState();
    input.focus();
  }

  function activatePanel(panel) {
    document.querySelectorAll('.content-panel').forEach((item) => item.classList.toggle('active', item.id === `panel-${panel}`));
    document.querySelectorAll('[data-panel]').forEach((item) => item.classList.toggle('active', item.dataset.panel === panel));
    if (panel === 'documents') loadDocuments();
    if (panel === 'workflows') loadWorkflows();
    if (panel === 'settings') loadModels();
  }

  async function loadDocuments() {
    const target = $('#document-list');
    try {
      const result = await api.documents();
      $('#vault-summary').textContent = `${result.total_files || 0} document${result.total_files === 1 ? '' : 's'} · ${result.total_chunks || 0} indexed chunks`;
      ui.renderDocuments(target, result.files || [], removeDocument);
    } catch (error) {
      target.replaceChildren(ui.element('p', 'quiet-copy', error.message));
    }
  }

  async function addDocuments(paths) {
    if (!paths?.length) return;
    setCenterActivity(`Indexing ${paths.length} local document${paths.length === 1 ? '' : 's'}.`);
    showToast(`Indexing ${paths.length} document${paths.length === 1 ? '' : 's'} locally…`);
    for (const filePath of paths) {
      try { await api.indexDocument(filePath); } catch (error) { showToast(error.message); }
    }
    await loadDocuments();
    setCenterActivity('Ready for a local task.');
    showToast('Document vault updated.');
  }

  async function chooseDocuments() {
    try { await addDocuments(await desktop.chooseDocuments()); } catch { showToast('Nikola could not open the document picker.'); }
  }

  async function removeDocument(filename) {
    try { await api.removeDocument(filename); await loadDocuments(); showToast('Document removed from the vault.'); }
    catch (error) { showToast(error.message); }
  }

  async function loadWorkflows() {
    const target = $('#workflow-list');
    try { ui.renderWorkflows(target, await api.workflows()); }
    catch (error) { target.replaceChildren(ui.element('p', 'quiet-copy', error.message)); }
  }

  async function loadModels() {
    const target = $('#model-list');
    try {
      const result = await api.models();
      target.replaceChildren();
      (result.models || []).forEach((model) => {
        const line = ui.element('div', 'model-row');
        line.append(ui.element('b', '', model.name), ui.element('span', '', `${model.size_mb} MB${model.active ? ' · active' : ''}`));
        target.append(line);
      });
      if (!target.children.length) target.append(ui.element('p', 'quiet-copy', 'No local model files were reported.'));
    } catch (error) { target.replaceChildren(ui.element('p', 'quiet-copy', error.message)); }
  }

  async function analyzeScreen() {
    const output = $('#vision-result');
    output.classList.remove('hidden');
    output.textContent = 'Analyzing locally…';
    setCenterActivity('Analyzing the current screen locally.');
    try {
      const result = await api.solveScreen($('#vision-prompt').value.trim() || 'Analyze my current screen.');
      output.textContent = `${result.description}\n\n${result.solution}`;
    } catch (error) { output.textContent = error.message; }
    finally { setCenterActivity('Ready for a local task.'); }
  }

  async function toggleVoiceRecording() {
    const button = $('#voice-record');
    const label = $('#voice-state');
    if (state.isRecording) {
      state.mediaRecorder?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.audioChunks = [];
      const recorder = new MediaRecorder(stream);
      state.mediaRecorder = recorder;
      state.isRecording = true;
      button.classList.add('recording');
      label.textContent = 'Listening… select again to finish';
      recorder.ondataavailable = (event) => { if (event.data.size) state.audioChunks.push(event.data); };
      recorder.onstop = async () => {
        state.isRecording = false;
        button.classList.remove('recording');
        label.textContent = 'Transcribing locally…';
        setCenterActivity('Transcribing voice locally.');
        stream.getTracks().forEach((track) => track.stop());
        try {
          const result = await api.transcribe(new Blob(state.audioChunks, { type: recorder.mimeType || 'audio/webm' }));
          if (result.text) { input.value = result.text; resizeComposer(); activatePanel('chat'); input.focus(); label.textContent = 'Transcription added to the composer'; }
          else label.textContent = result.error || 'Nikola could not hear a transcription.';
        } catch (error) { label.textContent = error.message; }
        finally { setCenterActivity('Ready for a local task.'); }
      };
      recorder.start();
    } catch { label.textContent = 'Microphone access was not available.'; }
  }

  function bindEvents() {
    $('#assistant-ball').addEventListener('click', () => { if (!dragged) desktop.openWorkspace(); dragged = false; });
    $('#assistant-ball').addEventListener('dblclick', () => desktop.openWorkspace());
    $('#assistant-ball').addEventListener('contextmenu', (event) => { event.preventDefault(); desktop.showBallMenu(); });
    let dragOffset = null;
    let dragged = false;
    $('#assistant-ball').addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      dragged = false;
      dragOffset = { x: event.screenX - window.screenX, y: event.screenY - window.screenY };
      event.currentTarget.setPointerCapture(event.pointerId);
    });
    $('#assistant-ball').addEventListener('pointermove', (event) => {
      if (!dragOffset || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      dragged ||= Math.abs(event.movementX) + Math.abs(event.movementY) > 1;
      desktop.moveBall({ x: event.screenX - dragOffset.x, y: event.screenY - dragOffset.y });
    });
    $('#assistant-ball').addEventListener('pointerup', (event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); dragOffset = null; });
    $('#hide-workspace').addEventListener('click', () => desktop.showBall());
    $('#quit-nikola').addEventListener('click', () => desktop.quit());
    $('#brand-home').addEventListener('click', () => activatePanel('chat'));
    const commandCenter = $('#command-center');
    const setCommandCenter = (open) => { commandCenter.classList.toggle('open', open); $('#command-center-toggle').setAttribute('aria-expanded', String(open)); };
    $('#command-center-toggle').addEventListener('click', () => setCommandCenter(!commandCenter.classList.contains('open')));
    $('#command-center-close').addEventListener('click', () => setCommandCenter(false));
    $('#new-chat').addEventListener('click', newChat);
    $('#sidebar-toggle').addEventListener('click', () => { $('#sidebar').classList.toggle('collapsed'); localStorage.setItem('nikola-sidebar-collapsed', $('#sidebar').classList.contains('collapsed')); });
    document.querySelector('.workspace-nav').addEventListener('click', (event) => { const target = event.target.closest('[data-panel]'); if (target) activatePanel(target.dataset.panel); });
    $('#composer').addEventListener('submit', (event) => { event.preventDefault(); sendMessage(); });
    input.addEventListener('input', () => { resizeComposer(); renderCommandPalette(); });
    input.addEventListener('keydown', (event) => {
      const palette = $('#command-palette');
      const options = palette.querySelectorAll('.command-option');
      if (!palette.classList.contains('hidden') && options.length) {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          activeCommand = event.key === 'ArrowDown' ? (activeCommand + 1) % options.length : (activeCommand - 1 + options.length) % options.length;
          renderCommandPalette();
          return;
        }
        if ((event.key === 'Enter' || event.key === 'Tab') && activeCommand >= 0) {
          event.preventDefault();
          const prefix = input.value.trim().toLowerCase().split(' ')[0];
          executeCommand(commands.filter((command) => command.name.startsWith(prefix))[activeCommand]);
          return;
        }
      }
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
      if (event.key === 'Escape') { palette.classList.add('hidden'); activeCommand = -1; state.activeController?.abort(); }
    });
    $('#stop-generation').addEventListener('click', () => state.activeController?.abort());
    $('#attach-document').addEventListener('click', chooseDocuments);
    $('#add-documents').addEventListener('click', chooseDocuments);
    $('#messages').addEventListener('click', (event) => { if (event.target.dataset.action === 'regenerate' && state.lastPrompt && !state.activeController) { input.value = state.lastPrompt; sendMessage(); } });
    $('#clear-vault').addEventListener('click', () => $('#confirm-dialog').classList.remove('hidden'));
    $('#cancel-clear').addEventListener('click', () => $('#confirm-dialog').classList.add('hidden'));
    $('#confirm-clear').addEventListener('click', async () => { try { await api.clearDocuments(); $('#confirm-dialog').classList.add('hidden'); await loadDocuments(); showToast('The document vault has been cleared.'); } catch (error) { showToast(error.message); } });
    $('#reconnect').addEventListener('click', refreshStatus);
    $('#restart-backend').addEventListener('click', () => desktop.restartBackend());
    $('#analyze-screen').addEventListener('click', analyzeScreen);
    $('#voice-record').addEventListener('click', toggleVoiceRecording);
    $('#voice-trigger').addEventListener('click', () => { activatePanel('voice'); $('#voice-record').focus(); });
    $('#composer').addEventListener('dragover', (event) => event.preventDefault());
    $('#composer').addEventListener('drop', (event) => { event.preventDefault(); const paths = [...event.dataTransfer.files].map((file) => file.path).filter(Boolean); if (paths.length) addDocuments(paths); else showToast('For privacy, add documents using the file picker.'); });
    if (localStorage.getItem('nikola-sidebar-collapsed') === 'true') $('#sidebar').classList.add('collapsed');
    desktop.onWindowMode(setMode);
    desktop.onNewChat(newChat);
    desktop.onOpenView((view) => { setMode('workspace'); activatePanel(view); });
    desktop.onRestartBackend((result) => { showToast(result?.accepted ? 'Backend restart requested. Nikola will reconnect when it is ready.' : 'Nikola could not request a backend restart.'); refreshStatus(); });
  }

  bindEvents();
  showEmptyState();
  resizeComposer();
  refreshStatus();
  setInterval(refreshStatus, 10_000);
  setMode('ball');
})();

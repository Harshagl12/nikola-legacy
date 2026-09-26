(function attachNikolaApi(global) {
  'use strict';

  const BASE_URL = 'http://127.0.0.1:8000';

  class NikolaApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = 'NikolaApiError';
      this.status = status || 0;
    }
  }

  function friendlyError(response) {
    if (response.status === 401) return 'Nikola could not authenticate with its local backend.';
    if (response.status === 404) return 'This Nikola feature is not available in the local backend.';
    if (response.status >= 500) return 'Nikola’s local backend could not complete that request.';
    return 'Nikola could not complete that request.';
  }

  async function request(path, options = {}) {
    const controller = options.signal ? null : new AbortController();
    const timeout = global.setTimeout(() => controller?.abort(), options.timeout || 12_000);
    const isForm = options.body instanceof FormData;
    try {
      const response = await fetch(`${BASE_URL}${path}`, {
        ...options,
        signal: options.signal || controller.signal,
        headers: {
          ...(isForm ? {} : options.body ? { 'Content-Type': 'application/json' } : {}),
          ...(options.headers || {}),
        },
      });
      if (!response.ok) throw new NikolaApiError(friendlyError(response), response.status);
      return response;
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      if (error instanceof NikolaApiError) throw error;
      throw new NikolaApiError('Unable to connect to Nikola’s local backend.');
    } finally {
      global.clearTimeout(timeout);
    }
  }

  async function json(path, options) {
    return (await request(path, options)).json();
  }

  async function streamAnswer(payload, onEvent, signal) {
    const response = await request('/ask', {
      method: 'POST',
      body: JSON.stringify({ ...payload, stream: true }),
      signal,
      timeout: 90_000,
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/event-stream')) {
      onEvent({ event: 'complete', ...(await response.json()) });
      return;
    }

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
        const line = event.split('\n').find((item) => item.startsWith('data:'));
        if (!line) continue;
        try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* Ignore malformed SSE frames. */ }
      }
    }
  }

  global.NikolaApi = Object.freeze({
    request,
    json,
    streamAnswer,
    error: NikolaApiError,
    status: () => json('/status'),
    documents: () => json('/rag/files'),
    indexDocument: (filePath) => json('/index', { method: 'POST', body: JSON.stringify({ file_path: filePath }) }),
    removeDocument: (filename) => json('/rag/remove', { method: 'POST', body: JSON.stringify({ filename }) }),
    clearDocuments: () => json('/rag/clear-all', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
    models: () => json('/models/list'),
    workflows: () => json('/workflow/list'),
    solveScreen: (query) => json('/solve-screen', { method: 'POST', body: JSON.stringify({ query }) }),
    transcribe: (file) => {
      const form = new FormData();
      form.append('file', file, 'nikola-voice.webm');
      return json('/voice/transcribe', { method: 'POST', body: form, timeout: 45_000 });
    },
  });
})(window);

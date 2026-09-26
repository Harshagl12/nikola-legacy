(function attachNikolaUi(global) {
  'use strict';

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function createMessage(role, text = '') {
    const article = element('article', `chat-message ${role}`);
    const meta = element('div', 'message-meta', role === 'user' ? 'YOU' : 'NIKOLA');
    const body = element('div', 'message-body');
    body.textContent = text;
    body.dataset.raw = text;
    const actions = element('div', 'message-actions');
    const copy = element('button', '', 'Copy');
    copy.type = 'button';
    copy.addEventListener('click', () => navigator.clipboard?.writeText(body.textContent));
    actions.append(copy);
    if (role === 'assistant') {
      const regenerate = element('button', '', 'Regenerate');
      regenerate.type = 'button';
      regenerate.dataset.action = 'regenerate';
      actions.append(regenerate);
    }
    article.append(meta, body, actions);
    return { article, body, sources: null };
  }

  function renderSources(message, sources) {
    if (!sources?.length) return;
    const container = element('div', 'source-group');
    container.append(element('span', 'sources-label', 'Sources'));
    sources.forEach((source) => {
      const chip = element('span', 'source-chip', source);
      container.append(chip);
    });
    message.article.append(container);
    message.sources = container;
  }

  function appendInline(target, text) {
    const fragments = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    fragments.forEach((fragment) => {
      if (!fragment) return;
      if (fragment.startsWith('`') && fragment.endsWith('`')) target.append(element('code', '', fragment.slice(1, -1)));
      else if (fragment.startsWith('**') && fragment.endsWith('**')) target.append(element('strong', '', fragment.slice(2, -2)));
      else target.append(document.createTextNode(fragment));
    });
  }

  function renderMarkdown(body, source) {
    body.replaceChildren();
    body.dataset.raw = source;
    let codeBlock = null;
    let list = null;
    source.split('\n').forEach((line) => {
      if (line.startsWith('```')) {
        if (codeBlock) { body.append(codeBlock); codeBlock = null; }
        else { codeBlock = element('pre', 'message-code'); list = null; }
        return;
      }
      if (codeBlock) { codeBlock.textContent += `${line}\n`; return; }
      const heading = line.match(/^(#{1,4})\s+(.+)/);
      const bullet = line.match(/^\s*[-*]\s+(.+)/);
      if (heading) {
        const node = element(`h${Math.min(4, heading[1].length + 2)}`, 'message-heading');
        appendInline(node, heading[2]); body.append(node); list = null; return;
      }
      if (bullet) {
        if (!list) { list = element('ul', 'message-list'); body.append(list); }
        const item = element('li'); appendInline(item, bullet[1]); list.append(item); return;
      }
      list = null;
      const paragraph = element('p', 'message-paragraph');
      appendInline(paragraph, line || ' ');
      body.append(paragraph);
    });
    if (codeBlock) body.append(codeBlock);
  }

  function renderDocuments(container, files, onRemove) {
    container.replaceChildren();
    if (!files.length) {
      container.append(element('p', 'quiet-copy', 'No documents have been indexed yet.'));
      return;
    }
    files.forEach((file) => {
      const card = element('article', 'vault-card');
      const top = element('div', 'vault-card-top');
      const name = element('h3', '', file.filename || 'Untitled document');
      const remove = element('button', 'icon-button danger', 'Remove');
      remove.type = 'button';
      remove.addEventListener('click', () => onRemove(file.filename));
      top.append(name, remove);
      card.append(top, element('p', 'quiet-copy', `${file.chunks || 0} chunks · ${formatBytes(file.size_bytes)}`));
      container.append(card);
    });
  }

  function renderWorkflows(container, workflows) {
    container.replaceChildren();
    if (!workflows?.length) {
      container.append(element('p', 'quiet-copy', 'No saved workflows are available yet. Nikola will only show workflows confirmed by you.'));
      return;
    }
    workflows.forEach((workflow) => {
      const card = element('article', 'workflow-card');
      card.append(element('h3', '', workflow.name || workflow.description || 'Saved workflow'));
      card.append(element('p', 'quiet-copy', workflow.description || 'A locally confirmed workflow.'));
      container.append(card);
    });
  }

  function formatBytes(value) {
    if (!Number.isFinite(value) || value <= 0) return 'Size unavailable';
    return value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  global.NikolaUi = Object.freeze({ element, createMessage, renderSources, renderMarkdown, renderDocuments, renderWorkflows });
})(window);

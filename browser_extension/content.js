/**
 * Content Script - Detect forms and field info
 */

let scanTimeout;

function scanForFields() {
  const fields = [];
  
  document.querySelectorAll('input, select, textarea').forEach(element => {
    // Check if element is in a form or visible
    if (!element.offsetParent) return;
    
    // Get associated label
    let label = '';
    const labelElement = document.querySelector(`label[for="${element.id}"]`);
    if (labelElement) label = labelElement.textContent;
    if (!label) label = element.getAttribute('aria-label') || '';
    if (!label) label = element.getAttribute('placeholder') || '';
    
    fields.push({
      id: element.id,
      name: element.name,
      label: label,
      type: element.type || element.tagName.toLowerCase(),
      placeholder: element.getAttribute('placeholder') || ''
    });
  });
  
  if (fields.length > 0) {
    chrome.storage.session.set({ [`fields_${getCurrentTabId()}`]: fields });
    showBanner();
  }
}

function showBanner() {
  // Check if banner already exists
  if (document.getElementById('nikola-banner')) return;
  
  const banner = document.createElement('div');
  banner.id = 'nikola-banner';
  banner.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 40px;
    background: #7c6af7;
    color: white;
    display: flex;
    align-items: center;
    padding: 0 16px;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 13px;
    z-index: 999999;
    box-shadow: 0 2px 8px rgba(124, 106, 247, 0.3);
  `;
  
  banner.innerHTML = `
    <span style="flex: 1;">✓ Nikola can fill this form — click the extension icon</span>
    <button id="nikola-dismiss" style="
      background: rgba(255,255,255,0.2);
      color: white;
      border: none;
      padding: 4px 8px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    ">✕</button>
  `;
  
  document.body.insertBefore(banner, document.body.firstChild);
  
  document.getElementById('nikola-dismiss').addEventListener('click', () => {
    banner.remove();
  });
}

function getCurrentTabId() {
  // Content scripts can't get their own tab ID, use document ID
  return document.documentElement.id || 'default';
}

// Scan on load and for SPA changes
scanForFields();

const observer = new MutationObserver(() => {
  clearTimeout(scanTimeout);
  scanTimeout = setTimeout(scanForFields, 500);
});

observer.observe(document.body, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ['id', 'name', 'placeholder', 'aria-label']
});

// Listen for fill request from background
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'FILL_FORM') {
    const mappings = request.mappings;
    
    document.querySelectorAll('input, select, textarea').forEach(element => {
      const fieldKey = element.id || element.name;
      
      // Check all possible identifiers
      for (const [formFieldKey, value] of Object.entries(mappings)) {
        if (formFieldKey === element.id || formFieldKey === element.name) {
          element.value = value;
          element.dispatchEvent(new Event('input', { bubbles: true }));
          element.dispatchEvent(new Event('change', { bubbles: true }));
          break;
        }
      }
    });
    
    sendResponse({ success: true });
  }
});

// Capture clicked text or active input box content and transmit safely to local backend
document.addEventListener('click', async (event) => {
  const target = event.target;
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    const text = target.value || target.textContent || target.placeholder || '';
    if (text.trim()) {
      try {
        const result = await chrome.storage.local.get(["NIKOLA_API_KEY"]);
        const apiKey = result.NIKOLA_API_KEY || "";
        await fetch('http://localhost:8000/autofill/context', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': apiKey
          },
          body: JSON.stringify({ clicked_text: text, id: target.id, name: target.name }),
          timeout: 2000
        }).catch(() => {});
      } catch (err) {
        // Ignore offline or extension context errors
      }
    }
  }
}, true);

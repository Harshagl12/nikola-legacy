/**
 * Background Service Worker - Handle Nikola backend communication
 */

const BACKEND_URL = 'http://localhost:8000';

const getApiKey = async () => {
  const res = await chrome.storage.local.get(["NIKOLA_API_KEY"]);
  return res.NIKOLA_API_KEY || "";
};

async function apiFetch(endpoint, options = {}) {
  const apiKey = await getApiKey();
  options.headers = {
    'X-API-Key': apiKey,
    ...(options.headers || {})
  };
  return fetch(`${BACKEND_URL}${endpoint}`, options);
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'REQUEST_AUTOFILL') {
    handleAutofill(sendResponse);
  } else if (request.action === 'CLEAR_PROFILE') {
    clearProfile(sendResponse);
  } else if (request.action === 'ADD_FIELD') {
    addField(request.field, request.value, sendResponse);
  } else if (request.action === 'GET_PROFILE_FIELDS') {
    getProfileFields(sendResponse);
  }
  
  return true; // Keep channel open for async response
});

async function handleAutofill(sendResponse) {
  try {
    // Get active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      sendResponse({ error: 'No active tab' });
      return;
    }
    
    // Get fields from content script storage
    const sessionData = await chrome.storage.session.get(`fields_${tab.id}`);
    const formFields = sessionData[`fields_${tab.id}`] || [];
    
    if (formFields.length === 0) {
      sendResponse({ error: 'No form fields detected' });
      return;
    }
    
    // Send to backend
    try {
      const response = await apiFetch('/autofill/fill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ form_fields: formFields }),
        timeout: 5000
      });
      
      if (!response.ok) {
        sendResponse({ error: 'Backend error: ' + response.status });
        return;
      }
      
      const data = await response.json();
      
      // Send fill request to content script
      chrome.tabs.sendMessage(tab.id, {
        action: 'FILL_FORM',
        mappings: data.mappings
      });
      
      sendResponse({ success: true, filled: Object.keys(data.mappings).length });
    } catch (error) {
      sendResponse({ error: 'Backend offline. Start Nikola first.' });
    }
  } catch (error) {
    sendResponse({ error: error.message });
  }
}

async function clearProfile(sendResponse) {
  try {
    const response = await apiFetch('/autofill/clear', {
      method: 'POST',
      timeout: 5000
    });
    
    if (response.ok) {
      sendResponse({ success: true });
    } else {
      sendResponse({ error: 'Clear failed' });
    }
  } catch (error) {
    sendResponse({ error: 'Backend offline' });
  }
}

async function addField(field, value, sendResponse) {
  try {
    const response = await apiFetch('/autofill/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field, value }),
      timeout: 5000
    });
    
    if (response.ok) {
      const data = await response.json();
      sendResponse({ success: true, fields_count: data.fields_count });
    } else {
      sendResponse({ error: 'Add failed' });
    }
  } catch (error) {
    sendResponse({ error: 'Backend offline' });
  }
}

async function getProfileFields(sendResponse) {
  try {
    const response = await apiFetch('/autofill/profile', {
      timeout: 5000
    });
    
    if (response.ok) {
      const data = await response.json();
      sendResponse({ fields: data.fields });
    } else {
      sendResponse({ error: 'Get failed' });
    }
  } catch (error) {
    sendResponse({ error: 'Backend offline' });
  }
}

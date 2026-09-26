const BACKEND_URL = 'http://localhost:8000';

async function getApiKey() {
  const res = await chrome.storage.local.get(["NIKOLA_API_KEY"]);
  return res.NIKOLA_API_KEY || "";
}

async function apiFetch(endpoint, options = {}) {
  const apiKey = await getApiKey();
  options.headers = {
    'X-API-Key': apiKey,
    ...(options.headers || {})
  };
  return fetch(`${BACKEND_URL}${endpoint}`, options);
}

async function loadContent() {
  try {
    // Check backend status
    const statusResponse = await apiFetch('/status', {
      method: 'GET',
      timeout: 2000
    }).catch(() => ({ status: 0 }));
    
    const content = document.getElementById('content');
    
    if (statusResponse.status !== 200) {
      document.getElementById('status-dot').classList.add('offline');
      content.innerHTML = '<div class="offline-message">Backend offline<br>Start Nikola first</div>';
      return;
    }
    
    // Get profile fields
    const fieldsResponse = await apiFetch('/autofill/profile');
    const profileData = await fieldsResponse.json();
    const profileFields = profileData.fields || [];
    
    // Build HTML
    let html = '';
    
    // Profile fields section
    if (profileFields.length > 0) {
      html += '<div class="section">';
      html += '<div class="section-title">Profile Fields</div>';
      html += '<div class="field-list">';
      profileFields.forEach(field => {
        html += `
          <div class="field-item">
            <input type="checkbox" checked>
            <span class="field-label">${escapeHtml(field)}</span>
          </div>
        `;
      });
      html += '</div>';
      html += '<button class="btn btn-primary" id="fill-btn">Fill Form</button>';
      html += '</div>';
    }
    
    // Add field section
    html += '<div class="section">';
    html += '<div class="section-title">Manage Profile</div>';
    html += `
      <div class="input-group">
        <input type="text" id="new-field" placeholder="Field name">
        <input type="text" id="new-value" placeholder="Value">
      </div>
      <button class="btn btn-primary" id="add-btn">Remember</button>
    `;
    html += '</div>';
    
    // Clear section
    html += '<div class="section">';
    html += '<button class="btn btn-danger" id="clear-btn">Clear All Data</button>';
    html += '</div>';
    
    content.innerHTML = html;
    
    // Event listeners
    document.getElementById('fill-btn')?.addEventListener('click', fillForm);
    document.getElementById('add-btn')?.addEventListener('click', addField);
    document.getElementById('clear-btn')?.addEventListener('click', clearProfile);
  } catch (error) {
    console.error('Load error:', error);
    document.getElementById('content').innerHTML = 
      '<div class="offline-message">Error loading</div>';
  }
}

function fillForm() {
  chrome.runtime.sendMessage({ action: 'REQUEST_AUTOFILL' }, (response) => {
    if (response.error) {
      alert('Error: ' + response.error);
    } else {
      alert(`Filled ${response.filled} fields`);
    }
  });
}

function addField() {
  const field = document.getElementById('new-field').value;
  const value = document.getElementById('new-value').value;
  
  if (!field || !value) {
    alert('Please enter both field and value');
    return;
  }
  
  chrome.runtime.sendMessage({
    action: 'ADD_FIELD',
    field: field,
    value: value
  }, (response) => {
    if (response.success) {
      document.getElementById('new-field').value = '';
      document.getElementById('new-value').value = '';
      alert('Field saved');
      loadContent();
    } else {
      alert('Error: ' + response.error);
    }
  });
}

function clearProfile() {
  if (!confirm('Delete all profile data?')) return;
  
  chrome.runtime.sendMessage({ action: 'CLEAR_PROFILE' }, (response) => {
    if (response.success) {
      alert('Profile cleared');
      loadContent();
    } else {
      alert('Error: ' + response.error);
    }
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Load on open
document.addEventListener('DOMContentLoaded', loadContent);
loadContent();

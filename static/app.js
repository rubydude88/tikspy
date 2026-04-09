// ── STATE ─────────────────────────────────────────────
let selectedVideoUrl = null;

// ── SETTINGS (LOCAL STORAGE) ─────────────────────────

function saveApiKey() {
  const key = document.getElementById('api-key-input').value.trim();
  const feedback = document.getElementById('settings-feedback');

  if (!key) {
    feedback.className = 'settings-feedback err';
    feedback.textContent = 'Please enter a key.';
    return;
  }

  localStorage.setItem('apify_api_key', key);

  feedback.className = 'settings-feedback ok';
  feedback.textContent = 'Key saved in this browser.';
  document.getElementById('api-key-input').value = '';

  loadSettingsStatus();
}

function loadSettingsStatus() {
  const savedKey = localStorage.getItem('apify_api_key');
  const el = document.getElementById('settings-status');

  if (savedKey) {
    el.className = 'settings-status ok';
    el.textContent = 'API key saved in this browser';
  } else {
    el.className = 'settings-status warn';
    el.textContent = 'No API key configured';
  }
}

function getApiKey() {
  return localStorage.getItem('apify_api_key') || '';
}

// Optional: clear key
function clearSavedApiKey() {
  localStorage.removeItem('apify_api_key');
  loadSettingsStatus();
}

// ── INIT ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadSettingsStatus();
});

// ── HELPERS ──────────────────────────────────────────

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError() {
  document.getElementById('error-banner').classList.add('hidden');
}

// ── FETCH VIDEOS ─────────────────────────────────────

async function fetchVideos() {
  hideError();

  const api_key = getApiKey();
  if (!api_key) {
    showError('Please save your API key first.');
    return;
  }

  const username = document.getElementById('username-input').value.trim();
  const limit = Number(document.getElementById('limit-input').value || 30);
  const date_from = document.getElementById('date-from-input').value || null;
  const date_to = document.getElementById('date-to-input').value || null;

  if (!username) {
    showError('Username is required.');
    return;
  }

  try {
    const res = await fetch('/scrape/videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, api_key, limit, date_from, date_to }),
    });

    const data = await res.json();

    if (data.error) {
      showError(data.error);
      return;
    }

    renderVideos(data.videos || []);
  } catch (err) {
    showError('Failed to fetch videos.');
  }
}

// ── FETCH COMMENTS ───────────────────────────────────

async function fetchComments() {
  hideError();

  const api_key = getApiKey();
  if (!api_key) {
    showError('Please save your API key first.');
    return;
  }

  const count = Number(document.getElementById('comment-count-input').value || 50);

  if (!selectedVideoUrl) {
    showError('Select a video first.');
    return;
  }

  try {
    const res = await fetch('/scrape/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        video_url: selectedVideoUrl,
        api_key,
        count
      }),
    });

    const data = await res.json();

    if (data.error) {
      showError(data.error);
      return;
    }

    renderComments(data.comments || []);
  } catch (err) {
    showError('Failed to fetch comments.');
  }
}

// ── RENDER VIDEOS ────────────────────────────────────

function renderVideos(videos) {
  const tbody = document.getElementById('videos-tbody');
  tbody.innerHTML = '';

  videos.forEach(v => {
    const tr = document.createElement('tr');

    tr.onclick = () => {
      selectedVideoUrl = v.url;
      document.querySelectorAll('#videos-tbody tr').forEach(r => r.classList.remove('selected'));
      tr.classList.add('selected');
    };

    tr.innerHTML = `
      <td><img src="${v.thumbnail || ''}" class="thumbnail" /></td>
      <td class="caption-cell">${v.caption || ''}</td>
      <td class="num-cell">${v.likes || 0}</td>
      <td class="num-cell">${v.comments || 0}</td>
      <td class="num-cell">${v.shares || 0}</td>
      <td class="num-cell">${v.views || 0}</td>
      <td class="date-cell">${v.created_at || ''}</td>
    `;

    tbody.appendChild(tr);
  });
}

// ── RENDER COMMENTS ──────────────────────────────────

function renderComments(comments) {
  const tbody = document.getElementById('comments-tbody');
  tbody.innerHTML = '';

  comments.forEach(c => {
    const tr = document.createElement('tr');

    tr.innerHTML = `
      <td class="username-cell">${c.username || ''}</td>
      <td class="comment-cell">${c.text || ''}</td>
      <td class="num-cell">${c.likes || 0}</td>
    `;

    tbody.appendChild(tr);
  });
}

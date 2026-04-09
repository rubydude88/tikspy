'use strict';

let videosData = [];
let commentsData = [];
let currentTab = 'videos';
let settingsOpen = false;

// { [comment_id]: 'loading' | 'open' | 'closed' }
const replyState = {};
let currentVideoUrl = '';

// ── Settings ─────────────────────────────────────────────────────
async function loadSettingsStatus() {
  const savedKey = localStorage.getItem('apify_api_key');
  const el = document.getElementById('settings-status');
  if (savedKey) {
    el.className = 'settings-status ok';
    el.textContent = 'API key: Saved in this browser';
  } else {
    el.className = 'settings-status warn';
    el.textContent = 'No API key configured — scraping will not work.';
  }
}

function toggleSettings() {
  settingsOpen = !settingsOpen;
  const panel = document.getElementById('settings-panel');
  const overlay = document.getElementById('settings-overlay');
  const btn = document.getElementById('btn-settings');
  panel.classList.toggle('hidden', !settingsOpen);
  overlay.classList.toggle('hidden', !settingsOpen);
  btn.classList.toggle('active', settingsOpen);
  if (settingsOpen) {
    loadSettingsStatus();
    document.getElementById('settings-feedback').textContent = '';
    document.getElementById('settings-feedback').className = 'settings-feedback';
  }
}

function toggleKeyVisibility() {
  const input = document.getElementById('api-key-input');
  input.type = input.type === 'password' ? 'text' : 'password';
}

async function saveApiKey() {
  const key = document.getElementById('api-key-input').value.trim();
  const feedback = document.getElementById('settings-feedback');
  const btn = document.getElementById('btn-save-key');
  if (!key) {
    feedback.className = 'settings-feedback err';
    feedback.textContent = 'Please enter a key.';
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Saving…';
  feedback.textContent = '';
  try {
    localStorage.setItem('apify_api_key', key);
    feedback.className = 'settings-feedback ok';
    feedback.textContent = 'Key saved in this browser.';
    document.getElementById('api-key-input').value = '';
    loadSettingsStatus();
  } catch (e) {
    feedback.className = 'settings-feedback err';
    feedback.textContent = 'Failed to save key.';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Key';
  }
}

// ── Tab switching ────────────────────────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.getElementById('panel-videos').classList.toggle('hidden', tab !== 'videos');
  document.getElementById('panel-comments').classList.toggle('hidden', tab !== 'comments');
  document.getElementById('tab-videos').classList.toggle('active', tab === 'videos');
  document.getElementById('tab-comments').classList.toggle('active', tab === 'comments');
  document.getElementById('tab-videos').setAttribute('aria-selected', tab === 'videos');
  document.getElementById('tab-comments').setAttribute('aria-selected', tab === 'comments');
}

// ── Helpers ──────────────────────────────────────────────────────
function getTimestamp() {
  const now = new Date();
  const pad = (n) => n.toString().padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_` +
         `${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
}

function formatNum(n) {
  n = Number(n) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const mo = d.toLocaleString('en', { month: 'short' });
    const day = String(d.getDate()).padStart(2, '0');
    const yr = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return `${mo} ${day} ${yr} · ${hh}:${mm}`;
  } catch { return iso; }
}

function formatDuration(secs) {
  secs = Number(secs) || 0;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function relativeTime(iso) {
  if (!iso) return '—';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return 'just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} hour${h !== 1 ? 's' : ''} ago`;
    const d = Math.floor(h / 24);
    if (d < 30) return `${d} day${d !== 1 ? 's' : ''} ago`;
    const mo = Math.floor(d / 30);
    if (mo < 12) return `${mo} month${mo !== 1 ? 's' : ''} ago`;
    const yr = Math.floor(mo / 12);
    return `${yr} year${yr !== 1 ? 's' : ''} ago`;
  } catch { return '—'; }
}

function truncate(str, len) {
  if (!str) return '';
  return str.length > len ? str.slice(0, len) + '…' : str;
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), 6000);
}

function showLoading(tbodyId, colCount) {
  const tbody = document.getElementById(tbodyId);
  tbody.innerHTML = '';
  for (let i = 0; i < 8; i++) {
    const tr = document.createElement('tr');
    for (let c = 0; c < colCount; c++) {
      const td = document.createElement('td');
      if (c === 0) td.innerHTML = '<span class="skeleton skeleton-thumb"></span>';
      else if (c === 1) td.innerHTML = '<span class="skeleton skeleton-text-long"></span>';
      else td.innerHTML = '<span class="skeleton skeleton-text-short"></span>';
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function setButtonLoading(btn, loading) {
  btn.disabled = loading;
  btn._origText = btn._origText || btn.textContent;
  btn.textContent = loading ? 'Loading…' : btn._origText;
}

// ── Fetch videos ─────────────────────────────────────────────────
async function fetchVideos() {
  const username = document.getElementById('username').value.trim();
  if (!username) { showError('Please enter a TikTok username.'); return; }

  const api_key = localStorage.getItem('apify_api_key') || '';
  if (!api_key) { showError('Please save your API key first.'); renderVideosEmpty(); return; }

  const limit = parseInt(document.getElementById('limit').value) || 30;
  const date_from = document.getElementById('date_from').value || null;
  const date_to = document.getElementById('date_to').value || null;

  const btn = document.getElementById('btn-fetch-videos');
  setButtonLoading(btn, true);
  showLoading('videos-tbody', 9);
  document.getElementById('videos-export-row').style.display = 'none';
  document.getElementById('error-banner').classList.add('hidden');

  try {
    const res = await fetch('/scrape/videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, api_key, limit, date_from, date_to }),
    });
    const data = await res.json();
    if (data.error) { showError(data.error); renderVideosEmpty(); return; }
    videosData = data.videos || [];
    renderVideosTable();
    populateVideoDropdown();
    document.getElementById('videos-count').textContent =
      `${videosData.length} video${videosData.length !== 1 ? 's' : ''} found`;
    document.getElementById('videos-export-row').style.display =
      videosData.length > 0 ? 'flex' : 'none';
  } catch (e) {
    showError('Network error: ' + e.message);
    renderVideosEmpty();
  } finally {
    setButtonLoading(btn, false);
  }
}

function renderVideosEmpty() {
  document.getElementById('videos-tbody').innerHTML = `
    <tr class="empty-state-row"><td colspan="9">
      <div class="empty-state"><div class="empty-icon">&#9675;</div><div>No videos found.</div></div>
    </td></tr>`;
}

function renderVideosTable() {
  const tbody = document.getElementById('videos-tbody');
  if (!videosData.length) { renderVideosEmpty(); return; }
  tbody.innerHTML = '';
  videosData.forEach((v) => {
    const tr = document.createElement('tr');
    tr.title = v.caption || '';
    tr.addEventListener('click', () => tr.classList.toggle('selected'));

    // col1: thumbnail
    const tdThumb = document.createElement('td');
    if (v.thumbnail) {
      const img = document.createElement('img');
      img.src = v.thumbnail; img.alt = ''; img.className = 'thumbnail';
      img.onerror = () => img.replaceWith(makePlaceholderThumb());
      tdThumb.appendChild(img);
    } else { tdThumb.appendChild(makePlaceholderThumb()); }
    tr.appendChild(tdThumb);

    // col2: caption
    const tdCap = document.createElement('td');
    const capDiv = document.createElement('div');
    capDiv.className = 'caption-cell';
    capDiv.textContent = v.caption || '—';
    capDiv.title = v.caption || '';
    tdCap.appendChild(capDiv);
    tr.appendChild(tdCap);

    // col3: published
    const tdPub = document.createElement('td');
    tdPub.className = 'date-cell hide-mobile';
    tdPub.textContent = formatDate(v.published);
    tr.appendChild(tdPub);

    // col4: duration
    const tdDur = document.createElement('td');
    tdDur.className = 'num-cell hide-mobile';
    tdDur.textContent = formatDuration(v.duration);
    tr.appendChild(tdDur);

    // col5-8: stats
    tr.appendChild(numCell(v.views));
    tr.appendChild(numCell(v.likes));
    tr.appendChild(numCell(v.comments));
    const tdShares = numCell(v.shares);
    tdShares.classList.add('hide-mobile');
    tr.appendChild(tdShares);

    // col9: link
    const tdLink = document.createElement('td');
    tdLink.className = 'link-cell';
    if (v.url) {
      const a = document.createElement('a');
      a.href = v.url; a.target = '_blank'; a.rel = 'noopener';
      a.title = 'Open on TikTok'; a.textContent = '↗';
      tdLink.appendChild(a);
    }
    tr.appendChild(tdLink);

    tbody.appendChild(tr);
  });
}

function numCell(val) {
  const td = document.createElement('td');
  td.className = 'num-cell';
  td.textContent = formatNum(val);
  return td;
}

function makePlaceholderThumb() {
  const div = document.createElement('div');
  div.className = 'thumb-placeholder';
  div.textContent = '▶';
  return div;
}

// ── Comments dropdown ────────────────────────────────────────────
function populateVideoDropdown() {
  const sel = document.getElementById('video-url-select');
  sel.innerHTML = '';
  if (!videosData.length) {
    sel.innerHTML = '<option value="">— no videos loaded —</option>';
    return;
  }
  videosData.forEach((v, i) => {
    const opt = document.createElement('option');
    opt.value = v.url || '';
    opt.textContent = truncate(v.caption || v.url || `Video ${i + 1}`, 60);
    sel.appendChild(opt);
  });
}

// ── Fetch comments ───────────────────────────────────────────────
async function fetchComments() {
  const video_url = document.getElementById('video-url-select').value;
  if (!video_url) { showError('Please select a video (fetch videos first).'); return; }

  const api_key = localStorage.getItem('apify_api_key') || '';
  if (!api_key) { showError('Please save your API key first.'); renderCommentsEmpty(); return; }

  const count = parseInt(document.getElementById('comment-count').value) || 50;

  // Reset reply state on fresh fetch
  Object.keys(replyState).forEach(k => delete replyState[k]);
  currentVideoUrl = video_url;

  const btn = document.getElementById('btn-fetch-comments');
  setButtonLoading(btn, true);
  showLoading('comments-tbody', 6);
  document.getElementById('comments-export-row').style.display = 'none';
  document.getElementById('error-banner').classList.add('hidden');

  try {
    const res = await fetch('/scrape/comments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_url, api_key, count }),
    });
    const data = await res.json();
    if (data.error) { showError(data.error); renderCommentsEmpty(); return; }
    commentsData = data.comments || [];
    renderCommentsTable();
    document.getElementById('comments-count').textContent =
      `${commentsData.length} comment${commentsData.length !== 1 ? 's' : ''} found`;
    document.getElementById('comments-export-row').style.display =
      commentsData.length > 0 ? 'flex' : 'none';
  } catch (e) {
    showError('Network error: ' + e.message);
    renderCommentsEmpty();
  } finally {
    setButtonLoading(btn, false);
  }
}

function renderCommentsEmpty() {
  document.getElementById('comments-tbody').innerHTML = `
    <tr class="empty-state-row"><td colspan="6">
      <div class="empty-state"><div class="empty-icon">&#9675;</div><div>No comments found.</div></div>
    </td></tr>`;
}

function renderCommentsTable() {
  const tbody = document.getElementById('comments-tbody');
  if (!commentsData.length) { renderCommentsEmpty(); return; }
  tbody.innerHTML = '';
  commentsData.forEach((c) => tbody.appendChild(makeCommentRow(c)));
}

// 6 columns: [avatar] [username] [comment] [likes] [replies] [posted]
function makeCommentRow(c) {
  const tr = document.createElement('tr');
  tr.dataset.commentId = c.id;
  tr.className = 'comment-row';

  // col1: avatar
  const tdAv = document.createElement('td');
  if (c.avatar) {
    const img = document.createElement('img');
    img.src = c.avatar;
    img.alt = c.username ? c.username[0] : '?';
    img.className = 'avatar';
    img.onerror = () => img.replaceWith(makeAvatarPlaceholder(c.username));
    tdAv.appendChild(img);
  } else {
    tdAv.appendChild(makeAvatarPlaceholder(c.username));
  }
  tr.appendChild(tdAv);

  // col2: username
  const tdUser = document.createElement('td');
  tdUser.className = 'username-cell';
  tdUser.textContent = c.username || '—';
  tr.appendChild(tdUser);

  // col3: comment text
  const tdComment = document.createElement('td');
  const commentDiv = document.createElement('div');
  commentDiv.className = 'comment-cell';
  commentDiv.textContent = truncate(c.text, 120);
  commentDiv.title = c.text || '';
  tdComment.appendChild(commentDiv);
  tr.appendChild(tdComment);

  // col4: likes
  tr.appendChild(numCell(c.likes));

  // col5: replies — button if count > 0, dash otherwise
  const tdRep = document.createElement('td');
  tdRep.className = 'num-cell hide-mobile';
  if (c.replies > 0 && c.id) {
    const btn = document.createElement('button');
    btn.className = 'btn-replies';
    btn.id = `btn-replies-${c.id}`;
    btn.textContent = `▶ ${c.replies} repl${c.replies !== 1 ? 'ies' : 'y'}`;
    btn.title = 'Click to load replies';
    btn.onclick = () => toggleReplies(c.id, c.replies);
    tdRep.appendChild(btn);
  } else {
    tdRep.textContent = '—';
  }
  tr.appendChild(tdRep);

  // col6: posted
  const tdPost = document.createElement('td');
  tdPost.className = 'date-cell hide-mobile';
  tdPost.textContent = relativeTime(c.posted);
  tdPost.title = c.posted || '';
  tr.appendChild(tdPost);

  return tr;
}

// ── Replies ───────────────────────────────────────────────────────
async function toggleReplies(commentId, replyCount) {
  if (replyState[commentId] === 'open') { collapseReplies(commentId); return; }
  if (replyState[commentId] === 'loading') return;

  const btn = document.getElementById(`btn-replies-${commentId}`);
  const api_key = localStorage.getItem('apify_api_key') || '';

  replyState[commentId] = 'loading';
  if (btn) { btn.textContent = '⏳ Loading…'; btn.disabled = true; }

  try {
    const res = await fetch('/scrape/replies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        video_url: currentVideoUrl,
        comment_id: commentId,
        api_key,
        count: replyCount,
      }),
    });
    const data = await res.json();

    if (data.error) {
      showError(data.error);
      replyState[commentId] = 'closed';
      if (btn) { btn.textContent = `▶ ${replyCount} repl${replyCount !== 1 ? 'ies' : 'y'}`; btn.disabled = false; }
      return;
    }

    insertReplyRows(commentId, data.replies || []);
    replyState[commentId] = 'open';
    if (btn) { btn.textContent = `▼ ${replyCount} repl${replyCount !== 1 ? 'ies' : 'y'}`; btn.disabled = false; }
  } catch (e) {
    showError('Network error fetching replies: ' + e.message);
    replyState[commentId] = 'closed';
    if (btn) { btn.textContent = `▶ ${replyCount} repl${replyCount !== 1 ? 'ies' : 'y'}`; btn.disabled = false; }
  }
}

function insertReplyRows(commentId, replies) {
  const tbody = document.getElementById('comments-tbody');
  const parentRow = tbody.querySelector(`tr[data-comment-id="${commentId}"]`);
  if (!parentRow) return;

  removeReplyRows(commentId);

  if (!replies.length) {
    const emptyTr = document.createElement('tr');
    emptyTr.className = 'reply-row';
    emptyTr.dataset.parentId = commentId;
    // 6 cols: col1 = indent, col2-6 = message
    emptyTr.innerHTML = `<td class="reply-indent"><span class="reply-line">└</span></td><td colspan="5" class="reply-empty">No replies could be loaded.</td>`;
    parentRow.insertAdjacentElement('afterend', emptyTr);
    return;
  }

  // Insert in reverse so afterend keeps correct order
  [...replies].reverse().forEach((r) => {
    parentRow.insertAdjacentElement('afterend', makeReplyRow(r, commentId));
  });
}

// Reply row uses same 6 columns:
// col1: indent | col2: avatar | col3: username+text (no colspan needed) | col4: likes | col5: — | col6: posted
function makeReplyRow(r, parentId) {
  const tr = document.createElement('tr');
  tr.className = 'reply-row';
  tr.dataset.parentId = parentId;

  // col1: indent
  const tdIndent = document.createElement('td');
  tdIndent.className = 'reply-indent';
  tdIndent.innerHTML = '<span class="reply-line">└</span>';
  tr.appendChild(tdIndent);

  // col2: avatar (small)
  const tdAv = document.createElement('td');
  if (r.avatar) {
    const img = document.createElement('img');
    img.src = r.avatar;
    img.alt = r.username ? r.username[0] : '?';
    img.className = 'avatar avatar-sm';
    img.onerror = () => img.replaceWith(makeAvatarPlaceholder(r.username, true));
    tdAv.appendChild(img);
  } else {
    tdAv.appendChild(makeAvatarPlaceholder(r.username, true));
  }
  tr.appendChild(tdAv);

  // col3: username + text stacked
  const tdMain = document.createElement('td');
  const nameSpan = document.createElement('span');
  nameSpan.className = 'reply-username';
  nameSpan.textContent = r.username || '—';
  const textDiv = document.createElement('div');
  textDiv.className = 'comment-cell reply-text';
  textDiv.textContent = truncate(r.text, 120);
  textDiv.title = r.text || '';
  tdMain.appendChild(nameSpan);
  tdMain.appendChild(textDiv);
  tr.appendChild(tdMain);

  // col4: likes
  tr.appendChild(numCell(r.likes));

  // col5: empty (no nested replies)
  const tdEmpty = document.createElement('td');
  tdEmpty.className = 'hide-mobile';
  tr.appendChild(tdEmpty);

  // col6: posted
  const tdPost = document.createElement('td');
  tdPost.className = 'date-cell hide-mobile';
  tdPost.textContent = relativeTime(r.posted);
  tdPost.title = r.posted || '';
  tr.appendChild(tdPost);

  return tr;
}

function collapseReplies(commentId) {
  removeReplyRows(commentId);
  replyState[commentId] = 'closed';
  const btn = document.getElementById(`btn-replies-${commentId}`);
  if (btn) {
    const comment = commentsData.find(c => c.id === commentId);
    const count = comment ? comment.replies : 0;
    btn.textContent = `▶ ${count} repl${count !== 1 ? 'ies' : 'y'}`;
  }
}

function removeReplyRows(commentId) {
  document.getElementById('comments-tbody')
    .querySelectorAll(`tr[data-parent-id="${commentId}"]`)
    .forEach(r => r.remove());
}

function makeAvatarPlaceholder(username, small = false) {
  const div = document.createElement('div');
  div.className = small ? 'avatar-placeholder avatar-placeholder-sm' : 'avatar-placeholder';
  div.textContent = username ? username[0].toUpperCase() : '?';
  return div;
}

// ── Exports ──────────────────────────────────────────────────────
function toCSV(rows) {
  if (!rows.length) return '';
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(',')];
  rows.forEach(row => {
    lines.push(headers.map(h => {
      const val = row[h] == null ? '' : String(row[h]);
      return /[",\n]/.test(val) ? '"' + val.replace(/"/g, '""') + '"' : val;
    }).join(','));
  });
  return lines.join('\n');
}

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function flattenVideos(videos) {
  return videos.map(v => ({
    id: v.id, url: v.url, published: v.published,
    duration_sec: v.duration, views: v.views, likes: v.likes,
    comments: v.comments, shares: v.shares, caption: v.caption,
  }));
}

function flattenComments(comments) {
  return comments.map(c => ({
    id: c.id, username: c.username, text: c.text,
    likes: c.likes, replies: c.replies, posted: c.posted,
  }));
}

function exportVideosCSV() {
  if (!videosData.length) return;
  const filename = `tikspy_videos_${getTimestamp()}.csv`;
  downloadBlob(toCSV(flattenVideos(videosData)), filename, 'text/csv');
}

function exportVideosXLSX() {
  if (!videosData.length) return;
  const ws = XLSX.utils.json_to_sheet(flattenVideos(videosData));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Videos');
  XLSX.writeFile(wb, `tikspy_videos_${getTimestamp()}.xlsx`);
}

function exportCommentsCSV() {
  if (!commentsData.length) return;
  const filename = `tikspy_comments_${getTimestamp()}.csv`;
  downloadBlob(toCSV(flattenComments(commentsData)), filename, 'text/csv');
}

function exportCommentsXLSX() {
  if (!commentsData.length) return;
  const ws = XLSX.utils.json_to_sheet(flattenComments(commentsData));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Comments');
  XLSX.writeFile(wb, `tikspy_comments_${getTimestamp()}.xlsx`);
}

// ── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSettingsStatus();
});

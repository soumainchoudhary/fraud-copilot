/**
 * Fraud Investigation Copilot - Frontend Application Logic
 */

// Application state
const state = {
  currentTab: 'scoring',
  casesPage: 1,
  casesPageSize: 15,
  casesStatusFilter: 'all',
  casesSearchQuery: '',
  casesTotal: 0,
  activeCaseModalId: null,
  pcaFeatures: {},
  lastScorePercent: 0,
};

// ==========================================================================
// Authentication & Secure Fetch
// ==========================================================================

function getApiKey() {
  return localStorage.getItem('fraud_copilot_api_key') || '';
}

function setApiKey(key) {
  if (key && key.trim()) {
    localStorage.setItem('fraud_copilot_api_key', key.trim());
  } else {
    localStorage.removeItem('fraud_copilot_api_key');
  }
}

function updateApiKeyBadge() {
  const label = document.getElementById('api-key-label');
  if (!label) return;
  const key = getApiKey();
  if (key) {
    label.textContent = `API Key: ${key.slice(0, 4)}...`;
  } else {
    label.textContent = 'API Key: Dev';
  }
}

function promptApiKey() {
  const current = getApiKey();
  const key = prompt('Enter Fraud Copilot API Key (leave empty for dev mode):', current);
  if (key !== null) {
    setApiKey(key);
    updateApiKeyBadge();
    showToast(key ? 'API Key configured' : 'Using default Dev API credentials', 'info', 'Authentication');
    loadStats();
    loadCases();
  }
}

async function secureFetch(url, options = {}) {
  const headers = options.headers ? { ...options.headers } : {};
  const apiKey = getApiKey();
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    console.warn('Unauthorized request - 401. API Key required or invalid.');
    showToast('Unauthorized - Invalid or missing API Key.', 'danger', 'Auth Error');
  }
  return response;
}

// ==========================================================================
// Initialization
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  updateApiKeyBadge();
  startSystemClock();
  initSpotlightTracking();
  buildPcaGrid();
  loadStats();
  loadCases();
  checkHealth();
  initWebSocketLiveStream();
  refreshDriftAndShadow();
});

// ==========================================================================
// Tab Switching
// ==========================================================================

function switchTab(tabId) {
  state.currentTab = tabId;
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));

  const tabBtn = document.getElementById(`tab-${tabId}-btn`);
  const pane = document.getElementById(`pane-${tabId}`);
  if (tabBtn) tabBtn.classList.add('active');
  if (pane) pane.classList.add('active');
}

// ==========================================================================
// Health & Stats
// ==========================================================================

async function checkHealth() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    if (data.status === 'ok') {
      const mlPill = document.getElementById('ml-status-pill');
      if (mlPill) mlPill.style.display = 'flex';
    }
  } catch (err) {
    console.warn('Health check failed:', err);
  }
}

async function loadStats() {
  try {
    const res = await secureFetch('/cases/stats');
    if (!res.ok) return;
    const stats = await res.json();

    const totalEl = document.getElementById('stat-total-cases');
    const escalatedEl = document.getElementById('stat-escalated-cases');
    const reviewEl = document.getElementById('stat-under-review');
    const resolvedEl = document.getElementById('stat-resolved-cases');
    const casesCountLabel = document.getElementById('cases-count-label');

    if (totalEl) totalEl.textContent = stats.total_cases.toLocaleString();
    if (escalatedEl) escalatedEl.textContent = stats.escalated_cases.toLocaleString();
    if (reviewEl) reviewEl.textContent = stats.under_review_cases.toLocaleString();
    if (resolvedEl) resolvedEl.textContent = stats.resolved_cases.toLocaleString();
    if (casesCountLabel) casesCountLabel.textContent = `${stats.total_cases} Cases Indexed`;
  } catch (err) {
    console.error('Failed to load case stats:', err);
  }
}

// ==========================================================================
// Scoring Simulator & Explainable AI
// ==========================================================================

function buildPcaGrid() {
  const container = document.getElementById('pca-grid');
  if (!container) return;
  container.innerHTML = '';

  for (let i = 1; i <= 28; i++) {
    const defaultVal = i === 14 ? -0.14 : i === 12 ? 1.07 : i === 10 ? -0.17 : i === 4 ? 1.38 : 0.0;
    state.pcaFeatures[`v${i}`] = defaultVal;

    const cell = document.createElement('div');
    cell.className = 'pca-cell';
    cell.innerHTML = `
      <label for="pca-v${i}">V${i}</label>
      <input type="number" id="pca-v${i}" step="0.01" value="${defaultVal}" onchange="updatePcaInput(${i}, this.value)" />
    `;
    container.appendChild(cell);
  }
}

function updateSlider(feature) {
  const slider = document.getElementById(`slider-${feature}`);
  const label = document.getElementById(`val-${feature}`);
  if (!slider || !label) return;
  const val = parseFloat(slider.value);
  label.textContent = val.toFixed(2);
  state.pcaFeatures[feature] = val;

  const numInput = document.getElementById(`pca-${feature}`);
  if (numInput) numInput.value = val;
}

function updatePcaInput(index, val) {
  const num = parseFloat(val) || 0.0;
  state.pcaFeatures[`v${index}`] = num;

  const slider = document.getElementById(`slider-v${index}`);
  const label = document.getElementById(`val-v${index}`);
  if (slider && label) {
    slider.value = num;
    label.textContent = num.toFixed(2);
  }
}

function randomizeFeatures() {
  document.getElementById('txn-id').value = `TXN-SIM-${Math.floor(1000 + Math.random() * 9000)}`;
  document.getElementById('txn-amount').value = (Math.random() * 300 + 5).toFixed(2);
  document.getElementById('txn-time').value = Math.floor(Math.random() * 86400);

  for (let i = 1; i <= 28; i++) {
    const randVal = (Math.random() * 4 - 2).toFixed(2);
    updatePcaInput(i, randVal);
  }
}

function applyPreset(type) {
  if (type === 'legit') {
    document.getElementById('txn-id').value = `TXN-NORM-${Math.floor(1000 + Math.random() * 9000)}`;
    document.getElementById('txn-amount').value = '24.50';
    document.getElementById('txn-time').value = '34200'; // 9:30 AM
    for (let i = 1; i <= 28; i++) updatePcaInput(i, 0.0);
    updatePcaInput(14, 0.15);
    updatePcaInput(12, 0.22);
    updatePcaInput(10, 0.05);
    updatePcaInput(4, -0.10);
  } else if (type === 'fraud_heavy') {
    document.getElementById('txn-id').value = `TXN-FRAUD-${Math.floor(1000 + Math.random() * 9000)}`;
    document.getElementById('txn-amount').value = '550.00';
    document.getElementById('txn-time').value = '7200'; // 2:00 AM
    for (let i = 1; i <= 28; i++) updatePcaInput(i, 0.0);
    updatePcaInput(14, -7.50); // Severe V14 anomaly
    updatePcaInput(12, -6.10); // Severe V12 anomaly
    updatePcaInput(10, -5.20);
    updatePcaInput(4, 4.80);
    updatePcaInput(17, -8.10);
  } else if (type === 'structuring') {
    document.getElementById('txn-id').value = `TXN-STRUC-${Math.floor(1000 + Math.random() * 9000)}`;
    document.getElementById('txn-amount').value = '149.99';
    document.getElementById('txn-time').value = '1800'; // 12:30 AM
    for (let i = 1; i <= 28; i++) updatePcaInput(i, 0.0);
    updatePcaInput(14, -2.50);
    updatePcaInput(10, -1.80);
    updatePcaInput(4, 2.10);
  }
}

async function handleScoreSubmit(event) {
  event.preventDefault();
  const submitBtn = document.getElementById('score-submit-btn');
  submitBtn.disabled = true;
  submitBtn.innerHTML = `Scoring...`;

  const payload = {
    transaction_id: document.getElementById('txn-id').value,
    amount: parseFloat(document.getElementById('txn-amount').value),
    time: parseFloat(document.getElementById('txn-time').value),
  };

  for (let i = 1; i <= 28; i++) {
    payload[`v${i}`] = state.pcaFeatures[`v${i}`] || 0.0;
  }

  const startTime = performance.now();

  try {
    const res = await secureFetch('/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Scoring request failed');
    }

    const data = await res.json();
    const duration = (performance.now() - startTime).toFixed(1);

    renderScoreResult(data, duration);
  } catch (err) {
    alert(`Scoring error: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
      Score Transaction
    `;
  }
}

function renderScoreResult(data, latencyMs) {
  const percent = (data.risk_score * 100).toFixed(1);
  const targetPercent = parseFloat(percent);
  const gaugeVal = document.getElementById('gauge-score');
  const gaugeCircle = document.getElementById('gauge-circle');
  const decisionPill = document.getElementById('decision-pill');
  const decisionText = document.getElementById('decision-text');
  const latencyInfo = document.getElementById('latency-info');
  const modelBadge = document.getElementById('model-version-badge');

  if (modelBadge) modelBadge.textContent = data.model_version || 'xgboost-v1';
  
  // Smooth animated numerical counter
  if (gaugeVal) {
    animateValue(gaugeVal, state.lastScorePercent || 0, targetPercent, 700);
  }
  state.lastScorePercent = targetPercent;

  // SVG circumference: 2 * PI * 80 ~= 502.65
  const circumference = 502.65;
  const offset = circumference - (data.risk_score * circumference);
  if (gaugeCircle) {
    gaugeCircle.style.strokeDashoffset = offset;
    if (data.flagged) {
      gaugeCircle.style.stroke = '#ef4444';
    } else if (data.risk_score > 0.4) {
      gaugeCircle.style.stroke = '#f59e0b';
    } else {
      gaugeCircle.style.stroke = '#10b981';
    }
  }

  // Decision Pill
  if (decisionPill && decisionText) {
    if (data.flagged) {
      decisionPill.className = 'decision-pill flagged';
      decisionText.textContent = 'HIGH RISK — FRAUD ALERT TRIGGERED';
      showToast(`High Risk Alert: ${percent}% fraud probability. Transaction flagged!`, 'danger', 'Fraud Alert Triggered');
    } else {
      decisionPill.className = 'decision-pill clean';
      decisionText.textContent = 'CLEAN TRANSACTION — APPROVED';
      showToast(`Transaction approved: ${percent}% risk score (${latencyMs}ms).`, 'success', 'Scoring Complete');
    }
  }

  if (latencyInfo) {
    latencyInfo.textContent = `Latency: ${latencyMs}ms • Flag Threshold: 94.5%`;
  }

  // Render Explainable AI Factors
  renderXaiFactors(data.risk_factors || []);
}

function renderXaiFactors(factors) {
  const list = document.getElementById('xai-factors-list');
  if (!list) return;

  if (!factors || factors.length === 0) {
    list.innerHTML = `<div class="xai-empty">No dominant risk factors detected. Baseline risk parameters.</div>`;
    return;
  }

  const maxAbs = Math.max(...factors.map(f => Math.abs(f.contribution)), 0.05);

  list.innerHTML = factors.map((f, idx) => {
    const isUp = f.direction === 'risk_increasing';
    const sign = f.contribution > 0 ? '+' : '';
    const impactClass = isUp ? 'increasing' : 'decreasing';
    const arrow = isUp ? '▲ Increases Fraud Risk' : '▼ Mitigates Risk';
    const widthPercent = Math.min(100, Math.max(12, (Math.abs(f.contribution) / maxAbs) * 100)).toFixed(0);

    return `
      <div class="xai-card" style="animation: paneFadeIn 0.35s cubic-bezier(0.16, 1, 0.3, 1) both; animation-delay: ${idx * 0.06}s;">
        <div class="xai-card-top">
          <span class="xai-feature-name">${escapeHtml(f.feature)}</span>
          <span class="xai-impact-badge ${impactClass}">${sign}${f.contribution.toFixed(3)} (${arrow})</span>
        </div>
        <div class="xai-progress-bar">
          <div class="xai-progress-fill ${impactClass}" style="width: 0%;" data-target-width="${widthPercent}%"></div>
        </div>
        <p class="xai-desc">${escapeHtml(f.description)}</p>
      </div>
    `;
  }).join('');

  // Smoothly expand bar widths in next tick
  requestAnimationFrame(() => {
    setTimeout(() => {
      document.querySelectorAll('.xai-progress-fill').forEach(bar => {
        const target = bar.getAttribute('data-target-width');
        if (target) bar.style.width = target;
      });
    }, 50);
  });
}

// ==========================================================================
// Copilot Chat (RAG)
// ==========================================================================

function applyPrompt(text) {
  const input = document.getElementById('chat-input');
  if (input) {
    input.value = text;
    input.focus();
  }
}

function clearChat() {
  const feed = document.getElementById('chat-messages');
  if (feed) {
    feed.innerHTML = `
      <div class="chat-msg assistant">
        <div class="msg-avatar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        </div>
        <div class="msg-bubble">
          <p>Chat cleared. Ask any question about the flagged cases, UPI IDs, or mule networks.</p>
        </div>
      </div>
    `;
  }
}

async function handleAskSubmit(event) {
  event.preventDefault();
  const input = document.getElementById('chat-input');
  const askBtn = document.getElementById('ask-btn');
  const query = input.value.trim();
  if (!query) return;

  const topK = parseInt(document.getElementById('top-k-input').value, 10) || 5;

  // Append user message
  appendChatMessage('user', query);
  input.value = '';

  // Append thinking assistant placeholder
  const placeholderId = `ai-msg-${Date.now()}`;
  appendChatMessage('assistant', 'Searching vector database and generating grounded response...', placeholderId);

  askBtn.disabled = true;

  try {
    const res = await secureFetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: topK }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Copilot assistant error');
    }

    const data = await res.json();
    updateAssistantMessage(placeholderId, data.answer, data.sources || []);
  } catch (err) {
    updateAssistantMessage(placeholderId, `Error: ${err.message}`, []);
  } finally {
    askBtn.disabled = false;
  }
}

function appendChatMessage(role, text, id = null) {
  const feed = document.getElementById('chat-messages');
  if (!feed) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-msg ${role}`;
  if (id) msgDiv.id = id;

  const iconSvg = role === 'user'
    ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`
    : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`;

  msgDiv.innerHTML = `
    <div class="msg-avatar">${iconSvg}</div>
    <div class="msg-bubble">
      <p>${escapeHtml(text)}</p>
    </div>
  `;

  feed.appendChild(msgDiv);
  feed.scrollTop = feed.scrollHeight;
}

function updateAssistantMessage(id, answerText, sources) {
  const msgDiv = document.getElementById(id);
  if (!msgDiv) return;

  const bubble = msgDiv.querySelector('.msg-bubble');
  if (!bubble) return;

  // Format citations like [Case: CASE-XXXX] into clickable pills
  let formatted = escapeHtml(answerText).replace(/\[Case:\s*([A-Za-z0-9-]+)\]/g, (match, caseId) => {
    return `<button class="citation-pill" onclick="openCaseById('${caseId}')">🔍 ${caseId}</button>`;
  });

  // Convert markdown bold **text** to <strong>
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Convert newlines to paragraphs/breaks
  formatted = formatted.split('\n\n').map(p => `<p>${p.replace(/\n/g, '<br/>')}</p>`).join('');

  let sourcesHtml = '';
  if (sources && sources.length > 0) {
    sourcesHtml = `
      <div class="sources-container">
        <div class="sources-title">Retrieved Evidence Sources (${sources.length})</div>
        <div class="sources-grid">
          ${sources.map(s => `
            <div class="source-card" onclick="openCaseById('${escapeHtml(s.case_id)}')">
              <div class="source-header">
                <span class="mono">${escapeHtml(s.case_id)}</span>
                <span class="badge ${s.score > 0.5 ? 'badge-red' : 'badge-amber'}">Sim: ${(s.score * 100).toFixed(0)}%</span>
              </div>
              <div class="source-snippet">${escapeHtml(s.snippet)}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  bubble.innerHTML = formatted + sourcesHtml;

  const feed = document.getElementById('chat-messages');
  if (feed) feed.scrollTop = feed.scrollHeight;
}

// ==========================================================================
// Case Explorer Table
// ==========================================================================

let searchDebounceTimer = null;
function debounceCaseSearch() {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    state.casesSearchQuery = document.getElementById('case-search-input').value.trim();
    state.casesPage = 1;
    loadCases();
  }, 300);
}

function setCaseStatusFilter(status, btn) {
  state.casesStatusFilter = status;
  state.casesPage = 1;
  document.querySelectorAll('.filter-pill').forEach(el => el.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadCases();
}

function changePage(delta) {
  state.casesPage += delta;
  loadCases();
}

async function loadCases() {
  const tbody = document.getElementById('cases-table-body');
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4">Loading cases...</td></tr>`;

  try {
    const params = new URLSearchParams({
      page: state.casesPage,
      page_size: state.casesPageSize,
    });
    if (state.casesStatusFilter !== 'all') {
      params.append('status', state.casesStatusFilter);
    }
    if (state.casesSearchQuery) {
      params.append('search', state.casesSearchQuery);
    }

    const res = await secureFetch(`/cases?${params.toString()}`);
    if (!res.ok) throw new Error('Failed to fetch cases');
    const data = await res.json();

    state.casesTotal = data.total;
    renderCasesTable(data.items);
    updatePaginationControls(data.total);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">Error loading cases: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderCasesTable(cases) {
  const tbody = document.getElementById('cases-table-body');
  if (!tbody) return;

  if (cases.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted">No cases match the selected filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = cases.map(c => {
    const riskPercent = (c.risk_score * 100).toFixed(1);
    const riskBadgeClass = c.risk_score >= 0.85 ? 'badge-red' : c.risk_score >= 0.65 ? 'badge-amber' : 'badge-green';
    const statusBadgeClass = c.status === 'escalated' ? 'badge-red' : c.status === 'open' ? 'badge-purple' : c.status === 'under_review' ? 'badge-amber' : 'badge-green';
    const dateFormatted = new Date(c.timestamp).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

    return `
      <tr>
        <td class="mono text-bold">${escapeHtml(c.case_id)}</td>
        <td>${escapeHtml(c.account_holder)}</td>
        <td class="mono">${escapeHtml(c.upi_id)}</td>
        <td class="text-bold">₹${Number(c.amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
        <td><span class="badge ${riskBadgeClass}">${riskPercent}%</span></td>
        <td><span class="badge ${statusBadgeClass}">${escapeHtml(c.status.toUpperCase())}</span></td>
        <td class="mono text-muted">${dateFormatted}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="openCaseById('${escapeHtml(c.case_id)}')">
            Inspect
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function updatePaginationControls(total) {
  const pageInfo = document.getElementById('page-info');
  const prevBtn = document.getElementById('btn-prev-page');
  const nextBtn = document.getElementById('btn-next-page');
  const pageNum = document.getElementById('current-page-num');

  const start = total === 0 ? 0 : (state.casesPage - 1) * state.casesPageSize + 1;
  const end = Math.min(state.casesPage * state.casesPageSize, total);

  if (pageInfo) pageInfo.textContent = `Showing ${start}-${end} of ${total} cases`;
  if (pageNum) pageNum.textContent = state.casesPage;
  if (prevBtn) prevBtn.disabled = state.casesPage <= 1;
  if (nextBtn) nextBtn.disabled = end >= total;
}

// ==========================================================================
// Case Detail Modal
// ==========================================================================

async function openCaseById(caseId) {
  state.activeCaseModalId = caseId;
  const modal = document.getElementById('case-modal');

  try {
    const res = await secureFetch(`/cases/${caseId}`);
    if (!res.ok) throw new Error('Case not found');
    const caseData = await res.json();

    document.getElementById('modal-case-id').textContent = caseData.case_id;
    document.getElementById('modal-holder-name').textContent = caseData.account_holder;
    document.getElementById('modal-account-num').textContent = caseData.account_number;
    document.getElementById('modal-upi-id').textContent = caseData.upi_id;
    document.getElementById('modal-amount').textContent = `₹${Number(caseData.amount).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
    document.getElementById('modal-assigned').textContent = caseData.assigned_to;
    document.getElementById('modal-contact').textContent = `${caseData.phone} • ${caseData.email}`;
    document.getElementById('modal-address').textContent = caseData.address;
    document.getElementById('modal-complaint').textContent = caseData.complaint_text;
    document.getElementById('modal-notes').textContent = caseData.investigator_notes;

    const riskBadge = document.getElementById('modal-risk-badge');
    const statusBadge = document.getElementById('modal-status-badge');
    const currentStatusEl = document.getElementById('modal-current-status');
    const noteInput = document.getElementById('new-note-input');
    if (noteInput) noteInput.value = '';

    riskBadge.textContent = `RISK: ${(caseData.risk_score * 100).toFixed(1)}%`;
    riskBadge.className = `badge ${caseData.risk_score >= 0.85 ? 'badge-red' : 'badge-amber'}`;

    const statusUpper = caseData.status.toUpperCase();
    statusBadge.textContent = statusUpper;
    const statusClass = caseData.status === 'escalated' ? 'badge-red' : caseData.status === 'under_review' ? 'badge-amber' : caseData.status === 'resolved' ? 'badge-green' : 'badge-purple';
    statusBadge.className = `badge ${statusClass}`;
    if (currentStatusEl) currentStatusEl.textContent = statusUpper;

    const linkedContainer = document.getElementById('modal-linked-accounts');
    if (caseData.linked_accounts && caseData.linked_accounts.length > 0) {
      linkedContainer.innerHTML = caseData.linked_accounts.map(acc => `
        <span class="linked-tag">🔗 Acct: ${escapeHtml(acc)}</span>
      `).join('');
    } else {
      linkedContainer.innerHTML = `<span class="text-muted">No linked mule accounts identified</span>`;
    }

    if (modal) modal.classList.add('open');
  } catch (err) {
    alert(`Could not load case details: ${err.message}`);
  }
}

async function updateCurrentCaseStatus(newStatus) {
  if (!state.activeCaseModalId) return;
  const caseId = state.activeCaseModalId;
  try {
    const res = await secureFetch(`/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) throw new Error('Failed to update case status');
    const updated = await res.json();

    const statusBadge = document.getElementById('modal-status-badge');
    const currentStatusEl = document.getElementById('modal-current-status');
    const statusUpper = updated.status.toUpperCase();
    if (statusBadge) {
      statusBadge.textContent = statusUpper;
      const statusClass = updated.status === 'escalated' ? 'badge-red' : updated.status === 'under_review' ? 'badge-amber' : updated.status === 'resolved' ? 'badge-green' : 'badge-purple';
      statusBadge.className = `badge ${statusClass}`;
    }
    if (currentStatusEl) currentStatusEl.textContent = statusUpper;

    showToast(`Case #${caseId} status updated to ${statusUpper}`, 'success', 'Status Updated');
    loadCases();
  } catch (err) {
    showToast(`Could not update case status: ${err.message}`, 'danger', 'Update Error');
  }
}

async function submitCaseNote() {
  if (!state.activeCaseModalId) return;
  const caseId = state.activeCaseModalId;
  const noteInput = document.getElementById('new-note-input');
  if (!noteInput) return;
  const text = noteInput.value.trim();
  if (!text) {
    showToast('Please enter a note before saving.', 'warning', 'Validation');
    return;
  }

  const saveBtn = document.getElementById('save-note-btn');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }

  try {
    const res = await secureFetch(`/cases/${caseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ investigator_notes: text }),
    });
    if (!res.ok) throw new Error('Failed to save note');
    const updated = await res.json();

    document.getElementById('modal-notes').textContent = updated.investigator_notes;
    noteInput.value = '';
    showToast(`Forensic note appended to case #${caseId}`, 'success', 'Note Saved');
    loadCases();
  } catch (err) {
    showToast(`Could not save note: ${err.message}`, 'danger', 'Save Error');
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Note';
    }
  }
}

async function exportCurrentCase() {
  if (!state.activeCaseModalId) return;
  const caseId = state.activeCaseModalId;
  try {
    const res = await secureFetch(`/cases/${caseId}/export`);
    if (!res.ok) throw new Error('Failed to export case report');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `case_${caseId}_report.json`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    a.remove();
    showToast(`Dossier case_${caseId}_report.json downloaded`, 'success', 'Export Complete');
  } catch (err) {
    showToast(`Export failed: ${err.message}`, 'danger', 'Export Error');
  }
}

function closeCaseModal() {
  const modal = document.getElementById('case-modal');
  if (modal) modal.classList.remove('open');
}

function closeModal(event) {
  if (event.target.id === 'case-modal') {
    closeCaseModal();
  }
}

function askAboutCurrentCase() {
  if (!state.activeCaseModalId) return;
  const caseId = state.activeCaseModalId;
  closeCaseModal();
  switchTab('copilot');
  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.value = `Provide a full investigation summary and risk analysis for case ${caseId}`;
    document.getElementById('ask-btn').click();
  }
}

// ==========================================================================
// Animation & UI Helpers
// ==========================================================================

function animateValue(element, start, end, duration) {
  if (!element) return;
  const startTime = performance.now();
  const startNum = parseFloat(start) || 0;
  const endNum = parseFloat(end) || 0;

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Smooth easeOutCubic
    const ease = 1 - Math.pow(1 - progress, 3);
    const currentVal = (startNum + (endNum - startNum) * ease).toFixed(1);
    element.textContent = `${currentVal}%`;

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      element.textContent = `${endNum.toFixed(1)}%`;
    }
  }

  requestAnimationFrame(update);
}

function showToast(message, type = 'info', title = null) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const iconSvg = type === 'success'
    ? '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>'
    : type === 'danger'
    ? '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    : type === 'warning'
    ? '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    : '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';

  const displayTitle = title || (type.charAt(0).toUpperCase() + type.slice(1));

  toast.innerHTML = `
    ${iconSvg}
    <div class="toast-content">
      <div class="toast-title">${escapeHtml(displayTitle)}</div>
      <div class="toast-msg">${escapeHtml(message)}</div>
    </div>
    <button class="toast-close" aria-label="Close notification" onclick="this.parentElement.remove()">&times;</button>
  `;

  container.appendChild(toast);

  // Auto remove after 3.5s with smooth transition
  setTimeout(() => {
    if (toast.parentElement) {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 250);
    }
  }, 3500);
}

function initSpotlightTracking() {
  const cards = document.querySelectorAll('.panel.glass, .metric-card, .modal-card.glass');
  cards.forEach(card => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', `${x}px`);
      card.style.setProperty('--mouse-y', `${y}px`);
    });
  });
}

function startSystemClock() {
  const clock = document.getElementById('system-clock');
  if (!clock) return;

  function tick() {
    const now = new Date();
    const utcStr = now.toISOString().slice(11, 19) + ' UTC';
    clock.textContent = utcStr;
  }
  tick();
  setInterval(tick, 1000);
}

// ==========================================================================
// High-Throughput Batch Scoring Simulator
// ==========================================================================

function openBatchModal() {
  const modal = document.getElementById('batch-modal');
  if (modal) {
    modal.style.display = 'flex';
    modal.classList.add('open');
  }
}

function closeBatchModal() {
  const modal = document.getElementById('batch-modal');
  if (modal) {
    modal.style.display = 'none';
    modal.classList.remove('open');
  }
}

function generateSyntheticBatch(count = 20) {
  const categories = ['misc_net', 'grocery_pos', 'shopping_net', 'gas_transport', 'travel', 'entertainment'];
  const transactions = [];

  for (let i = 0; i < count; i++) {
    const isSuspicious = Math.random() < 0.25; // 25% suspicious
    const amount = isSuspicious
      ? parseFloat((Math.random() * 2500 + 400).toFixed(2))
      : parseFloat((Math.random() * 85 + 5).toFixed(2));
    const velocity = isSuspicious ? Math.floor(Math.random() * 12 + 6) : Math.floor(Math.random() * 3 + 1);
    const category = categories[Math.floor(Math.random() * categories.length)];

    const pca = {};
    for (let p = 1; p <= 28; p++) {
      const val = isSuspicious && (p === 4 || p === 14 || p === 10)
        ? (Math.random() * 5 + 3) * (Math.random() > 0.5 ? 1 : -1)
        : (Math.random() * 2 - 1);
      pca[`v${p}`] = parseFloat(val.toFixed(4));
    }

    transactions.push({
      transaction_id: `TXN-SYNTH-${Date.now().toString().slice(-6)}-${i + 1}`,
      amount: amount,
      time: parseFloat(((Date.now() / 1000) % 172800).toFixed(1)),
      category: category,
      velocity_1h: velocity,
      ...pca
    });
  }

  return transactions;
}

async function runBatchScoreDemo(count = 20) {
  const runBtn = document.getElementById('btn-run-batch');
  const tbody = document.getElementById('batch-results-body');
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.innerHTML = `
      <span class="loading-spinner" style="width: 14px; height: 14px; border-width: 2px;"></span>
      Scoring ${count} Txns...
    `;
  }

  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">
          <span class="loading-spinner" style="width: 20px; height: 20px; margin: 0 auto 8px;"></span>
          Executing parallel batch inference across ${count} transactions...
        </td>
      </tr>
    `;
  }

  const batchPayload = generateSyntheticBatch(count);
  const startTime = performance.now();

  try {
    const res = await secureFetch('/score/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transactions: batchPayload }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Batch request failed with status ${res.status}`);
    }

    const data = await res.json();
    const duration = (performance.now() - startTime).toFixed(1);

    // Update batch stats cards
    const statTotal = document.getElementById('batch-stat-total');
    const statFlagged = document.getElementById('batch-stat-flagged');
    const statLatency = document.getElementById('batch-stat-latency');
    const statAvgScore = document.getElementById('batch-stat-avg-score');

    if (statTotal) statTotal.textContent = data.total_processed ?? data.results?.length ?? 0;
    if (statFlagged) statFlagged.textContent = data.total_flagged ?? 0;
    if (statLatency) statLatency.textContent = `${data.total_latency_ms ? data.total_latency_ms.toFixed(1) : duration} ms`;

    const avg = data.results && data.results.length > 0
      ? (data.results.reduce((acc, r) => acc + r.risk_score, 0) / data.results.length * 100).toFixed(1)
      : '0.0';
    if (statAvgScore) statAvgScore.textContent = `${avg}%`;

    // Render results
    if (tbody && data.results) {
      tbody.innerHTML = data.results.map((r, idx) => {
        const txn = batchPayload[idx] || {};
        const scorePercent = (r.risk_score * 100).toFixed(1);
        const scoreColor = r.flagged ? '#ef4444' : r.risk_score > 0.4 ? '#f59e0b' : '#10b981';
        const badgeClass = r.flagged ? 'status-badge escalated' : 'status-badge resolved';
        const decisionText = r.flagged ? 'FLAGGED' : 'CLEAN';

        return `
          <tr style="animation: paneFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) both; animation-delay: ${idx * 0.02}s;">
            <td class="mono font-semibold" style="font-size: 0.8rem;">${escapeHtml(r.transaction_id)}</td>
            <td class="mono font-semibold">$${(txn.amount || 0).toFixed(2)}</td>
            <td><span class="category-tag">${escapeHtml(txn.category || 'misc')}</span></td>
            <td class="mono">${txn.velocity_1h || 1}/hr</td>
            <td>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="mono font-semibold" style="color: ${scoreColor}; width: 45px;">${scorePercent}%</span>
                <div style="flex: 1; min-width: 50px; max-width: 80px; height: 6px; background: #e2e8f0; border-radius: 9999px; overflow: hidden;">
                  <div style="width: ${scorePercent}%; height: 100%; background: ${scoreColor}; border-radius: 9999px;"></div>
                </div>
              </div>
            </td>
            <td><span class="${badgeClass}" style="font-size: 0.72rem; padding: 2px 8px;">${decisionText}</span></td>
          </tr>
        `;
      }).join('');
    }

    showToast(`Batch completed: ${data.total_scored} txns scored in ${duration}ms (${data.flagged_count} flagged).`, 'success', 'Batch Scoring Success');

  } catch (err) {
    showToast(`Batch scoring failed: ${err.message}`, 'danger', 'Batch Error');
    if (tbody) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; color: var(--color-danger); padding: 2rem;">
            Failed to score batch: ${escapeHtml(err.message)}
          </td>
        </tr>
      `;
    }
  } finally {
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Run Synthetic Batch
      `;
    }
  }
}

// Utility: Escape HTML
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ==========================================================================
// Tier-1 Real-time Streaming, MLOps Drift & Mule Network Graph Logic
// ==========================================================================

let liveWs = null;
let wsReconnectTimer = null;

function initWebSocketLiveStream() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live-transactions`;

  try {
    liveWs = new WebSocket(wsUrl);

    liveWs.onopen = () => {
      console.log('WebSocket Live Stream Connected');
      const dot = document.getElementById('ws-pulse-dot');
      const text = document.getElementById('ws-status-text');
      if (dot) dot.className = 'pulse-dot green';
      if (text) text.textContent = 'WS LIVE STREAM';
    };

    liveWs.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === 'TRANSACTION_SCORED') {
          handleIncomingLiveTransaction(data);
        }
      } catch (e) {
        console.debug('WS parse error:', e);
      }
    };

    liveWs.onclose = () => {
      const dot = document.getElementById('ws-pulse-dot');
      const text = document.getElementById('ws-status-text');
      if (dot) dot.className = 'pulse-dot amber';
      if (text) text.textContent = 'WS RECONNECTING';
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(initWebSocketLiveStream, 4000);
    };

    liveWs.onerror = () => {
      if (liveWs) liveWs.close();
    };
  } catch (err) {
    console.debug('WS initialization deferred:', err);
  }
}

function handleIncomingLiveTransaction(data) {
  const feed = document.getElementById('ticker-feed');
  if (!feed) return;

  const pill = document.createElement('div');
  const alertClass = data.risk_score >= 0.8 ? 'critical' : (data.risk_score >= 0.5 ? 'warning' : 'low');
  pill.className = `ticker-pill ${alertClass}`;
  pill.innerHTML = `
    <strong>${escapeHtml(data.transaction_id || 'TXN')}</strong>:
    ₹${Number(data.amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
    <span style="font-weight: 700;">(${(data.risk_score * 100).toFixed(1)}%)</span>
  `;

  feed.insertBefore(pill, feed.firstChild);
  while (feed.children.length > 8) {
    feed.removeChild(feed.lastChild);
  }
}

async function triggerSimulatedStream() {
  const btn = document.getElementById('btn-stream-sim');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Emitting...';
  }
  try {
    const res = await secureFetch('/scoring/simulate-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: 6, delay_ms: 80, high_risk_ratio: 0.5 }),
    });
    if (res.ok) {
      showToast('Simulated burst transmitted over WebSockets', 'info', 'Stream Emitted');
    }
  } catch (err) {
    console.error('Simulate stream error:', err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Simulate Stream Burst';
    }
  }
}

async function refreshDriftAndShadow() {
  try {
    const [driftRes, shadowRes] = await Promise.all([
      secureFetch('/scoring/drift'),
      secureFetch('/scoring/shadow-metrics'),
    ]);

    if (driftRes.ok) {
      const drift = await driftRes.json();
      const psiEl = document.getElementById('drift-psi-val');
      const badgeEl = document.getElementById('drift-status-badge');
      if (psiEl) psiEl.textContent = drift.max_psi !== undefined ? drift.max_psi.toFixed(3) : '0.021';
      if (badgeEl) {
        badgeEl.textContent = drift.overall_status || 'HEALTHY';
        badgeEl.className = drift.overall_status === 'HEALTHY' ? 'badge badge-green' : 'badge badge-red';
      }

      const pillsEl = document.getElementById('monitored-features-pills');
      if (pillsEl && drift.features) {
        pillsEl.innerHTML = Object.entries(drift.features).slice(0, 5).map(([f, info]) => `
          <span class="feature-drift-pill">
            <span>${escapeHtml(f.toUpperCase())}:</span>
            <strong>${info.psi !== undefined ? info.psi.toFixed(3) : '0.010'} (${info.status || 'Stable'})</strong>
          </span>
        `).join('');
      }
    }

    if (shadowRes.ok) {
      const shadow = await shadowRes.json();
      const agreeEl = document.getElementById('shadow-agreement-val');
      const maeEl = document.getElementById('shadow-mae-val');
      const latEl = document.getElementById('shadow-latency-val');
      if (agreeEl) agreeEl.textContent = `${(shadow.decision_agreement_rate * 100).toFixed(1)}%`;
      if (maeEl) maeEl.textContent = shadow.mean_absolute_error.toFixed(3);
      if (latEl) latEl.textContent = `${shadow.average_challenger_latency_ms.toFixed(2)} ms`;
    }
  } catch (err) {
    console.debug('Drift refresh deferred:', err);
  }
}

// Mule Network Graph Modal
async function openNetworkGraphModal(caseId) {
  if (!caseId) return;
  const modal = document.getElementById('network-modal');
  const subtitle = document.getElementById('network-case-subtitle');
  if (subtitle) subtitle.textContent = `Target Ego-Network: ${caseId}`;
  if (modal) modal.style.display = 'flex';

  try {
    const res = await secureFetch(`/cases/${caseId}/network?hops=2`);
    if (!res.ok) throw new Error('Network graph unavailable');
    const data = await res.json();

    const banner = document.getElementById('network-alerts-banner');
    if (banner) {
      if (data.mule_ring_alerts && data.mule_ring_alerts.length > 0) {
        const ring = data.mule_ring_alerts[0];
        banner.style.display = 'block';
        banner.innerHTML = `
          <strong>CRITICAL MULE RING DETECTED:</strong> Hub entity <code>${escapeHtml(ring.hub_label || ring.hub_entity)}</code>
          interconnects ${ring.case_count} distinct fraud cases with cumulative financial exposure of
          <strong>₹${Number(ring.total_exposure_amount || 0).toLocaleString('en-IN')}</strong>.
        `;
      } else {
        banner.style.display = 'none';
      }
    }

    const metricsEl = document.getElementById('network-metrics-row');
    if (metricsEl && data.graph && data.graph.metrics) {
      const m = data.graph.metrics;
      metricsEl.innerHTML = `
        <span class="badge badge-purple">Nodes: ${m.total_nodes}</span>
        <span class="badge badge-cyan">Edges: ${m.total_edges}</span>
        <span class="badge ${m.shared_entities > 0 ? 'badge-red' : 'badge-green'}">Shared Hubs: ${m.shared_entities}</span>
        <span class="badge badge-amber">Density: ${(m.density * 100).toFixed(1)}%</span>
      `;
    }

    renderNetworkCanvas(data.graph);
  } catch (err) {
    console.error('Network graph load failed:', err);
  }
}

function closeNetworkModal() {
  const modal = document.getElementById('network-modal');
  if (modal) modal.style.display = 'none';
}

function renderNetworkCanvas(graph) {
  const canvas = document.getElementById('network-canvas');
  if (!canvas || !graph || !graph.nodes) return;
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const nodes = graph.nodes;
  const edges = graph.edges || [];
  const nodeCount = nodes.length;
  if (nodeCount === 0) return;

  const positions = {};
  const cx = width / 2;
  const cy = height / 2;

  // Layout target case in center, neighbors in radial orbits
  nodes.forEach((n, idx) => {
    if (n.is_target) {
      positions[n.id] = { x: cx, y: cy };
    } else {
      const angle = (idx / (nodeCount - 1 || 1)) * 2 * Math.PI;
      const radius = 110 + (idx % 2 === 0 ? 40 : 0);
      positions[n.id] = {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      };
    }
  });

  // Draw Edges
  ctx.strokeStyle = '#cbd5e1';
  ctx.lineWidth = 1.5;
  edges.forEach((edge) => {
    const p1 = positions[edge.source];
    const p2 = positions[edge.target];
    if (p1 && p2) {
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    }
  });

  // Draw Nodes
  nodes.forEach((n) => {
    const pos = positions[n.id];
    if (!pos) return;

    let fill = '#64748b';
    let radius = 10;
    if (n.type === 'case') { fill = '#ef4444'; radius = 14; }
    else if (n.type === 'account') { fill = '#3b82f6'; radius = 11; }
    else if (n.type === 'upi') { fill = '#f59e0b'; radius = 10; }
    else if (n.type === 'device') { fill = '#10b981'; radius = 9; }
    else if (n.type === 'ip') { fill = '#06b6d4'; radius = 9; }

    // Outer glow for target node
    if (n.is_target) {
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, radius + 6, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(239, 68, 68, 0.25)';
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(pos.x, pos.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Node text
    ctx.font = '10px Inter, sans-serif';
    ctx.fillStyle = '#1e293b';
    ctx.textAlign = 'center';
    const label = (n.label || n.id).slice(0, 14);
    ctx.fillText(label, pos.x, pos.y + radius + 12);
  });
}

// FinCEN SAR Export
async function exportFinCENSar(caseId, format = 'xml') {
  if (!caseId) return;
  try {
    const res = await secureFetch(`/cases/${caseId}/sar?format=${format}`, {
      method: 'POST',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'SAR generation failed' }));
      throw new Error(err.detail || 'Access Denied');
    }

    if (format === 'json') {
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      downloadBlob(blob, `SAR_FinCEN_${caseId}_dossier.json`);
      showToast(`SAR JSON dossier downloaded for case ${caseId}`, 'success', 'SAR Export');
    } else {
      const blob = await res.blob();
      downloadBlob(blob, `SAR_FinCEN_${caseId}.xml`);
      showToast(`FinCEN XML compliance file downloaded for ${caseId}`, 'success', 'FinCEN SAR Export');
    }
  } catch (err) {
    showToast(`SAR export error: ${err.message}`, 'danger', 'Compliance Error');
  }
}

function downloadBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}


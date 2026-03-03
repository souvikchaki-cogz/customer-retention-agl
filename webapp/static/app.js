document.getElementById('year').textContent = new Date().getFullYear();

const evaluateForm = document.getElementById('evaluate-form');
const evaluateOutput = document.getElementById('evaluate-output');
const evaluationStatusDiv = document.getElementById('evaluation-status');
const evaluationResultDiv = document.getElementById('evaluation-result');
const predictBtn = document.getElementById('predict-btn');
const predictOutput = document.getElementById('predict-output');
const existingTriggersContainer = document.getElementById('existing-triggers-content');

// Empty string means same origin
const apiBase = '';

function setLoading(el, loading, text) {
  if (!el) return;
  if (loading) {
    el.dataset.originalText = el.textContent;
    if (text) el.textContent = text;
    el.disabled = true;
  } else {
    el.textContent = el.dataset.originalText || el.textContent;
    el.disabled = false;
  }
}

function explanationFromStats(t) {
  if (!t) return '';
  if (t.explanation) return t.explanation; // Prefer server-provided explanation
  if (t.support == null) return '';
  const pDisp = t.p_value < 0.001 ? '<0.001' : t.p_value?.toFixed?.(3);
  const fdrDisp = t.fdr != null ? (t.fdr < 0.001 ? '<0.001' : t.fdr.toFixed(3)) : undefined;
  return `Support ${(t.support*100).toFixed(1)}%, lift ${t.lift?.toFixed?.(2)}, OR ${t.odds_ratio?.toFixed?.(2)}, p ${pDisp}${fdrDisp ? ', fdr ' + fdrDisp : ''}`;
}

async function fetchExistingTriggers() {
  if (!existingTriggersContainer) return;
  try {
    existingTriggersContainer.textContent = 'Loading...';
    const resp = await fetch(`${apiBase}/api/triggers?limit=25`);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (!Array.isArray(data.triggers) || data.triggers.length === 0) {
      existingTriggersContainer.innerHTML = '<em class="muted">No triggers available</em>';
      return;
    }
    const rows = data.triggers.map(t => {
      const sev = t.severity ? `<span class="sev sev-${String(t.severity).toLowerCase()}">${t.severity}</span>` : '';
      const support = t.support != null ? (t.support*100).toFixed(1)+'%' : '—';
      const lift = t.lift != null ? t.lift.toFixed(2) : '—';
      const oratio = t.odds_ratio != null ? t.odds_ratio.toFixed(2) : '—';
      const pval = t.p_value != null ? (t.p_value < 0.001 ? '<0.001' : t.p_value.toFixed(3)) : '—';
      const fdr = t.fdr != null ? (t.fdr < 0.001 ? '<0.001' : t.fdr.toFixed(3)) : '—';
      const idAttr = t.id != null ? ` data-id="${t.id}"` : '';
      return `<tr${idAttr}><td>${sev}${t.phrase}</td><td>${support}</td><td>${lift}</td><td>${oratio}</td><td>${pval}</td><td>${fdr}</td><td class="explanation">${explanationFromStats(t)}</td><td class="actions">${t.id != null ? '<button class="delete" type="button">Delete</button>' : ''}</td></tr>`;
    }).join('');
    existingTriggersContainer.innerHTML = `<table class="results">
      <thead><tr><th>Trigger</th><th>Support</th><th>Lift</th><th>Odds Ratio</th><th>p-value</th><th>FDR</th><th>Explanation</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    wireDeleteActions();
  } catch (err) {
    console.error('Fetch existing triggers failed', err);
    existingTriggersContainer.innerHTML = `<span class="error">Error loading triggers</span>`;
  }
}

let evaluationPollTimer = null;

function renderEvaluationResult(result) {
  if (!evaluationResultDiv) return;
  if (!result) { evaluationResultDiv.innerHTML = ''; return; }
  const {
    should_emit, score, rule_hits_json = [], structured_snapshot_json = {}, explanation_text,
    agent_version, ruleset_version, note_id, customer_id
  } = result;
  const summaryTable = `<table class="results compact">
    <thead><tr><th colspan="2">Evaluation Summary</th></tr></thead>
    <tbody>
      <tr><td>Customer ID</td><td>${customer_id || '—'}</td></tr>
      <tr><td>Note ID</td><td>${note_id || '—'}</td></tr>
      <tr><td>Score</td><td>${score != null ? (score*100).toFixed(1) + '%' : '—'}</td></tr>
      <tr><td>Emit Lead?</td><td>${should_emit ? '<span class="badge yes">Yes</span>' : '<span class="badge no">No</span>'}</td></tr>
      <tr><td>Explanation</td><td>${explanation_text || '—'}</td></tr>
      <tr><td>Agent Version</td><td>${agent_version || '—'}</td></tr>
      <tr><td>Ruleset Version</td><td>${ruleset_version || '—'}</td></tr>
    </tbody></table>`;
  const rulesRows = rule_hits_json.map(r => `<tr><td>${r.rule_id}</td><td>${(r.confidence*100).toFixed(0)}%</td><td>${r.evidence_text || ''}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">No rule hits</td></tr>';
  const rulesTable = `<table class="results compact">
    <thead><tr><th colspan="3">Rule Hits</th></tr><tr><th>Rule</th><th>Confidence</th><th>Evidence</th></tr></thead>
    <tbody>${rulesRows}</tbody></table>`;
  const snapshotEntries = Object.entries(structured_snapshot_json || {});
  const snapshotRows = snapshotEntries.length ? snapshotEntries.map(([k,v]) => `<tr><td>${k}</td><td>${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}</td></tr>`).join('') : '<tr><td colspan="2" class="muted">No snapshot data</td></tr>';
  const snapshotTable = `<table class="results compact">
    <thead><tr><th colspan="2">Structured Snapshot</th></tr></thead>
    <tbody>${snapshotRows}</tbody></table>`;
  evaluationResultDiv.innerHTML = `<div class="result-grid">${summaryTable}${rulesTable}${snapshotTable}</div>`;
}

function clearEvaluationPoll() {
  if (evaluationPollTimer) {
    clearInterval(evaluationPollTimer);
    evaluationPollTimer = null;
  }
}

async function pollEvaluation(instanceId) {
  clearEvaluationPoll();
  evaluationStatusDiv.textContent = 'Polling status...';
  evaluationPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/evaluate/status/${encodeURIComponent(instanceId)}`);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
  const prog = data.progress != null ? ` (${data.progress}%)` : '';
  const badgeClass = (data.runtime_status || '').toLowerCase();
  evaluationStatusDiv.innerHTML = `<span class="status-line"><span class="status-badge ${badgeClass}">${data.runtime_status || 'UNKNOWN'}</span>${data.status ? ' ' + data.status : ''}${prog}</span>`;
      if (data.runtime_status === 'Completed') {
        renderEvaluationResult(data.result);
        clearEvaluationPoll();
      } else if (data.runtime_status === 'Failed') {
        renderEvaluationResult(null);
        clearEvaluationPoll();
      }
    } catch (err) {
      console.error('Status poll error', err);
      evaluationStatusDiv.innerHTML = `<span class="error">Status polling failed</span>`;
      clearEvaluationPoll();
    }
  }, 4000);
}

evaluateForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  evaluateOutput.textContent = '';
  const btn = document.getElementById('evaluate-btn');
  setLoading(btn, true, 'Evaluating...');
  try {
    const customer_id = document.getElementById('customer-id').value.trim();
    const note = document.getElementById('note').value.trim();
    console.debug('Submitting evaluate', { customer_id, note });
    const resp = await fetch(`${apiBase}/api/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_id, note })
    });
    console.debug('Evaluate response status', resp.status);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    console.debug('Evaluate response body', data);
  evaluateOutput.innerHTML = `<div class=\"eval-banner\"><span class=\"title\">Evaluation Triggered<\/span><div class=\"meta\">Customer: <strong>${data.customer_id}<\/strong> | Instance: <code style=\"font-size:0.55rem;\">${data.instance_id || 'n/a'}<\/code><\/div><div>${data.message}<\/div><\/div>`;
    if (data.status_query_url && data.instance_id) {
      // status_query_url now a friendly internal path like /api/evaluate/status/{id}
      pollEvaluation(data.instance_id);
    } else {
  evaluationStatusDiv.innerHTML = '<span class="status-line"><span class="status-badge inprogress">Started</span> Orchestration started (no status URL returned)</span>';
    }
    renderEvaluationResult(null);
  } catch (err) {
    console.error('Evaluate error', err);
    evaluateOutput.innerHTML = `<span class="error">Error: ${err.message}</span>`;
  } finally {
    setLoading(btn, false);
    // Refresh existing triggers after an evaluation (could reflect newly matched ones later)
    fetchExistingTriggers();
  }
});

predictBtn.addEventListener('click', async () => {
  predictOutput.textContent = '';
  setLoading(predictBtn, true, 'Predicting...');
  try {
    console.debug('Triggering predict');
    const resp = await fetch(`${apiBase}/api/predict`, { method: 'POST' });
    console.debug('Predict response status', resp.status);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    console.debug('Predict response body', data);
    if (Array.isArray(data.triggers)) {
      const rows = data.triggers.map(t => {
        const pct = (t.support * 100).toFixed(1) + '%';
        const lift = t.lift.toFixed(2);
        const oratio = t.odds_ratio.toFixed(2);
        const pval = t.p_value < 0.001 ? '<0.001' : t.p_value.toFixed(3);
        const fdr = t.fdr < 0.001 ? '<0.001' : t.fdr.toFixed(3);
        const expl = explanationFromStats(t) || `Support ${pct}, lift ${lift}, OR ${oratio}, p ${pval}, fdr ${fdr}`;
        return `<tr data-trigger='${JSON.stringify(t).replace(/'/g,"&apos;")}'><td>${t.phrase}</td><td>${pct}</td><td>${lift}</td><td>${oratio}</td><td>${pval}</td><td>${fdr}</td><td>${expl}</td><td class="actions"><button class="approve" type="button">Approve</button><button class="disapprove" type="button">Disapprove</button></td></tr>`;
      }).join('');
      predictOutput.innerHTML = `
        <table class="results" id="predicted-table">
          <thead>
            <tr><th>Trigger</th><th>Support</th><th>Lift</th><th>Odds Ratio</th><th>p-value</th><th>FDR</th><th>Explanation</th><th>Actions</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>`;
      wirePredictionActions();
    } else {
      predictOutput.innerHTML = `<span class="error">Unexpected response</span>`;
    }
  } catch (err) {
    console.error('Predict error', err);
    predictOutput.innerHTML = `<span class="error">Error: ${err.message}</span>`;
  } finally {
    setLoading(predictBtn, false);
  }
});

// Initial load
function deriveApprovalPayload(row) {
  try {
    const dataAttr = row.getAttribute('data-trigger');
    if (!dataAttr) return null;
    return JSON.parse(dataAttr.replace(/&apos;/g, "'"));
  } catch { return null; }
}

function wirePredictionActions() {
  const table = document.getElementById('predicted-table');
  if (!table) return;
  table.querySelectorAll('button.approve').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const row = e.target.closest('tr');
      const payload = deriveApprovalPayload(row);
      if (!payload) return;
      btn.disabled = true;
      try {
        const resp = await fetch(`${apiBase}/api/triggers/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        row.classList.add('approved');
        row.querySelectorAll('button').forEach(b => b.remove());
        // Refresh existing triggers to show newly inserted if DB active
        fetchExistingTriggers();
      } catch (err) {
        console.error('Approve failed', err);
        btn.disabled = false;
      }
    });
  });
  table.querySelectorAll('button.disapprove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const row = e.target.closest('tr');
      row.classList.add('disapproved');
      row.querySelectorAll('button').forEach(b => b.remove());
    });
  });
}

// Initial load
fetchExistingTriggers();

function wireDeleteActions() {
  const table = existingTriggersContainer.querySelector('table');
  if (!table) return;
  table.querySelectorAll('button.delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const row = e.target.closest('tr');
      const id = row.getAttribute('data-id');
      if (!id) return;
      btn.disabled = true;
      try {
        const resp = await fetch(`${apiBase}/api/triggers/${id}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        if (data.deleted) {
          row.remove();
        } else {
          btn.disabled = false;
        }
      } catch (err) {
        console.error('Delete failed', err);
        btn.disabled = false;
      }
    });
  });
}
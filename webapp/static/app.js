document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('year').textContent = new Date().getFullYear();

  const evaluateForm = document.getElementById('evaluate-form');
  const evaluateOutput = document.getElementById('evaluate-output');
  const evaluationStatusDiv = document.getElementById('evaluation-status');
  const evaluationResultDiv = document.getElementById('evaluation-result');
  const predictBtn = document.getElementById('predict-btn');
  const predictOutput = document.getElementById('predict-output');
  const existingTriggersContainer = document.getElementById('existing-triggers-content');

  const apiBase = ''; // Empty string means same origin

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

  async function fetchExistingTriggers(phraseToHighlight) {
    if (!existingTriggersContainer) return;
    try {
      existingTriggersContainer.innerHTML = '<p class="text-gray-500">Loading...</p>';
      const resp = await fetch(`${apiBase}/api/triggers`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!Array.isArray(data.triggers) || data.triggers.length === 0) {
        existingTriggersContainer.innerHTML = '<p class="text-gray-500 italic">No approved triggers found.</p>';
        return [];
      }

      const customerNotesTriggers = data.triggers.filter(t => t.severity === 'NOTE');
      const coreSystemsTriggers = data.triggers.filter(t => t.severity === 'CORE');

      const customerNotesHtml = customerNotesTriggers.map(t => `<li class="py-1">${t.phrase}</li>`).join('');
      const coreSystemsHtml = coreSystemsTriggers.map(t => `<li class="py-1">${t.phrase}</li>`).join('');

      existingTriggersContainer.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">From Customer Notes/Interactions</h4>
            <ul class="list-disc list-inside text-gray-600">
              ${customerNotesHtml}
            </ul>
          </div>
          <div>
            <h4 class="text-md font-semibold mt-4 mb-2 text-gray-800">From Core Systems/Customer Profile</h4>
            <ul class="list-disc list-inside text-gray-600">
              ${coreSystemsHtml}
            </ul>
          </div>
        </div>
      `;
      // If requested, highlight the newly added phrase
      if (phraseToHighlight) {
        highlightApprovedPhrase(phraseToHighlight);
      }
      return data.triggers;

    } catch (err) {
      console.error('Fetch existing triggers failed', err);
      existingTriggersContainer.innerHTML = `<p class="text-red-500">Error loading triggers.</p>`;
      return [];
    }
  }

  function highlightApprovedPhrase(phrase) {
    try {
      if (!phrase || !existingTriggersContainer) return;
      const lis = existingTriggersContainer.querySelectorAll('li');
      const target = Array.from(lis).find(li => li.textContent.trim().toLowerCase() === String(phrase).trim().toLowerCase());
      if (target) {
        target.classList.add('flash-highlight');
        setTimeout(() => target.classList.remove('flash-highlight'), 1600);
      }
    } catch (e) {
      // no-op
    }
  }

  predictBtn.addEventListener('click', async () => {
    predictOutput.innerHTML = '<p class="text-gray-500">Generating predictions...</p>';
    setLoading(predictBtn, true, 'Predicting...');
    try {
      const resp = await fetch(`${apiBase}/api/predict`, { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (Array.isArray(data.triggers) && data.triggers.length > 0) {
        const triggerCards = data.triggers.map(t => {
          // Store the original trigger object for the approval payload
          const triggerData = JSON.stringify(t).replace(/'/g, "&apos;");

          const metricsHtml = [
            { label: 'Support', metric: t.support },
            { label: 'Lift', metric: t.lift },
            { label: 'Odds Ratio', metric: t.odds_ratio },
          ].map(m => `
            <div class="text-center">
              <div class="tooltip">
                <span class="text-sm text-gray-500">${m.label}</span>
                <span class="tooltip-text">${m.metric.explanation}</span>
              </div>
              <p class="text-xl font-bold text-indigo-600">${(m.label === 'Support' ? m.metric.value * 100 : m.metric.value).toFixed(1)}${m.label === 'Support' ? '%' : 'x'}</p>
            </div>`).join('');

          return `
            <div class="bg-white rounded-lg shadow-lg overflow-hidden transition-all duration-300" data-trigger='${triggerData}'>
              <div class="p-6">
                <h3 class="text-lg font-bold text-gray-900">${t.description}</h3>
                <p class="mt-2 text-sm text-gray-600">${t.narrative_explanation}</p>
                
                <div class="mt-4 p-3 bg-gray-50 rounded-md">
                  <p class="text-xs text-gray-500 font-mono">${t.example_phrases}</p>
                </div>

                <div class="mt-4 grid grid-cols-3 gap-4 border-t border-b border-gray-200 py-4">
                  ${metricsHtml}
                </div>

                <div class="mt-6 flex justify-end space-x-3">
                  <button class="disapprove py-2 px-4 text-sm font-medium text-gray-700 bg-white rounded-md border border-gray-300 hover:bg-gray-50">Reject</button>
                  <button class="approve py-2 px-4 text-sm font-medium text-white bg-indigo-600 rounded-md border border-transparent hover:bg-indigo-700">Approve</button>
                </div>
              </div>
            </div>`;
        }).join('');
        predictOutput.innerHTML = triggerCards;
        wirePredictionActions();
      } else {
        predictOutput.innerHTML = `<p class="text-gray-500 italic">No triggers were predicted.</p>`;
      }
    } catch (err) {
      console.error('Predict error', err);
      predictOutput.innerHTML = `<p class="text-red-500">Error: ${err.message}</p>`;
    } finally {
      setLoading(predictBtn, false);
    }
  });

  function deriveApprovalPayload(row) {
    try {
      const dataAttr = row.getAttribute('data-trigger');
      if (!dataAttr) return null;
      const trigger = JSON.parse(dataAttr.replace(/&apos;/g, "'"));
      
      // The approve endpoint expects a flat structure, so we create it here.
      return {
        phrase: trigger.description, // Map description to phrase
        example_phrases: trigger.example_phrases, // Added this line
        support: trigger.support.value,
        lift: trigger.lift.value,
        odds_ratio: trigger.odds_ratio.value,
        p_value: trigger.p_value,
        fdr: trigger.fdr,
      };
    } catch (e) {
      console.error("Could not derive approval payload", e);
      return null;
    }
  }

  function wirePredictionActions() {
    predictOutput.querySelectorAll('.approve').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const card = e.target.closest('[data-trigger]');
        const payload = deriveApprovalPayload(card);
        if (!payload) {
          // Use a modal or a div instead of alert
          // alert('Could not process this trigger for approval.');
          return;
        }
        btn.disabled = true;
        e.target.closest('.flex').innerHTML = '<p class="text-green-600 font-semibold">Approved</p>';
        try {
          const resp = await fetch(`${apiBase}/api/triggers/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          // Refresh and highlight the newly added trigger in the approved list
          try {
            const data = await resp.json();
            if (data && data.inserted) {
              await fetchExistingTriggers(payload.phrase);
            } else {
              await fetchExistingTriggers(payload.phrase);
            }
          } catch (_) {
            // If parsing fails, still attempt to refresh and highlight
            await fetchExistingTriggers(payload.phrase);
          }
          // Animate card away
          card.style.transform = 'scale(0.95)';
          card.style.opacity = '0';
          setTimeout(() => card.remove(), 300);
        } catch (err) {
          console.error('Approve failed', err);
          // Use a modal or a div instead of alert
          // alert(`Failed to approve trigger: ${err.message}`);
          // Restore button if failed
          e.target.closest('.flex').innerHTML = `<button class="disapprove py-2 px-4 text-sm font-medium text-gray-700 bg-white rounded-md border border-gray-300 hover:bg-gray-50">Reject</button><button class="approve py-2 px-4 text-sm font-medium text-white bg-indigo-600 rounded-md border border-transparent hover:bg-indigo-700">Approve</button>`;
        }
      });
    });

    predictOutput.querySelectorAll('.disapprove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const card = e.target.closest('[data-trigger]');
        e.target.closest('.flex').innerHTML = '<p class="text-red-600 font-semibold">Rejected</p>';
        card.style.transform = 'scale(0.95)';
        card.style.opacity = '0';
        setTimeout(() => card.remove(), 300);
      });
    });
  }

  // Workflow 1: Evaluate Customer
  evaluateForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const customerId = document.getElementById('customer-id').value;
    const note = document.getElementById('note').value;
    const evaluateBtn = document.getElementById('evaluate-btn');

    evaluateOutput.innerHTML = '';
    evaluationStatusDiv.innerHTML = '';
    evaluationResultDiv.innerHTML = '';
    setLoading(evaluateBtn, true, 'Evaluating...');

    try {
      const resp = await fetch(`${apiBase}/api/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_id: customerId, note: note })
      });

      if (!resp.ok) {
        const errorData = await resp.json();
        throw new Error(errorData.detail || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      evaluateOutput.innerHTML = `<p class="text-green-600">Evaluation triggered for Customer ID: ${data.customer_id}</p>`;
      
      if (data.instance_id && data.status_query_url) {
        pollEvaluationStatus(data.instance_id, data.status_query_url);
      } else {
        evaluationStatusDiv.innerHTML = `<p class="text-yellow-600">Evaluation started, but no status URL provided.</p>`;
      }

    } catch (err) {
      console.error('Evaluation error', err);
      evaluateOutput.innerHTML = `<p class="text-red-500">Error: ${err.message}</p>`;
    } finally {
      setLoading(evaluateBtn, false);
    }
  });

  async function pollEvaluationStatus(instanceId, statusQueryUrl) {
    let pollInterval;
    const poll = async () => {
      try {
        const resp = await fetch(`${apiBase}${statusQueryUrl}`);
        if (!resp.ok) {
          const errorData = await resp.json();
          throw new Error(errorData.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();

        evaluationStatusDiv.innerHTML = `
          <p>Status: <strong>${data.runtime_status}</strong></p>
          <p>Progress: ${data.progress !== null ? data.progress + '%' : 'N/A'}</p>
          ${data.status ? `<p>Details: ${data.status}</p>` : ''}
        `;

        if (data.runtime_status === 'Completed' || data.runtime_status === 'Failed' || data.runtime_status === 'Terminated') {
          clearInterval(pollInterval);
          if (data.result) {
            evaluationResultDiv.innerHTML = renderEvaluationResult(data.result);
          } else if (data.status) {
            evaluationResultDiv.innerHTML = `<p class="text-red-500">Evaluation ${data.runtime_status}: ${data.status}</p>`;
          } else {
            evaluationResultDiv.innerHTML = `<p class="text-red-500">Evaluation ${data.runtime_status}.</p>`;
          }
        }
      } catch (err) {
        console.error('Polling error', err);
        clearInterval(pollInterval);
        evaluationStatusDiv.innerHTML = `<p class="text-red-500">Error polling status: ${err.message}</p>`;
      }
    };

    pollInterval = setInterval(poll, 4000); // Poll every 4 seconds
    poll(); // Initial call
  }

  // ---- Evaluation Result Rendering ----
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function iconCheck(classes = 'h-5 w-5 text-green-600') {
    return `<svg class="${classes}" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 00-1.414 0L8 12.586 4.707 9.293A1 1 0 103.293 10.707l4 4a1 1 0 001.414 0l8-8a1 1 0 000-1.414z" clip-rule="evenodd"/></svg>`;
  }

  function iconCross(classes = 'h-5 w-5 text-red-600') {
    return `<svg class="${classes}" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-10.293a1 1 0 00-1.414-1.414L10 8.586 7.707 6.293a1 1 0 10-1.414 1.414L8.586 10l-2.293 2.293a1 1 0 101.414 1.414L10 11.414l2.293 2.293a1 1 0 001.414-1.414L11.414 10l2.293-2.293z" clip-rule="evenodd"/></svg>`;
  }

  function iconSparkle(classes = 'h-5 w-5 text-indigo-600') {
    // Multi-sparkles icon (Heroicons-inspired 24/solid sparkles)
    return `
      <svg class="${classes}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M14.73 3.21a.75.75 0 0 1 1.34 0l.788 1.593c.23.463.603.836 1.066 1.066l1.593.788a.75.75 0 0 1 0 1.34l-1.593.788c-.463.23-.836.603-1.066 1.066l-.788 1.593a.75.75 0 0 1-1.34 0l-.788-1.593a2.75 2.75 0 0 0-1.066-1.066l-1.593-.788a.75.75 0 0 1 0-1.34l1.593-.788c.463-.23.836-.603 1.066-1.066l.788-1.593Zm-9 7a.75.75 0 0 1 1.34 0l.528 1.064c.155.312.403.56.715.715l1.064.528a.75.75 0 0 1 0 1.34l-1.064.528c-.312.155-.56.403-.715.715l-.528 1.064a.75.75 0 0 1-1.34 0l-.528-1.064a1.75 1.75 0 0 0-.715-.715L2.064 14a.75.75 0 0 1 0-1.34l1.064-.528c.312-.155.56-.403.715-.715l.528-1.064Zm12.22 5.677a.75.75 0 0 0-1.44 0 3.001 3.001 0 0 1-2.227 2.226.75.75 0 0 0 0 1.441 3.001 3.001 0 0 1 2.226 2.227.75.75 0 0 0 1.441 0 3.001 3.001 0 0 1 2.227-2.227.75.75 0 0 0 0-1.44 3.001 3.001 0 0 1-2.227-2.227Z" />
      </svg>`;
  }

  function listItem(status, text, subtext = '') {
    const icon = status ? iconCheck() : iconCross();
    return `
      <li class="flex items-start gap-2 py-1">
        <span class="mt-0.5">${icon}</span>
        <div>
          <p class="text-sm text-gray-800">${escapeHtml(text)}</p>
          ${subtext ? `<p class="text-xs text-gray-500">${escapeHtml(subtext)}</p>` : ''}
        </div>
      </li>`;
  }

  function renderEvaluationResult(result) {
    try {
      const ruleHits = Array.isArray(result.rule_hits_json) ? result.rule_hits_json : [];
      const snapshot = result.structured_snapshot_json || {};

      // Customer Notes/Interactions list
      const notesList = ruleHits.length
        ? ruleHits.map(r => listItem(!!r.hit, r.description || r.rule_id || 'Rule', r.evidence_text || r.explanation || '')).join('')
        : '<li class="text-sm text-gray-500 italic">No rule hits.</li>';

      // Core Systems checks
      const tenure = Number(snapshot.loan_tenure ?? snapshot.remaining_years);
      const tenureKnown = Number.isFinite(tenure);
      const tenureOk = tenureKnown && tenure >= 1 && tenure <= 6;

      const brokerOk = !!snapshot.is_broker_originated;

      const advRate = Number(snapshot.advertised_rate);
      const intRate = Number(snapshot.interest_rate);
      const rateOk = Number.isFinite(intRate) && Number.isFinite(advRate) && ((intRate - advRate) > 0.5);

      const remainingYears = Number(snapshot.remaining_years);
      const ioEndingOk = Number.isFinite(remainingYears) && (remainingYears < 5);

      const coreList = [
        listItem(tenureKnown ? tenureOk : false, 'Loan tenure 1–6 years', tenureKnown ? `Loan Tenure: ${tenure}` : 'Loan tenure not provided'),
        listItem(brokerOk, 'Broker originated loan'),
        listItem(rateOk, 'Interest rate is 0.5% higher than advertised rate', (Number.isFinite(intRate) && Number.isFinite(advRate)) ? `Interest rate: ${intRate}%, Advertised Rate: ${advRate}%` : 'Rate data incomplete'),
        listItem(ioEndingOk, 'Interest-only loan term coming to an end', Number.isFinite(remainingYears) ? `Remaining Years: ${remainingYears}` : 'Remaining years not provided'),
      ].join('');

      // Recommended Action
      const shouldEmit = !!result.should_emit;
      const explanationBullets = typeof result.explanation_text === 'string'
        ? result.explanation_text.split('|').map(s => s.trim()).filter(Boolean)
        : [];
      const explanationListHtml = explanationBullets.length
        ? `<ul class="list-disc list-inside mt-2 text-sm text-gray-700">${explanationBullets.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
        : '';

      const scoreExplanationHtml = `
        <div class="mt-4 text-xs text-gray-600">
          <details>
            <summary class="cursor-pointer font-medium">How to interpret the score</summary>
            <div class="mt-2 space-y-2">
              <p>The score is a "risk level" for a customer. The higher the score, the more signals the customer is giving that they might be looking to leave or refinance.</p>
              <dl>
                <dt class="font-semibold">High Score (e.g., &gt; 0.8)</dt>
                <dd class="pl-4 mb-2">A high-priority customer. The retention team should contact them immediately.</dd>
                <dt class="font-semibold">Medium Score (e.g., 0.5 - 0.8)</dt>
                <dd class="pl-4 mb-2">A potential risk. Keep an eye on this customer and perhaps reach out proactively.</dd>
                <dt class="font-semibold">Low Score (e.g., &lt; 0.5)</dt>
                <dd class="pl-4">A low-priority customer for retention efforts.</dd>
              </dl>
            </div>
          </details>
        </div>
      `;

      const actionHtml = shouldEmit ? `
        <div class="mt-6 border rounded-lg p-4 bg-green-50 border-green-200">
          <h4 class="text-md font-semibold text-green-800">Lead Card</h4>
          <p class="mt-1 text-sm text-gray-800"><span class="font-medium">Score:</span> ${typeof result.score === 'number' ? result.score.toFixed(2) : escapeHtml(result.score)}</p>
          ${explanationListHtml}
          ${scoreExplanationHtml}
        </div>
      ` : '';

      return `
        <section class="mt-6">
          <div class="flex items-center gap-2">
            ${iconSparkle('h-5 w-5 text-indigo-600')}
            <h3 class="text-lg font-semibold text-gray-900">AI analysis</h3>
          </div>

          <div class="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="bg-white border rounded-lg p-4 shadow-sm">
              <h4 class="text-md font-semibold text-gray-800 mb-2">From Customer Notes/Interactions</h4>
              <ul class="list-none">${notesList}</ul>
            </div>
            <div class="bg-white border rounded-lg p-4 shadow-sm">
              <h4 class="text-md font-semibold text-gray-800 mb-2">From Core Systems/Customer Profile</h4>
              <ul class="list-none">${coreList}</ul>
            </div>
          </div>

          ${actionHtml}
        </section>
      `;
    } catch (e) {
      console.error('Render evaluation result failed', e);
      return `
        <h4 class="text-md font-semibold mt-4">Evaluation Result (raw)</h4>
        <pre class="bg-gray-100 p-3 rounded-md text-sm overflow-x-auto">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
      `;
    }
  }

  // Initial load
  fetchExistingTriggers();
});
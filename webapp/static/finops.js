document.addEventListener('DOMContentLoaded', () => {
  // Year footer
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Utility to format deltas
  function formatDelta(value, unit = '') {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value}${unit} from last month`;
  }

  function randomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }

  function randomFloat(min, max, decimals = 1) {
    const val = Math.random() * (max - min) + min;
    return parseFloat(val.toFixed(decimals));
  }

  // Assumptions for cost calculations
  const CUSTOMERS_PER_MONTH = 164765;
  const COST_PER_CUSTOMER = 0.09; // $0.09 per customer

  // Business performance baselines (monthly)
  const NOTES_PER_MONTH = 164_765;
  // Conversion assumptions (as requested)
  const LEAD_RATE = 0.20;       // 20% of notes become leads
  const CALL_RATE = 0.75;       // 75% of leads receive calls
  const RETENTION_RATE = 0.40;  // 40% of calls retain customers
  const LOSS_RATE = 0.12;       // 12% of calls still result in loss

  const computedLeads = Math.round(NOTES_PER_MONTH * LEAD_RATE);
  const computedCalls = Math.round(computedLeads * CALL_RATE);
  const computedLost = Math.round(computedCalls * LOSS_RATE);
  // Ensure retained + lost == calls by using remainder for retained
  const computedRetained = Math.max(0, computedCalls - computedLost);

  // Synthetic metrics generator
  const metrics = {
    // Section 1
    leadScoreDistribution: {
      value: `72% confidence`,
      delta: `+3% from last month`
    },
    accuracy: {
      value: `91.2%`,
      delta: `+0.6% from last month`
    },
    ruleHitFrequency: {
      value: `320 hits/week`,
      delta: `+25 from last month`
    },

    // Section 2
    guardrailActivationCount: {
      value: `84 activations`,
      delta: `-6 from last month`
    },
    piiScrubbingCount: {
      value: `182 items scrubbed`,
      delta: `+12 from last month`
    },
    ruleFallbackEvents: {
      value: `3 events`,
      delta: `0 from last month`
    },

    // Section 3
    tokenUsage: {
      value: `150k tokens`,
      delta: `-10 from last month`
    },
    e2eLatency: {
      value: `20–30 sec`,
      delta: `+1 sec from last month`
    },
    activityLatency: {
      value: `1.2 sec (slowest step)`,
      delta: `-0.2 sec from last month`
    },
    errorRate: {
      value: `1.1%`,
      delta: `-0.1% from last month`
    },
    costPerCustomer: {
      value: `${COST_PER_CUSTOMER.toFixed(2)}`,
      delta: `+$0.00 from last month`
    },
    monthlyCost: {
      value: `${(CUSTOMERS_PER_MONTH * COST_PER_CUSTOMER).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      delta: `+$5 from last month`
    },

    // Business performance
    bpNotes: {
      value: `${NOTES_PER_MONTH.toLocaleString()}`,
      delta: `+2,340 from last month`
    },
    bpLeads: {
      value: `${computedLeads.toLocaleString()}`,
      delta: `+320 from last month`
    },
    bpCalls: {
      value: `${computedCalls.toLocaleString()}`,
      delta: `+240 from last month`
    },
    bpRetained: {
      value: `${computedRetained.toLocaleString()}`,
      delta: `+120 from last month`
    },
    bpLost: {
      value: `${computedLost.toLocaleString()}`,
      delta: `-15 from last month`
    },
  };

  // Bind to DOM
  const map = [
    ['lead-score-dist', 'leadScoreDistribution'],
    ['lead-score-dist-delta', 'leadScoreDistribution', 'delta'],
    ['rule-hit-frequency', 'ruleHitFrequency'],
    ['rule-hit-frequency-delta', 'ruleHitFrequency', 'delta'],

  ['accuracy', 'accuracy'],
  ['accuracy-delta', 'accuracy', 'delta'],

    ['guardrail-activation-count', 'guardrailActivationCount'],
    ['guardrail-activation-count-delta', 'guardrailActivationCount', 'delta'],
    ['pii-scrubbing-count', 'piiScrubbingCount'],
    ['pii-scrubbing-count-delta', 'piiScrubbingCount', 'delta'],
    ['rule-fallback-events', 'ruleFallbackEvents'],
    ['rule-fallback-events-delta', 'ruleFallbackEvents', 'delta'],

    ['token-usage', 'tokenUsage'],
    ['token-usage-delta', 'tokenUsage', 'delta'],
    ['e2e-latency', 'e2eLatency'],
    ['e2e-latency-delta', 'e2eLatency', 'delta'],
    ['activity-latency', 'activityLatency'],
    ['activity-latency-delta', 'activityLatency', 'delta'],
    ['error-rate', 'errorRate'],
    ['error-rate-delta', 'errorRate', 'delta'],

    ['cost-per-customer', 'costPerCustomer'],
    ['cost-per-customer-delta', 'costPerCustomer', 'delta'],
    ['monthly-cost', 'monthlyCost'],
    ['monthly-cost-delta', 'monthlyCost', 'delta'],

    ['bp-notes-generated', 'bpNotes'],
    ['bp-notes-generated-delta', 'bpNotes', 'delta'],
    ['bp-leads-generated', 'bpLeads'],
    ['bp-leads-generated-delta', 'bpLeads', 'delta'],
    ['bp-calls-made', 'bpCalls'],
    ['bp-calls-made-delta', 'bpCalls', 'delta'],
    ['bp-customers-retained', 'bpRetained'],
    ['bp-customers-retained-delta', 'bpRetained', 'delta'],
    ['bp-customers-lost', 'bpLost'],
    ['bp-customers-lost-delta', 'bpLost', 'delta'],
  ];

  for (const [id, key, field] of map) {
    const el = document.getElementById(id);
    if (!el) continue;
    const v = field ? metrics[key][field] : metrics[key].value;
    el.textContent = v;
  }

  // Draw a bell curve for confidence score distribution with peak marker
  const canvas = document.getElementById('lead-score-curve');
  if (canvas && canvas.getContext) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Layout paddings
    const padLeft = 14;
    const padRight = 12;
    const padBottom = 22;
    const padTop = 18;
    const plotW = w - padLeft - padRight;
    const baselineY = h - padBottom;

    // Axes (baseline)
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, baselineY);
    ctx.lineTo(w - padRight, baselineY);
    ctx.stroke();

    // Normal curve params
    const mu = 0.7; // mean (peak towards right)
    const sigma = 0.12; // std dev
    const yMax = 1 / (sigma * Math.sqrt(2 * Math.PI));
    // Dynamic scale so the peak fits within the canvas with top padding
    const maxDrawableHeight = baselineY - padTop;
    const scale = Math.max(1, maxDrawableHeight / yMax);

    // Draw curve
    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i <= plotW; i++) {
      const x = i / plotW; // 0..1
      const y = (1 / (sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * Math.pow((x - mu) / sigma, 2));
      const xp = padLeft + i;
      const yp = baselineY - y * scale;
      if (i === 0) ctx.moveTo(xp, yp); else ctx.lineTo(xp, yp);
    }
    ctx.stroke();

    // Peak marker (dot + dashed guide + label)
    const xPeak = padLeft + mu * plotW;
    const yPeak = baselineY - yMax * scale;

    // Dashed guideline
    ctx.save();
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = '#9ca3af';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(xPeak, baselineY);
    ctx.lineTo(xPeak, yPeak);
    ctx.stroke();
    ctx.restore();

    // Peak dot
    ctx.fillStyle = '#ef4444'; // red accent
    ctx.beginPath();
    ctx.arc(xPeak, yPeak, 3, 0, Math.PI * 2);
    ctx.fill();

    // Label
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px sans-serif';
    ctx.fillText('Peak', Math.min(w - 34, xPeak + 6), Math.max(10, yPeak - 6));

    // Axis labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px sans-serif';
    ctx.fillText('Low', padLeft, h - 6);
    ctx.fillText('High', w - padRight - 26, h - 6);
  }

  // Populate Top 3 Rules list from Approved Triggers
  async function loadTopRules() {
    try {
      const resp = await fetch('/api/triggers');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const listEl = document.getElementById('top-rules-list');
      if (!listEl) return;
      const triggers = Array.isArray(data.triggers) ? data.triggers : [];
      // Take top 3 by support/lift if available; fallback to first 3
      const scored = triggers.map(t => ({
        phrase: t.phrase,
        score: (Number(t.support) || 0) * 0.6 + (Number(t.lift) || 0) * 0.4
      }));
      scored.sort((a, b) => b.score - a.score);
      const top3 = (scored.length ? scored.slice(0, 3) : triggers.slice(0, 3).map(t => ({ phrase: t.phrase, score: 0 })));

      // Parse total hits/week from headline and allocate ~65% across top 3 based on weights
      const totalEl = document.getElementById('rule-hit-frequency');
      const totalHitsHeadline = totalEl && totalEl.textContent ? parseInt((totalEl.textContent || '').replace(/[^0-9]/g, ''), 10) : 0;
  const totalHits = Number.isFinite(totalHitsHeadline) && totalHitsHeadline > 0 ? totalHitsHeadline : 300;
      const topShare = 0.65; // assume top 3 rules account for ~65% of all hits
      const allocTotal = Math.max(1, Math.round(totalHits * topShare));

      const weights = top3.map(r => (r.score && r.score > 0 ? r.score : 1));
      const weightSum = weights.reduce((a, b) => a + b, 0) || 1;
      const counts = weights.map((w, i) => (i < weights.length - 1 ? Math.max(0, Math.round((w / weightSum) * allocTotal)) : 0));
      // Adjust remainder to last item so sum matches allocTotal
      const remainder = allocTotal - counts.slice(0, -1).reduce((a, b) => a + b, 0);
      counts[counts.length - 1] = Math.max(0, remainder);

      listEl.innerHTML = top3
        .map((r, idx) => `
          <div class="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
            <div class="text-sm text-gray-800 truncate pr-3">
              <span class="font-medium">${r.phrase}</span>
            </div>
            <span class="ml-3 inline-flex items-center rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-700">${counts[idx]}/wk</span>
          </div>
        `)
        .join('');
    } catch (e) {
      // Fallback to synthetic
      const listEl = document.getElementById('top-rules-list');
      if (listEl) {
        const totalEl = document.getElementById('rule-hit-frequency');
        const totalHitsHeadline = totalEl && totalEl.textContent ? parseInt((totalEl.textContent || '').replace(/[^0-9]/g, ''), 10) : 0;
  const totalHits = Number.isFinite(totalHitsHeadline) && totalHitsHeadline > 0 ? totalHitsHeadline : 300;
        const topShare = 0.65;
        const allocTotal = Math.max(1, Math.round(totalHits * topShare));
        const fallbackWeights = [0.5, 0.3, 0.2];
        const baseCounts = fallbackWeights.map((w, i) => (i < 2 ? Math.round(w * allocTotal) : 0));
        baseCounts[2] = Math.max(0, allocTotal - baseCounts[0] - baseCounts[1]);

        const phrases = [
          'Rate higher than competitor',
          'Account closure intent',
          'Interest-only term ending'
        ];
        listEl.innerHTML = phrases
          .map((x, i) => `
            <div class="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
              <div class="text-sm text-gray-800 truncate pr-3">
                <span class="font-medium">${x}</span>
              </div>
              <span class="ml-3 inline-flex items-center rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-700">${baseCounts[i]}/wk</span>
            </div>
          `)
          .join('');
      }
    }
  }
  loadTopRules();
});
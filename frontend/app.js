const healthBadge = document.getElementById('healthBadge');
const singleDocRunBtn = document.getElementById('singleDocRunBtn');
const multiDocRunBtn = document.getElementById('multiDocRunBtn');

const singleDocStatus = document.getElementById('singleDocStatus');
const multiDocStatus = document.getElementById('multiDocStatus');
const resultSummary = document.getElementById('resultSummary');
const resultGrid = document.getElementById('resultGrid');
const topline = document.getElementById('topline');
const signals = document.getElementById('signals');
const compliance = document.getElementById('compliance');
const jsonOutput = document.getElementById('jsonOutput');
const compareResult = document.getElementById('compareResult');
const multiJsonCard = document.getElementById('multiJsonCard');
const multiJsonOutput = document.getElementById('multiJsonOutput');
const readiness = document.getElementById('readiness');
const consoleStatusChip = document.getElementById('consoleStatusChip');
const copyReportBtn = document.getElementById('copyReportBtn');
const downloadReportBtn = document.getElementById('downloadReportBtn');
const metricMode = document.getElementById('metricMode');
const metricRisk = document.getElementById('metricRisk');
const metricFields = document.getElementById('metricFields');
const metricFlags = document.getElementById('metricFlags');
const singleDocTab = document.getElementById('singleDocTab');
const multiDocTab = document.getElementById('multiDocTab');
const singleDocPanel = document.getElementById('singleDocPanel');
const multiDocPanel = document.getElementById('multiDocPanel');
const singleDocFile = document.getElementById('singleDocFile');
const multiPrimaryFile = document.getElementById('multiPrimaryFile');
const multiSecondaryFile = document.getElementById('multiSecondaryFile');
const singleDocPreview = document.getElementById('singleDocPreview');
const singlePreviewTitle = document.getElementById('singlePreviewTitle');
const multiPrimaryPreview = document.getElementById('multiPrimaryPreview');
const multiPrimaryPreviewTitle = document.getElementById('multiPrimaryPreviewTitle');
const multiSecondaryPreview = document.getElementById('multiSecondaryPreview');
const multiSecondaryPreviewTitle = document.getElementById('multiSecondaryPreviewTitle');
const accessibilityToggle = document.getElementById('accessibilityToggle');
const accessibilityPanel = document.getElementById('accessibilityPanel');
const toggleLargeText = document.getElementById('toggleLargeText');
const toggleHighContrast = document.getElementById('toggleHighContrast');
const toggleReduceMotion = document.getElementById('toggleReduceMotion');
const toggleColorBlindPalette = document.getElementById('toggleColorBlindPalette');

const REQUIRED_JSON_FIELDS = [
  'first_name',
  'last_name',
  'dob',
  'id_number',
  'expiration',
  'address',
  'license_class',
  'issuing_state',
];

const ACCESSIBILITY_STORAGE_KEY = 'notaryeveryday-accessibility';
const ACCESSIBILITY_CLASS_MAP = {
  largeText: 'a11y-large-text',
  highContrast: 'a11y-high-contrast',
  reduceMotion: 'a11y-reduce-motion',
  colorBlindPalette: 'a11y-color-blind',
};

let latestReport = null;
const previewUrls = new Map();

async function loadHealth() {
  try {
    const response = await fetch('/api/health');
    const data = await response.json();
    healthBadge.textContent = `${data.status.toUpperCase()} · ${data.version}`;
  } catch (error) {
    healthBadge.textContent = 'API offline';
  }
}

function badge(text, cls) {
  return `<span class="pill ${cls}">${text}</span>`;
}

function escapeHtml(text) {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function buildRequiredJson(parsedDocument) {
  const result = {};
  for (const key of REQUIRED_JSON_FIELDS) {
    result[key] = parsedDocument?.fields?.[key]?.value ?? null;
  }
  return result;
}

function buildComparisonJson(data) {
  return {
    verdict: data.verdict,
    overall_match_score: data.overall_match_score,
    recommendation: data.recommendation,
    comparisons: data.comparisons || [],
    id_document: data.id_document || {},
    other_document: data.other_document || {},
    compliance_flags: data.compliance_flags || [],
  };
}

function countCapturedFields(payload) {
  return Object.values(payload || {}).filter((value) => value !== null && value !== '').length;
}

function formatTimestamp(date = new Date()) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function setConsoleStatus(text) {
  consoleStatusChip.textContent = text;
}

function determineReadiness(labelOrVerdict, flagCount, highSeverityCount) {
  const normalized = String(labelOrVerdict || '').toLowerCase();
  if (normalized.includes('mismatch') || normalized.includes('suspicious') || normalized.includes('high') || highSeverityCount > 0) {
    return {
      title: 'Stop Packet',
      tone: 'fail',
      body: 'Material risk indicators were found. Pause automatic approval and require manual notary review.',
    };
  }

  if (flagCount > 0 || normalized.includes('medium') || normalized.includes('warning')) {
    return {
      title: 'Review Required',
      tone: 'warning',
      body: 'The packet is usable, but a notary or closing specialist should review surfaced flags before proceeding.',
    };
  }

  return {
    title: 'Ready To Proceed',
    tone: 'safe',
    body: 'No blocking issues surfaced in this run. The packet looks operationally ready for the next workflow step.',
  };
}

function renderReadinessCard(readinessState, supportingLine) {
  readiness.innerHTML = `
    <div class="readiness-card ${readinessState.tone}">
      ${badge(readinessState.title.toUpperCase(), readinessState.tone)}
      <p>${readinessState.body}</p>
      <p class="muted">${supportingLine}</p>
    </div>
  `;
}

function updateInsights({ mode, risk, fieldsCaptured, totalFields, criticalFlags }) {
  metricMode.textContent = mode;
  metricRisk.textContent = risk;
  metricFields.textContent = `${fieldsCaptured} / ${totalFields}`;
  metricFlags.textContent = String(criticalFlags);
}

function revokePreview(targetId) {
  const url = previewUrls.get(targetId);
  if (url) {
    URL.revokeObjectURL(url);
    previewUrls.delete(targetId);
  }
}

function renderFilePreview(file, surface, titleElement, emptyText) {
  revokePreview(surface.id);

  if (!file) {
    titleElement.textContent = 'No file selected';
    surface.className = 'preview-surface empty-preview';
    surface.textContent = emptyText;
    return;
  }

  titleElement.textContent = file.name;

  if ((file.type || '').startsWith('image/')) {
    const url = URL.createObjectURL(file);
    previewUrls.set(surface.id, url);
    surface.className = 'preview-surface image-preview';
    surface.innerHTML = `<img src="${url}" alt="${escapeHtml(file.name)} preview" />`;
    return;
  }

  const extension = file.name.includes('.') ? file.name.split('.').pop().toUpperCase() : 'FILE';
  surface.className = 'preview-surface file-preview';
  surface.innerHTML = `
    <div class="file-preview-glyph">${escapeHtml(extension)}</div>
    <div class="file-preview-meta">
      <strong>${escapeHtml(file.name)}</strong>
      <p>${escapeHtml(file.type || 'Document file')}</p>
      <p>${Math.max(1, Math.round(file.size / 1024))} KB</p>
    </div>
  `;
}

function buildSingleDocReport(data, structuredJson, readinessState) {
  const signalsList = (data.fraud_signals || []).map((item) => `- ${item.name} (${item.level}): ${item.explanation}`).join('\n') || '- None';
  const complianceList = (data.compliance_flags || []).map((item) => `- ${item.rule} (${item.severity}): ${item.message}${item.citation ? ` [${item.citation}]` : ''}`).join('\n') || '- None';
  return [
    'NOTARY EVERYDAY · VERIFICATION REPORT',
    `Mode: Single Doc`,
    `Generated: ${formatTimestamp()}`,
    `Authenticity: ${data.authenticity_label}`,
    `Risk: ${data.final_risk}`,
    `Confidence: ${(data.authenticity_confidence * 100).toFixed(1)}%`,
    `Packet Readiness: ${readinessState.title}`,
    '',
    `Summary: ${data.summary}`,
    `Recommendation: ${data.recommendation}`,
    '',
    'Fraud Signals',
    signalsList,
    '',
    'Compliance Flags',
    complianceList,
    '',
    'Structured JSON',
    JSON.stringify(structuredJson, null, 2),
  ].join('\n');
}

function buildMultiDocReport(data, readinessState) {
  const comparisons = (data.comparisons || []).map((item) => `- ${item.field}: ${item.flag} (${(item.confidence * 100).toFixed(1)}%) | ID="${item.id_value || '-'}" | Other="${item.doc_value || '-'}"`).join('\n');
  const complianceList = (data.compliance_flags || []).map((item) => `- ${item.rule} (${item.severity}): ${item.message}${item.citation ? ` [${item.citation}]` : ''}`).join('\n') || '- None';
  return [
    'NOTARY EVERYDAY · VERIFICATION REPORT',
    `Mode: Multiple Doc`,
    `Generated: ${formatTimestamp()}`,
    `Verdict: ${data.verdict}`,
    `Overall Match Score: ${Math.round(data.overall_match_score * 100)}%`,
    `Packet Readiness: ${readinessState.title}`,
    '',
    `Recommendation: ${data.recommendation}`,
    '',
    'Field Comparisons',
    comparisons || '- None',
    '',
    'Compliance Flags',
    complianceList,
  ].join('\n');
}

function readAccessibilitySettings() {
  try {
    return JSON.parse(localStorage.getItem(ACCESSIBILITY_STORAGE_KEY) || '{}');
  } catch (error) {
    return {};
  }
}

function writeAccessibilitySettings(settings) {
  localStorage.setItem(ACCESSIBILITY_STORAGE_KEY, JSON.stringify(settings));
}

function applyAccessibilitySettings(settings) {
  Object.entries(ACCESSIBILITY_CLASS_MAP).forEach(([key, className]) => {
    document.body.classList.toggle(className, Boolean(settings[key]));
  });

  toggleLargeText.checked = Boolean(settings.largeText);
  toggleHighContrast.checked = Boolean(settings.highContrast);
  toggleReduceMotion.checked = Boolean(settings.reduceMotion);
  toggleColorBlindPalette.checked = Boolean(settings.colorBlindPalette);
}

function updateAccessibilitySetting(key, value) {
  const nextSettings = {
    ...readAccessibilitySettings(),
    [key]: value,
  };
  writeAccessibilitySettings(nextSettings);
  applyAccessibilitySettings(nextSettings);
}

function renderSingleDocResult(data) {
  showOutputMode('single');
  resultSummary.classList.add('hidden');
  resultGrid.classList.remove('hidden');
  setConsoleStatus('Single-doc analysis complete');

  const structuredJson = buildRequiredJson(data.parsed_document);
  const capturedFields = countCapturedFields(structuredJson);
  const complianceFlags = data.compliance_flags || [];
  const fraudSignals = data.fraud_signals || [];
  const highSeverityCount = complianceFlags.filter((item) => item.severity === 'fail').length;
  const readinessState = determineReadiness(data.final_risk, complianceFlags.length, highSeverityCount);

  topline.innerHTML = `
    ${badge(data.authenticity_label.toUpperCase(), data.authenticity_label)}
    ${badge(`Risk: ${data.final_risk.toUpperCase()}`, data.final_risk)}
    <p><strong>Confidence:</strong> ${(data.authenticity_confidence * 100).toFixed(1)}%</p>
    <p><strong>Summary:</strong> ${data.summary}</p>
    <p><strong>Recommendation:</strong> ${data.recommendation}</p>
  `;

  signals.innerHTML = data.fraud_signals.length
    ? data.fraud_signals.map(item => `
      <div class="list-item">
        <h4>${item.name}</h4>
        ${badge(item.level.toUpperCase(), item.level)}
        <p>${item.explanation}</p>
        <p class="muted">Score: ${item.score}</p>
      </div>
    `).join('')
    : '<p class="muted">No major fraud signals detected.</p>';

  compliance.innerHTML = complianceFlags.length
    ? complianceFlags.map(item => `
    <div class="list-item">
      <h4>${item.rule}</h4>
      ${badge(item.severity.toUpperCase(), item.severity)}
      <p>${item.message}</p>
      <p class="muted">${escapeHtml(item.citation || 'Rule citation not available.')}</p>
    </div>
  `).join('')
    : '<p class="muted">No compliance flags detected.</p>';

  renderReadinessCard(
    readinessState,
    `${capturedFields} of ${REQUIRED_JSON_FIELDS.length} core fields were extracted from the document.`
  );
  updateInsights({
    mode: 'Single Doc',
    risk: data.final_risk.toUpperCase(),
    fieldsCaptured: capturedFields,
    totalFields: REQUIRED_JSON_FIELDS.length,
    criticalFlags: highSeverityCount + fraudSignals.filter((item) => item.level === 'high').length,
  });

  jsonOutput.textContent = JSON.stringify(structuredJson, null, 2);
  latestReport = {
    filename: 'notaryeveryday-single-doc-report.txt',
    text: buildSingleDocReport(data, structuredJson, readinessState),
  };
}

function renderMultiDocResult(data) {
  showOutputMode('multi');
  setConsoleStatus('Multi-doc comparison complete');
  const rows = data.comparisons.map(item => `
    <tr>
      <td>${escapeHtml(item.field)}</td>
      <td>${escapeHtml(item.id_value || '-')}</td>
      <td>${escapeHtml(item.doc_value || '-')}</td>
      <td>${badge(item.flag, item.flag.toLowerCase())}</td>
      <td>${(item.confidence * 100).toFixed(1)}%</td>
      <td>${escapeHtml(item.explanation || '-')}</td>
    </tr>
  `).join('');
  const complianceFlags = data.compliance_flags || [];
  const failCount = complianceFlags.filter((item) => item.severity === 'fail').length;
  const readinessState = determineReadiness(data.verdict, complianceFlags.length, failCount);
  const populatedComparisons = (data.comparisons || []).filter((item) => item.id_value || item.doc_value).length;

  const complianceHtml = complianceFlags.length
    ? `
      <div class="panel">
        <h3>Cross-Document Compliance</h3>
        ${complianceFlags.map(item => `
          <div class="list-item">
            <h4>${escapeHtml(item.rule)}</h4>
            ${badge(item.severity.toUpperCase(), item.severity)}
            <p>${escapeHtml(item.message || '-')}</p>
            <p class="muted">${escapeHtml(item.citation || 'Rule citation not available.')}</p>
          </div>
        `).join('')}
      </div>
    `
    : '';

  compareResult.innerHTML = `
    <p>${badge(data.verdict.toUpperCase(), data.verdict)} ${badge(`Score ${Math.round(data.overall_match_score * 100)}%`, data.verdict)}</p>
    <p><strong>Recommendation:</strong> ${data.recommendation}</p>
    <div class="readiness-card ${readinessState.tone}">
      ${badge(readinessState.title.toUpperCase(), readinessState.tone)}
      <p>${readinessState.body}</p>
      <p class="muted">${failCount} blocking compliance flags surfaced in this packet review.</p>
    </div>
    <table class="table">
      <thead>
        <tr>
          <th>Field</th>
          <th>ID Value</th>
          <th>Other Doc Value</th>
          <th>Status</th>
          <th>Confidence</th>
          <th>Explanation</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    ${complianceHtml}
  `;
  updateInsights({
    mode: 'Multiple Doc',
    risk: data.verdict.toUpperCase(),
    fieldsCaptured: populatedComparisons,
    totalFields: REQUIRED_JSON_FIELDS.length,
    criticalFlags: failCount,
  });
  latestReport = {
    filename: 'notaryeveryday-multi-doc-report.txt',
    text: buildMultiDocReport(data, readinessState),
  };
  multiJsonCard.classList.remove('hidden');
  multiJsonOutput.textContent = JSON.stringify(buildComparisonJson(data), null, 2);
}

async function runSingleDoc(fileSource, statusElements = []) {
  const file = fileSource.files[0];
  if (!file) {
    statusElements.forEach((element) => {
      element.textContent = 'Please choose a document first.';
    });
    return;
  }

  statusElements.forEach((element) => {
    element.textContent = 'Analyzing image...';
  });
  setConsoleStatus('Single-doc analysis in progress');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/analyze-document', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Analysis failed.');

    statusElements.forEach((element) => {
      element.textContent = 'Done.';
    });
    renderSingleDocResult(data);
  } catch (error) {
    statusElements.forEach((element) => {
      element.textContent = error.message;
    });
  }
}

async function runMultiDoc(primarySource, secondarySource, statusElements = []) {
  const primary = primarySource.files[0];
  const secondary = secondarySource.files[0];

  if (!primary || !secondary) {
    statusElements.forEach((element) => {
      element.textContent = 'Please choose both files.';
    });
    return;
  }

  statusElements.forEach((element) => {
    element.textContent = 'Comparing documents...';
  });
  setConsoleStatus('Multi-doc comparison in progress');

  const formData = new FormData();
  formData.append('primary_file', primary);
  formData.append('secondary_file', secondary);

  try {
    const response = await fetch('/api/compare-docs', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Comparison failed.');

    statusElements.forEach((element) => {
      element.textContent = 'Done.';
    });
    renderMultiDocResult(data);
  } catch (error) {
    statusElements.forEach((element) => {
      element.textContent = error.message;
    });
  }
}

function showOutputMode(mode) {
  const showSingle = mode === 'single';
  singleDocPanel.classList.toggle('hidden', !showSingle);
  multiDocPanel.classList.toggle('hidden', showSingle);
  singleDocTab.classList.toggle('active', showSingle);
  multiDocTab.classList.toggle('active', !showSingle);
  singleDocTab.setAttribute('aria-selected', String(showSingle));
  multiDocTab.setAttribute('aria-selected', String(!showSingle));
  singleDocTab.tabIndex = showSingle ? 0 : -1;
  multiDocTab.tabIndex = showSingle ? -1 : 0;
  if (showSingle) {
    multiJsonCard.classList.add('hidden');
  }
}

singleDocTab.addEventListener('click', () => showOutputMode('single'));
multiDocTab.addEventListener('click', () => showOutputMode('multi'));
singleDocTab.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowRight') {
    event.preventDefault();
    showOutputMode('multi');
    multiDocTab.focus();
  }
});
multiDocTab.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    showOutputMode('single');
    singleDocTab.focus();
  }
});

singleDocRunBtn.addEventListener('click', async () => {
  await runSingleDoc(singleDocFile, [singleDocStatus]);
});

multiDocRunBtn.addEventListener('click', async () => {
  await runMultiDoc(multiPrimaryFile, multiSecondaryFile, [multiDocStatus]);
});

singleDocFile.addEventListener('change', () => {
  renderFilePreview(
    singleDocFile.files[0],
    singleDocPreview,
    singlePreviewTitle,
    'Upload a file to see it here before running analysis.',
  );
});

multiPrimaryFile.addEventListener('change', () => {
  renderFilePreview(
    multiPrimaryFile.files[0],
    multiPrimaryPreview,
    multiPrimaryPreviewTitle,
    'Add the first document to preview it here.',
  );
});

multiSecondaryFile.addEventListener('change', () => {
  renderFilePreview(
    multiSecondaryFile.files[0],
    multiSecondaryPreview,
    multiSecondaryPreviewTitle,
    'Add the second document to preview it here.',
  );
});

copyReportBtn.addEventListener('click', async () => {
  if (!latestReport?.text) {
    setConsoleStatus('Run a verification before copying a report');
    return;
  }

  try {
    await navigator.clipboard.writeText(latestReport.text);
    setConsoleStatus('Report copied to clipboard');
  } catch (error) {
    setConsoleStatus('Clipboard copy failed');
  }
});

downloadReportBtn.addEventListener('click', () => {
  if (!latestReport?.text) {
    setConsoleStatus('Run a verification before downloading a report');
    return;
  }

  const blob = new Blob([latestReport.text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = latestReport.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setConsoleStatus('Report downloaded');
});

accessibilityToggle.addEventListener('click', () => {
  const isOpen = !accessibilityPanel.classList.contains('hidden');
  accessibilityPanel.classList.toggle('hidden', isOpen);
  accessibilityToggle.setAttribute('aria-expanded', String(!isOpen));
});

document.addEventListener('click', (event) => {
  if (!accessibilityPanel || accessibilityPanel.classList.contains('hidden')) {
    return;
  }

  if (!accessibilityPanel.contains(event.target) && !accessibilityToggle.contains(event.target)) {
    accessibilityPanel.classList.add('hidden');
    accessibilityToggle.setAttribute('aria-expanded', 'false');
  }
});

toggleLargeText.addEventListener('change', (event) => {
  updateAccessibilitySetting('largeText', event.target.checked);
});

toggleHighContrast.addEventListener('change', (event) => {
  updateAccessibilitySetting('highContrast', event.target.checked);
});

toggleReduceMotion.addEventListener('change', (event) => {
  updateAccessibilitySetting('reduceMotion', event.target.checked);
});

toggleColorBlindPalette.addEventListener('change', (event) => {
  updateAccessibilitySetting('colorBlindPalette', event.target.checked);
});

showOutputMode('single');
applyAccessibilitySettings(readAccessibilitySettings());
loadHealth();

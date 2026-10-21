const DEFAULT_SUBSCRIBED_CATEGORIES = "__DEFAULT_CATEGORIES__";

const AI_ERROR_PLACEHOLDERS = new Set([
  'summary generation failed', 'motivation analysis unavailable',
  'method extraction failed', 'result analysis unavailable',
  'conclusion extraction failed', 'processing failed',
  'this content has not passed the compliance test and has been hidden.'
]);

function hasValidAI(ai) {
  return ai && ['tldr', 'motivation', 'method', 'result', 'conclusion'].every(field =>
    typeof ai[field] === 'string' && ai[field].trim() &&
    !AI_ERROR_PLACEHOLDERS.has(ai[field].trim().toLowerCase())
  );
}

function uniquePapers(data) {
  const byId = new Map();
  const ordered = Object.values(data).flat().sort((a, b) =>
    String(b.date).localeCompare(String(a.date)) || (a.rawOrder || 0) - (b.rawOrder || 0)
  );
  ordered.forEach(paper => {
    const id = normalizePaperId(paper.id || paper.url);
    const previous = byId.get(id);
    if (!previous) {
      byId.set(id, paper);
    } else {
      const preferred = paper.aiAvailable && !previous.aiAvailable ? paper : previous;
      const categories = [...new Set([...previous.category, ...paper.category])];
      const date = previous.date < paper.date ? previous.date : paper.date;
      byId.set(id, {...preferred, date, category: categories, allCategories: categories});
    }
  });
  return [...byId.values()];
}

function papersForCategory(data, category) {
  const papers = uniquePapers(data);
  return category === 'all' ? papers : papers.filter(paper =>
    (paper.allCategories || paper.category || []).includes(category)
  );
}

function parseJsonlData(jsonlText, date) {
  const result = {};
  
  const lines = jsonlText.trim().split('\n');
  
  lines.forEach((line, rawOrder) => {
    try {
      const paper = JSON.parse(line);
      
      if (!paper.categories) {
        return;
      }
      
      let allCategories = Array.isArray(paper.categories) ? paper.categories : [paper.categories];
      
      const primaryCategory = allCategories[0];
      
      if (!result[primaryCategory]) {
        result[primaryCategory] = [];
      }
      
      const aiAvailable = Boolean(hasValidAI(paper.AI));
      const summary = aiAvailable ? paper.AI.tldr : (paper.summary || 'Abstract unavailable');
      
      result[primaryCategory].push({
        rawOrder,
        title: paper.title,
        url: paper.abs || paper.pdf || `https://arxiv.org/abs/${paper.id}`,
        authors: Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors,
        authorList: Array.isArray(paper.authors) ? paper.authors : String(paper.authors || '').split(',').map(author => author.trim()),
        category: allCategories,
        allCategories: allCategories,
        aiAvailable: aiAvailable,
        aiLanguage: paper.aiLanguage || '',
        researcherMatches: paper.researcherMatches || [],
        summary: summary,
        details: paper.summary || '',
        date: date,
        id: paper.id,
        motivation: aiAvailable ? paper.AI.motivation : '',
        method: aiAvailable ? paper.AI.method : '',
        result: aiAvailable ? paper.AI.result : '',
        conclusion: aiAvailable ? paper.AI.conclusion : '',
        code_url: paper.code_url || '',
        code_stars: paper.code_stars || 0,
        code_last_update: paper.code_last_update || ''
      });
    } catch (error) {
      console.error('解析JSON行失败:', error, line);
    }
  });
  
  return result;
}

// 获取所有类别并按偏好排序
function getAllCategories(data, subscribedCategories) {
  const papers = uniquePapers(data);
  const configured = Array.isArray(subscribedCategories) ? subscribedCategories : DEFAULT_SUBSCRIBED_CATEGORIES;
  const categories = Array.isArray(configured) ? [...new Set(configured)] : [];
  const categoryCounts = Object.fromEntries(categories.map(category => [category, 0]));
  papers.forEach(paper => {
    new Set(paper.allCategories || paper.category || []).forEach(category => {
      if (Object.hasOwn(categoryCounts, category)) categoryCounts[category]++;
    });
  });
  return {
    sortedCategories: categories,
    categoryCounts,
    totalCount: papers.length
  };
}

function normalizePaperId(value) {
  return String(value || '').replace(/^https?:\/\/(?:www\.)?arxiv\.org\/abs\//, '').replace(/v\d+$/, '');
}

function preferenceKey(name) {
  return `${DATA_CONFIG.namespace}:${name}`;
}

function readPreference(name, migrate = false) {
  try {
    const saved = localStorage.getItem(preferenceKey(name));
    if (saved !== null) return saved;
    if (migrate && ['preferredKeywords', 'preferredAuthors'].includes(name)) {
      const legacy = localStorage.getItem(name);
      if (legacy !== null) {
        const values = JSON.parse(legacy);
        if (Array.isArray(values) && values.every(value => typeof value === 'string')) {
          localStorage.setItem(preferenceKey(name), legacy);
          return legacy;
        }
      }
    }
  } catch (error) {
    console.warn('Browser preferences unavailable:', error.message);
  }
  return null;
}

function savePreference(name, value) {
  try {
    localStorage.setItem(preferenceKey(name), value);
    return true;
  } catch (error) {
    console.warn('Browser preferences unavailable:', error.message);
    return false;
  }
}

let selectedAILanguage = null;
function getPreferredLanguage() {
  if (selectedAILanguage) return selectedAILanguage;
  const saved = readPreference('aiLanguage');
  selectedAILanguage = ['English', 'Chinese'].includes(saved) ? saved : 'English';
  return selectedAILanguage;
}

function selectLanguageForDate(date, preferredLanguage = null) {
  return preferredLanguage || getPreferredLanguage();
}

function initLanguageSelector(onChange) {
  const buttons = document.querySelectorAll('[data-ai-language]');
  const refresh = () => buttons.forEach(button => {
    const active = button.dataset.aiLanguage === getPreferredLanguage();
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('active', active);
  });
  buttons.forEach(button => button.addEventListener('click', () => {
    const language = button.dataset.aiLanguage;
    if (language === getPreferredLanguage()) return;
    selectedAILanguage = language;
    savePreference('aiLanguage', language);
    refresh();
    onChange(language);
  }));
  refresh();
}

function datesFromInventory(text) {
  const dates = new Set();
  text.split('\n').forEach(line => {
    const match = line.trim().match(/(?:^|\/)(\d{4}-\d{2}-\d{2})(?:_AI_enhanced_(?:English|Chinese))?\.jsonl$/);
    if (match) dates.add(match[1]);
  });
  return [...dates].sort().reverse();
}

function readJsonlRows(text) {
  return text.split('\n').filter(line => line.trim()).map(line => JSON.parse(line));
}

function attachLanguage(rawText, enhancedText, date, language, researcherIndex = null) {
  const enhanced = new Map();
  readJsonlRows(enhancedText).forEach(row => {
    const id = normalizePaperId(row.id || row.abs);
    if (hasValidAI(row.AI)) {
      const candidates = enhanced.get(id) || [];
      candidates.push(row);
      enhanced.set(id, candidates);
    }
  });
  const rows = readJsonlRows(rawText).map(row => {
    const id = normalizePaperId(row.id || row.abs);
    const candidates = (enhanced.get(id) || []).filter(candidate => candidate.summary === row.summary);
    const first = candidates[0];
    const consistent = first && candidates.every(candidate =>
      ['tldr', 'motivation', 'method', 'result', 'conclusion'].every(field => candidate.AI[field] === first.AI[field])
    );
    return {...row, AI: consistent ? first.AI : null, aiLanguage: language,
      code_url: consistent ? first.code_url : row.code_url,
      researcherMatches: currentResearcherMatches(researcherIndex, id)};
  });
  return parseJsonlData(rows.map(row => JSON.stringify(row)).join('\n'), date);
}

function currentResearcherMatches(index, id) {
  if (!index || index.schema_version !== 1 || !DATA_CONFIG.researchersDigest ||
      index.config_digest !== DATA_CONFIG.researchersDigest) return [];
  const matches = index.papers?.[id];
  return Array.isArray(matches) ? matches.filter(match =>
    ['reliable', 'suspected'].includes(match.kind) && typeof match.author === 'string' &&
    typeof match.display_name === 'string' && typeof match.researcher_id === 'string'
  ) : [];
}

let researcherIndexPromise = null;
async function loadResearcherIndex() {
  if (!researcherIndexPromise) {
    researcherIndexPromise = fetch(DATA_CONFIG.getDataUrl('assets/researcher-index.json'), {cache: 'no-cache'})
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      }).then(index => {
        if (index.schema_version !== 1 || index.config_digest !== DATA_CONFIG.researchersDigest) {
          throw new Error('Researcher index needs a configuration refresh');
        }
        return index;
      }).catch(error => {
        console.warn('Researcher highlights unavailable:', error.message);
        const status = document.getElementById('researcherStatus');
        if (status) {
          status.hidden = false;
          status.textContent = 'Researcher highlights unavailable until the index is refreshed.';
        }
        return null;
      });
  }
  return researcherIndexPromise;
}

async function loadPaperDate(date, language) {
  const [rawResponse, enhancedText, index] = await Promise.all([
    fetch(DATA_CONFIG.getDataUrl(`data/${date}.jsonl`)),
    fetch(DATA_CONFIG.getDataUrl(`data/${date}_AI_enhanced_${language}.jsonl`))
      .then(response => response.ok ? response.text() : '')
      .catch(() => ''),
    loadResearcherIndex()
  ]);
  if (rawResponse.status === 404) return {};
  if (!rawResponse.ok) throw new Error(`Raw papers unavailable (HTTP ${rawResponse.status})`);
  const rawText = await rawResponse.text();
  try {
    return attachLanguage(rawText, enhancedText, date, language, index);
  } catch (error) {
    // Invalid AI data must not hide verified raw papers.
    if (enhancedText) return attachLanguage(rawText, '', date, language, index);
    throw error;
  }
}

async function loadPaperDates(dates, language) {
  const combined = {};
  for (const date of dates) {
    const data = await loadPaperDate(date, language);
    Object.entries(data).forEach(([category, papers]) => {
      combined[category] = (combined[category] || []).concat(papers);
    });
  }
  return combined;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character])
  );
}

function safeHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || '')) ? String(value) : '#';
}

function highlightMatches(text, terms, className = 'highlight-match') {
  const raw = String(text || '');
  const words = [...new Set(terms || [])].filter(term => typeof term === 'string' && term.length)
    .sort((a, b) => b.length - a.length);
  if (!words.length) return escapeHtml(raw);
  const pattern = words.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const regex = new RegExp(pattern, 'gi');
  let result = '';
  let start = 0;
  for (const match of raw.matchAll(regex)) {
    result += escapeHtml(raw.slice(start, match.index));
    result += `<span class="${escapeHtml(className)}">${escapeHtml(match[0])}</span>`;
    start = match.index + match[0].length;
  }
  return result + escapeHtml(raw.slice(start));
}

function formatPaperAuthors(paper, terms = [], truncated = false) {
  const authors = paper.authorList || String(paper.authors || '').split(',').map(author => author.trim());
  const matches = paper.researcherMatches || [];
  const visible = authors.map((author, index) => !truncated || authors.length <= 4 || index < 2 ||
    index >= authors.length - 2 || matches.some(match => match.author === author));
  const parts = [];
  authors.forEach((author, index) => {
    if (!visible[index]) {
      if (index === 0 || visible[index - 1]) parts.push('<span class="author-ellipsis">…</span>');
      return;
    }
    const authorMatches = matches.filter(match => match.author === author);
    const kind = authorMatches.some(match => match.kind === 'reliable') ? 'reliable' : 'suspected';
    const label = authorMatches.map(match => `${match.display_name}: ${match.kind === 'reliable' ? 'watched researcher' : 'possible name match; identity unconfirmed'}`).join('; ');
    const text = highlightMatches(author, terms, 'author-highlight');
    parts.push(authorMatches.length
      ? `<span class="author-item researcher-match researcher-${kind}" title="${escapeHtml(label)}">${text}<span class="researcher-marker" aria-label="${escapeHtml(label)}">${kind === 'reliable' ? '◆' : '?'}</span></span>`
      : `<span class="author-item">${text}</span>`);
  });
  return parts.join(', ');
}

function aiUnavailableMessage(paper) {
  return `${paper.aiLanguage || getPreferredLanguage()} AI summary unavailable; showing the original abstract.`;
}

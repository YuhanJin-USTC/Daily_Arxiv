const DEFAULT_SUBSCRIBED_CATEGORIES = "__DEFAULT_CATEGORIES__";
const SUMMARY_FIELDS = ['tldr', 'motivation', 'method', 'result', 'conclusion'];

const AI_ERROR_PLACEHOLDERS = new Set([
  'summary generation failed', 'motivation analysis unavailable',
  'method extraction failed', 'result analysis unavailable',
  'conclusion extraction failed', 'processing failed',
  'this content has not passed the compliance test and has been hidden.'
]);

function hasValidAI(ai) {
  return ai && SUMMARY_FIELDS.every(field =>
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
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(paper);
  });
  return Array.from(byId.values(), copies => {
    if (copies.length === 1) return copies[0];
    const preferred = copies.find(paper => paper.aiAvailable) || copies[0];
    const categories = [...new Set(copies.flatMap(paper => paper.category))];
    const topics = copies.filter(paper => paper.title === preferred.title &&
      paper.details === preferred.details && paper.topics).map(paper => paper.topics);
    return {...preferred, date: copies[copies.length - 1].date, category: categories,
      allCategories: categories, topics: consistentTopics(topics)};
  });
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
        topics: validatedTopics(paper.topics),
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
  return typeof value === 'string' ? value.replace(/^https?:\/\/(?:www\.)?arxiv\.org\/abs\//, '').replace(/v\d+$/, '') : '';
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

function validatedTopics(topics) {
  if (!Array.isArray(topics?.keywords) || topics.keywords.length < 3 || topics.keywords.length > 5 ||
      !Array.isArray(topics.laser_plasma_keywords) || topics.laser_plasma_keywords.length > 5) return null;
  function phrases(values) {
    const result = new Map();
    for (const value of values) {
      if (typeof value !== 'string' || /[<>\p{C}]|(?! )\p{Z}/u.test(value)) return null;
      const phrase = value.trim().replace(/ +/g, ' ');
      if (!/\p{Script=Latin}/u.test(phrase) || /(?!(?:\p{Script=Latin}|\p{Script=Greek}))\p{L}/u.test(phrase)) return null;
      const key = phrase.toLowerCase();
      if (result.has(key) || AI_ERROR_PLACEHOLDERS.has(key)) return null;
      result.set(key, phrase);
    }
    return result;
  }
  const keywords = phrases(topics.keywords);
  const subset = phrases(topics.laser_plasma_keywords);
  if (!keywords || !subset || Array.from(subset.keys()).some(key => !keywords.has(key))) return null;
  return {keywords: [...keywords.values()], laser_plasma_keywords: Array.from(subset.keys(), key => keywords.get(key))};
}

function consistentTopics(values) {
  const first = values[0];
  if (!first) return null;
  const signature = JSON.stringify(first);
  return values.every(value => JSON.stringify(value) === signature) ? first : null;
}

function indexEnhancements(text) {
  const byId = new Map();
  let rows;
  try {
    rows = readJsonlRows(text);
  } catch {
    // Each optional language file may be unavailable independently.
    return byId;
  }
  for (const row of rows) {
    if (!row || !hasValidAI(row.AI)) continue;
    const id = normalizePaperId(row.id || row.abs);
    if (!id) continue;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(row);
  }
  return byId;
}

function consistentEnhancement(candidates) {
  const first = candidates[0];
  return first && candidates.every(candidate =>
    SUMMARY_FIELDS.every(field => candidate.AI[field] === first.AI[field])
  ) ? first : null;
}

function attachLanguage(rawText, enhancedText, date, language, researcherIndex = null, englishText = '') {
  const enhanced = indexEnhancements(enhancedText);
  const english = language === 'English' ? enhanced : indexEnhancements(englishText);
  const rows = readJsonlRows(rawText).map(row => {
    const id = normalizePaperId(row.id || row.abs);
    const sameAbstract = candidate => typeof row.summary === 'string' && row.summary.trim() &&
      candidate.summary === row.summary;
    const selected = consistentEnhancement((enhanced.get(id) || []).filter(sameAbstract));
    const topicRows = (english.get(id) || []).filter(candidate => sameAbstract(candidate) &&
      typeof row.title === 'string' && row.title.trim() && candidate.title === row.title);
    const topics = consistentEnhancement(topicRows) ?
      consistentTopics(topicRows.map(candidate => validatedTopics(candidate.topics))) : null;
    return {...row, AI: selected?.AI || null, aiLanguage: language, topics,
      code_url: selected ? selected.code_url : row.code_url,
      researcherMatches: currentResearcherMatches(researcherIndex, id)};
  });
  return parseJsonlData(rows.map(row => JSON.stringify(row)).join('\n'), date);
}

function currentResearcherMatches(index, id) {
  if (!index || index.schema_version !== 1 || !DATA_CONFIG.researchersDigest ||
      index.config_digest !== DATA_CONFIG.researchersDigest) return [];
  const matches = index.papers?.[id];
  return Array.isArray(matches) ? matches.filter(match =>
    match && ['reliable', 'suspected'].includes(match.kind) && typeof match.author === 'string' &&
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

async function loadPaperDate(date, language, {includeTopics = false} = {}) {
  const fetchEnhanced = name => fetch(DATA_CONFIG.getDataUrl(`data/${date}_AI_enhanced_${name}.jsonl`))
    .then(response => response.ok ? response.text() : '').catch(() => '');
  const [rawResponse, enhancedText, englishText, index] = await Promise.all([
    fetch(DATA_CONFIG.getDataUrl(`data/${date}.jsonl`)),
    fetchEnhanced(language),
    includeTopics && language !== 'English' ? fetchEnhanced('English') : '',
    loadResearcherIndex()
  ]);
  if (rawResponse.status === 404) return {};
  if (!rawResponse.ok) throw new Error(`Raw papers unavailable (HTTP ${rawResponse.status})`);
  return attachLanguage(await rawResponse.text(), enhancedText, date, language, index, englishText);
}

async function loadPaperDates(dates, language, options) {
  const combined = {};
  for (const date of dates) {
    const data = await loadPaperDate(date, language, options);
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

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {validatedTopics, consistentTopics};
}

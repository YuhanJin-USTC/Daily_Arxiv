const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const fields = ['tldr', 'motivation', 'method', 'result', 'conclusion'];
const good = Object.fromEntries(fields.map(field => [field, `AI ${field}`]));
const topics = {keywords: ['Laser wakefields', 'Betatron radiation', 'X-ray diagnostics'], laser_plasma_keywords: ['Laser wakefields']};
const raw = (id, extra = {}) => ({id, title: `Plasma ${id}`, authors: ['First', 'Second', 'Alexey Arefiev', 'Fourth', 'Last'], summary: 'Exact original abstract', categories: ['physics.plasm-ph'], ...extra});
const jsonl = rows => rows.map(JSON.stringify).join('\n');
const match = (extra = {}) => ({researcher_id: 'arefiev', display_name: 'Alexey Arefiev', author: 'Alexey Arefiev', kind: 'reliable', basis: 'confirmed_name', ...extra});
const index = (papers = {}) => ({schema_version: 1, config_digest: 'current', papers});

function storage() {
  const values = new Map();
  return {values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value))};
}

function element() {
  const classes = new Set();
  return {innerHTML: '', textContent: '', children: [], dataset: {}, attributes: {}, style: {}, scrollTop: 0,
    classList: {add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name), toggle(name, yes) { yes ? classes.add(name) : classes.delete(name); }},
    setAttribute(name, value) {this.attributes[name] = value;}, addEventListener() {},
    appendChild(child) {this.children.push(child);}, querySelector() {return element();}};
}

function browser(options = {}) {
  const elements = new Map();
  const get = name => {if (!elements.has(name)) elements.set(name, element()); return elements.get(name);};
  const localStorage = options.storage || storage();
  const ctx = vm.createContext({console: {error() {}, warn() {}, log() {}}, localStorage, setTimeout, clearTimeout,
    document: {addEventListener() {}, getElementById: get, querySelector: get, querySelectorAll: () => [], createElement: element, body: element()},
    window: {addEventListener() {}, scrollTo() {}}, alert() {},
    DATA_CONFIG: {namespace: 'new-repo', language: 'Chinese', researchersDigest: 'current', categories: ['physics.plasm-ph'], getDataUrl: path => `/Daily_Arxiv/${path}`},
    ...options});
  vm.runInContext(read('js/papers.js'), ctx);
  return {ctx, elements, get, localStorage};
}

function rows(ctx, data) {return ctx.uniquePapers(data);}
function response(text = '', status = 200) {return {ok: status === 200, status, text: async () => text, json: async () => JSON.parse(text)};}

test('English default and saved language are shared across pages with no fallback', () => {
  const first = browser();
  assert.equal(first.ctx.getPreferredLanguage(), 'English');
  assert.equal(first.ctx.selectLanguageForDate('missing'), 'English');
  first.ctx.savePreference('aiLanguage', 'Chinese');
  const refreshed = browser({storage: first.localStorage});
  assert.equal(refreshed.ctx.getPreferredLanguage(), 'Chinese');
  assert.equal(refreshed.ctx.selectLanguageForDate('English-only-date'), 'Chinese');
});

test('only personal keyword and author keys migrate; legacy keys and credentials stay untouched', () => {
  const {ctx, localStorage} = browser();
  localStorage.setItem('preferredAuthors', '["Arefiev"]');
  localStorage.setItem('preferredKeywords', '["laser"]');
  localStorage.setItem('arxiv_auth', 'old-login');
  assert.equal(ctx.readPreference('preferredAuthors', true), '["Arefiev"]');
  assert.equal(ctx.readPreference('preferredKeywords', true), '["laser"]');
  assert.equal(ctx.readPreference('arxiv_auth', true), null);
  ctx.savePreference('preferredAuthors', '["Vieira"]');
  assert.equal(localStorage.getItem('preferredAuthors'), '["Arefiev"]');
  assert.equal(localStorage.getItem('new-repo:preferredAuthors'), '["Vieira"]');
  assert.equal(localStorage.getItem('arxiv_auth'), 'old-login');
  assert.equal(localStorage.getItem('new-repo:arxiv_auth'), null);
});

test('storage blocking does not prevent English reading', () => {
  const {ctx} = browser({localStorage: {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}}});
  assert.equal(ctx.getPreferredLanguage(), 'English');
  assert.equal(ctx.savePreference('aiLanguage', 'Chinese'), false);
});

test('raw union controls papers and metadata; selected AI joins normalized IDs and exact abstracts', () => {
  const {ctx} = browser();
  const data = ctx.attachLanguage(jsonl([raw('2610.00001'), raw('2610.00002')]),
    jsonl([raw('2610.00001v2', {title: 'stale title', authors: ['stale author'], AI: good}), raw('extra', {AI: good})]),
    '2026-10-20', 'Chinese', index({'2610.00001': [match()]}));
  const papers = rows(ctx, data);
  assert.equal(papers.length, 2);
  assert.equal(papers[0].summary, 'AI tldr');
  assert.equal(papers[0].title, 'Plasma 2610.00001');
  assert.match(papers[0].authors, /Alexey Arefiev/);
  assert.equal(papers[0].aiLanguage, 'Chinese');
  assert.equal(papers[0].researcherMatches.length, 1);
  assert.equal(papers[1].summary, 'Exact original abstract');
  assert.equal(papers[1].aiAvailable, false);
  assert.match(ctx.aiUnavailableMessage(papers[1]), /Chinese.*original abstract/);
});

test('wrong abstract, partial AI and conflicting AI remain unavailable', () => {
  const {ctx} = browser();
  for (const enhanced of [
    [raw('one', {summary: 'Exact original abstract ', AI: good})],
    [raw('one', {AI: {...good, result: ''}})],
    [raw('one', {AI: good}), raw('one', {AI: {...good, tldr: 'Conflicting answer'}})]
  ]) {
    const paper = rows(ctx, ctx.attachLanguage(jsonl([raw('one')]), jsonl(enhanced), '2026-10-20', 'English'))[0];
    assert.equal(paper.aiAvailable, false);
    assert.equal(paper.summary, 'Exact original abstract');
  }
});

test('both languages use the English keywords bound to the raw title and abstract', () => {
  const {ctx} = browser();
  const source = raw('one');
  const english = {...source, id: 'https://arxiv.org/abs/onev2', AI: good, topics};
  const chinese = {...source, AI: {...good, tldr: '中文摘要'}, topics: {...topics, laser_plasma_keywords: []}};
  const join = (language, selected, englishRows = []) => rows(ctx, ctx.attachLanguage(jsonl([source]),
    jsonl(selected), '2026-10-20', language, null, jsonl(englishRows)))[0];
  const en = join('English', [english, english]);
  const zh = join('Chinese', [chinese], [english]);
  const pending = join('Chinese', [], [english]);
  assert.deepEqual(JSON.parse(JSON.stringify(en.topics)), topics);
  assert.deepEqual(zh.topics, en.topics);
  assert.deepEqual(pending.topics, en.topics);
  assert.equal(zh.summary, '中文摘要');
  assert.equal(pending.aiAvailable, false);
  assert.equal(pending.summary, source.summary);

  for (const englishRows of [[], [{...english, id: 'two'}], [{...english, title: 'Different title'}],
    [{...english, summary: source.summary + ' '}], [{...english, AI: {...good, result: ''}}],
    [english, {...english, AI: {...good, tldr: 'Contradiction'}}],
    [english, {...english, topics: {...topics, laser_plasma_keywords: []}}]]) {
    const paper = join('Chinese', [chinese], englishRows);
    assert.equal(paper.topics, null);
    assert.equal(paper.summary, '中文摘要');
  }
});

test('optional bad labels leave healthy English fields visible; valid subsets use keyword spelling', () => {
  const {ctx} = browser();
  const source = raw('one');
  const join = input => rows(ctx, ctx.attachLanguage(jsonl([source]),
    jsonl([{...source, topics: input, AI: good}]), '2026-10-20', 'English'))[0];
  for (const invalid of [null, {}, {...topics, keywords: ['Only one']},
    {...topics, keywords: ['Only', 'TWO', 'two']}, {...topics, keywords: ['Laser', '电子动力学', 'Waves']},
    {...topics, keywords: ['Laser', '<img src=x>', 'Waves']}, {...topics, laser_plasma_keywords: ['Missing']},
    {...topics, keywords: ['Valid', 'Terms', 'Processing failed']},
    {...topics, laser_plasma_keywords: ['Laser wakefields', 'LASER WAKEFIELDS']}]) {
    const paper = join(invalid);
    assert.equal(paper.topics, null);
    assert.equal(paper.aiAvailable, true);
    assert.equal(paper.summary, good.tldr);
  }
  const normalized = join({...topics, laser_plasma_keywords: ['  laser  WAKEFIELDS ']}).topics;
  assert.deepEqual([...normalized.laser_plasma_keywords], ['Laser wakefields']);
});

test('raw dates and legacy inventory dates are deduplicated without relying on English inventory', () => {
  const {ctx} = browser();
  assert.deepEqual([...ctx.datesFromInventory('data/2026-10-20.jsonl\n2026-10-19_AI_enhanced_Chinese.jsonl\ndata/2026-10-20_AI_enhanced_English.jsonl\n2026-10-18_English.md')], ['2026-10-20', '2026-10-19']);
});

test('current backend index is required; watched middle authors survive truncation and HTML is escaped', () => {
  const {ctx} = browser();
  const matches = [match({author: 'Alexey <Arefiev>', display_name: 'A & "B"'}), match({author: 'Fourth', kind: 'suspected'})];
  const paper = {...raw('one', {authors: ['First', 'Second', 'Alexey <Arefiev>', 'Fourth', 'Fifth', 'Last']}), researcherMatches: matches};
  paper.authorList = paper.authors;
  const html = ctx.formatPaperAuthors(paper, [], true);
  assert.match(html, /Alexey &lt;Arefiev&gt;/);
  assert.match(html, /researcher-reliable/);
  assert.match(html, /researcher-suspected/);
  assert.match(html, /identity unconfirmed/);
  assert.doesNotMatch(html, /<Arefiev>|title="A & "B"/);
  assert.equal(ctx.currentResearcherMatches({...index({one: matches}), config_digest: 'old'}, 'one').length, 0);
  assert.equal(ctx.currentResearcherMatches(index({one: matches}), 'one').length, 2);
  assert.doesNotMatch(ctx.highlightMatches('<img src=x onerror=alert(1)>', ['img'], 'keyword-highlight'), /<img/);
});

test('raw file and only requested language are fetched; missing or broken AI still shows raw', async () => {
  for (const enhanced of [response('', 404), response('invalid JSON')]) {
    const fetched = [];
    const {ctx} = browser({fetch: async url => {
      fetched.push(url);
      if (url.endsWith('researcher-index.json')) return response(JSON.stringify(index()));
      if (url.includes('_AI_enhanced_')) return enhanced;
      return response(jsonl([raw('one')]));
    }});
    const papers = rows(ctx, await ctx.loadPaperDate('2026-10-20', 'Chinese'));
    assert.equal(papers.length, 1);
    assert.equal(papers[0].aiAvailable, false);
    assert.ok(fetched.every(url => !url.includes('English')));
    assert.ok(fetched.includes('/Daily_Arxiv/data/2026-10-20.jsonl'));
  }
});

test('homepage fetches English once for topics and keeps language failures independent', async () => {
  const requested = [];
  const source = raw('one');
  const translations = {
    English: jsonl([{...source, AI: good, topics}]),
    Chinese: jsonl([{...source, AI: {...good, tldr: '中文摘要'}}])
  };
  const {ctx} = browser({fetch: async url => {
    requested.push(url);
    if (url.endsWith('researcher-index.json')) return response(JSON.stringify(index()));
    const language = url.match(/_AI_enhanced_(English|Chinese)/)?.[1];
    return response(language ? translations[language] : jsonl([source]));
  }});
  const load = async language => rows(ctx,
    await ctx.loadPaperDates(['2026-10-20'], language, {includeTopics: true}))[0];
  assert.equal((await load('English')).summary, good.tldr);
  assert.equal(requested.filter(url => url.includes('_English')).length, 1);
  assert.equal(requested.filter(url => url.includes('_Chinese')).length, 0);
  const englishText = translations.English;
  translations.English = 'invalid JSON';
  const missingEnglish = await load('Chinese');
  assert.equal(missingEnglish.topics, null);
  assert.equal(missingEnglish.summary, '中文摘要');
  translations.Chinese = 'invalid JSON';
  translations.English = englishText;
  const missingChinese = await load('Chinese');
  assert.deepEqual(JSON.parse(JSON.stringify(missingChinese.topics)), topics);
  assert.equal(missingChinese.summary, source.summary);
});

test('date ranges merge raw IDs and categories once while preserving source order', async () => {
  const {ctx} = browser({fetch: async url => {
    if (url.endsWith('researcher-index.json')) return response(JSON.stringify(index()));
    if (url.includes('_AI_enhanced_')) return response('', 404);
    return response(jsonl(url.includes('10-20') ? [raw('two', {categories: ['physics.optics', 'physics.plasm-ph']}), raw('one')] : [raw('one'), raw('three')]));
  }});
  const data = await ctx.loadPaperDates(['2026-10-20', '2026-10-19'], 'English');
  const papers = rows(ctx, data);
  assert.deepEqual(Array.from(papers, paper => paper.id), ['two', 'one', 'three']);
  assert.equal(papers.find(paper => paper.id === 'one').date, '2026-10-19');
  assert.equal(ctx.getAllCategories(data, ['physics.plasm-ph']).totalCount, 3);
});

test('date-range duplicates keep available English topics only for the displayed source', () => {
  const {ctx} = browser();
  const source = raw('one');
  const day = (date, row, chinese, english) => ctx.attachLanguage(jsonl([row]),
    chinese ? jsonl([{...row, AI: good}]) : '', date, 'Chinese', null,
    english ? jsonl([{...row, AI: good, topics: english}]) : '');
  const combine = (older, newer) => rows(ctx, {a: Object.values(older).flat(), b: Object.values(newer).flat()})[0];
  const newer = day('2026-10-20', source, false, topics);
  const old = day('2026-10-19', source, true, null);
  assert.deepEqual(JSON.parse(JSON.stringify(combine(old, newer).topics)), topics);
  const revised = day('2026-10-19', {...source, summary: source.summary + '.'}, true, null);
  assert.equal(combine(revised, newer).topics, null);
  const conflicting = day('2026-10-19', source, true, {...topics, laser_plasma_keywords: []});
  assert.equal(combine(conflicting, newer).topics, null);
});

test('rapid language requests retain the latest result, range, filters, view and open paper', async () => {
  const {ctx, get} = browser();
  vm.runInContext(read('js/app.js'), ctx);
  vm.runInContext(`
    availableDates = ['2026-10-20', '2026-10-19'];
    currentCategory = 'physics.plasm-ph'; currentView = 'list'; textSearchQuery = 'laser';
    activeAuthors = ['personal']; activeKeywords = ['keyword']; openPaperId = 'one';
    renderCategoryFilter = () => {};
    showPaperDetails = paper => {globalThis.opened = paper;};
  `, ctx);
  const pending = [];
  ctx.loadPaperDates = (dates, language) => new Promise(resolve => pending.push({dates: [...dates], language, resolve}));
  const first = ctx.loadSelectedPapers('2026-10-19', '2026-10-20');
  vm.runInContext("selectedAILanguage = 'Chinese'", ctx);
  const second = ctx.loadSelectedPapers('2026-10-19', '2026-10-20');
  const data = language => ctx.attachLanguage(jsonl([raw('one')]), jsonl([raw('one', {AI: {...good, tldr: language}})]), '2026-10-20', language);
  pending[1].resolve(data('Chinese')); await second;
  pending[0].resolve(data('English')); await first;
  assert.equal(ctx.opened.summary, 'Chinese');
  assert.deepEqual(pending.map(item => item.language), ['English', 'Chinese']);
  assert.deepEqual(pending[1].dates, ['2026-10-20', '2026-10-19']);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify([currentCategory,currentView,textSearchQuery,activeAuthors,activeKeywords,selectedStartDate,selectedEndDate])', ctx)), ['physics.plasm-ph', 'list', 'laser', ['personal'], ['keyword'], '2026-10-19', '2026-10-20']);
  assert.equal(get('paperContainer').attributes['aria-busy'], 'false');
});

test('statistics rapid switches cannot overwrite the latest language or duplicate related papers', async () => {
  const {ctx, get} = browser({nlp: () => ({match: () => ({forEach() {}})})});
  vm.runInContext(read('js/statistic.js'), ctx);
  vm.runInContext("availableDates=['2026-10-20']; selectedRelatedKeyword='plasma';", ctx);
  const pending = [];
  ctx.loadPaperDates = () => new Promise(resolve => pending.push(resolve));
  const first = ctx.loadPapersByDateRange('2026-10-20', '2026-10-20');
  vm.runInContext("selectedAILanguage='Chinese'", ctx);
  const second = ctx.loadPapersByDateRange('2026-10-20', '2026-10-20');
  const data = language => ctx.attachLanguage(jsonl([raw('one'), raw('onev2')]), jsonl([raw('one', {AI: {...good, tldr: language}})]), '2026-10-20', language, index({one:[match()]}));
  pending[1](data('Chinese')); await second;
  pending[0](data('English')); await first;
  assert.equal(vm.runInContext('allPapersData.length', ctx), 1);
  assert.equal(vm.runInContext('allPapersData[0].summary', ctx), 'Chinese');
  assert.match(get('relatedPapers').innerHTML, /Chinese/);
  assert.match(get('relatedPapers').innerHTML, /researcher-reliable/);
});

test('homepage and detail render safe content and the same researcher marks', () => {
  const {ctx, get} = browser();
  vm.runInContext(read('js/app.js'), ctx);
  const paper = raw('one', {title: '<img src=x onerror=alert(1)>', summary: '<script>bad</script>'});
  ctx.loaded = ctx.attachLanguage(jsonl([paper]), '', '2026-10-20', 'Chinese', index({one: [match()]}));
  vm.runInContext('paperData = loaded;', ctx);
  ctx.renderPapers();
  const card = get('paperContainer').children[0].innerHTML;
  assert.match(card, /researcher-reliable/);
  assert.match(card, /Chinese AI summary unavailable/);
  assert.doesNotMatch(card, /<img|<script>/);
  ctx.showPaperDetails(rows(ctx, ctx.loaded)[0], 1);
  assert.match(get('modalBody').innerHTML, /researcher-reliable/);
  assert.doesNotMatch(get('modalBody').innerHTML, /<script>/);
  assert.doesNotMatch(get('modalTitle').innerHTML, /<img/);
});

test('cards rank active hits, researcher evidence and laser–plasma topics in stable category order', () => {
  const {ctx, get} = browser();
  vm.runInContext(read('js/app.js'), ctx);
  const ids = ['other', 'hit-other', 'topic', 'suspected', 'reliable', 'hit-topic', 'hit-suspected',
    'hit-reliable', 'hit-reliable-2', 'general-keywords', 'other-category'];
  const source = ids.map(id => raw(id, {
    title: id.startsWith('hit-') ? `Selected ${id}` : id,
    authors: id === 'hit-other' ? ['Personal Author'] : ['Alexey Arefiev'],
    categories: id === 'other-category' ? ['physics.optics'] : ['physics.optics', 'physics.plasm-ph']
  }));
  const enhanced = source.map(row => ({...row, AI: good,
    topics: row.id.includes('topic') ? topics : {...topics, laser_plasma_keywords: []}}));
  ctx.loaded = ctx.attachLanguage(jsonl([...source, source[4]]), jsonl(enhanced), '2026-10-20', 'English',
    index({reliable:[match()], suspected:[match({kind:'suspected'})],
      'hit-reliable':[match({kind:'suspected'}), match()], 'hit-reliable-2':[match()], 'hit-suspected':[match({kind:'suspected'})]}));
  vm.runInContext(`paperData = loaded; currentCategory = 'physics.plasm-ph';
    textSearchQuery = 'selected'; activeKeywords = ['hit-other']; activeAuthors = ['Personal']; renderPapers();`, ctx);
  const cards = get('paperContainer').children;
  const order = () => Array.from(vm.runInContext('currentFilteredPapers', ctx), paper => paper.id);
  const expected = ['hit-reliable', 'hit-reliable-2', 'hit-suspected', 'hit-topic', 'hit-other',
    'reliable', 'suspected', 'topic', 'other', 'general-keywords'];
  assert.deepEqual(order(), expected);
  assert.deepEqual(cards.map(card => card.dataset.id), expected);
  assert.equal(cards[0].className, 'paper-card matched-paper researcher-card-reliable');
  assert.equal(cards[2].className, 'paper-card matched-paper researcher-card-suspected');
  assert.equal(cards[3].className, 'paper-card matched-paper');
  assert.match(cards[4].title, /文本: selected.*关键词: hit-other.*作者: Personal/);
  assert.equal(cards[7].className, 'paper-card');
  assert.match(cards[7].innerHTML, /laser-plasma-keyword/);
  assert.doesNotMatch(cards[9].innerHTML, /laser-plasma-keyword/);

  vm.runInContext(`currentPaperIndex = 4; showPaperDetails(currentFilteredPapers[4], 5);
    textSearchQuery = ''; activeKeywords = []; activeAuthors = []; renderPapers();`, ctx);
  assert.equal(vm.runInContext('currentFilteredPapers[currentPaperIndex].id', ctx), 'hit-other');
  assert.equal(get('paperPosition').textContent, '9 / 10');
  ctx.navigateToPreviousPaper();
  assert.equal(vm.runInContext('openPaperId', ctx), 'other');
  ctx.navigateToNextPaper();
  assert.equal(vm.runInContext('openPaperId', ctx), 'hit-other');
});

test('topic chips in a Chinese raw fallback escape scientific labels identically in both views', () => {
  const {ctx, get} = browser();
  vm.runInContext(read('js/app.js'), ctx);
  const source = raw('one');
  const keyword = 'Laser & "plasma"';
  const labels = {keywords: [keyword, 'PIC simulations', 'Betatron radiation'], laser_plasma_keywords: [keyword]};
  ctx.loaded = ctx.attachLanguage(jsonl([source]), '', '2026-10-20', 'Chinese', null,
    jsonl([{...source, AI: good, topics: labels}]));
  vm.runInContext('paperData = loaded; renderPapers(); showPaperDetails(currentFilteredPapers[0], 1);', ctx);
  const card = get('paperContainer').children[0].innerHTML;
  const detail = get('modalBody').innerHTML;
  const chips = html => html.match(/<div class="paper-keywords"[^>]*>.*?<\/div>/)?.[0];
  assert.equal(chips(card), chips(detail));
  assert.match(chips(card), /aria-label="Laser–plasma keyword: Laser &amp; &quot;plasma&quot;"/);
  assert.match(card, /Chinese AI summary unavailable/);
  assert.match(detail, /Exact original abstract/);
  assert.doesNotMatch(detail, /AI tldr/);
});

test('language controls use native buttons and preferences explain their local scope', () => {
  for (const page of ['index.html', 'statistic.html']) {
    assert.match(read(page), /<button type="button" data-ai-language="English" aria-pressed=/);
    assert.match(read(page), /<button type="button" data-ai-language="Chinese" aria-pressed="(?:true|false)" title="Chinese AI summaries">ZH<\/button>/);
    assert.doesNotMatch(read(page), />中文<\/button>/);
  }
  assert.match(read('settings.html'), /only in this browser/);
  assert.doesNotMatch(read('js/app.js') + read('js/statistic.js') + read('js/settings.js'), /api.github.com\/repos\/dw-dengwei/);
});

test('changing date mode clears the previous day before a new range is chosen', () => {
  for (const script of ['js/app.js', 'js/statistic.js']) {
    const {ctx, get} = browser();
    vm.runInContext(read(script), ctx);
    get('dateRangeMode').checked = true;
    vm.runInContext("globalThis.pickerCalls=[]; flatpickrInstance={set: (...args)=>pickerCalls.push(args),clear: (...args)=>pickerCalls.push(['clear',...args])};", ctx);
    ctx.toggleRangeMode();
    assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(pickerCalls)', ctx)), [['mode', 'range'], ['clear', false]]);
  }
});

test('AI-only files cannot publish papers when the authoritative raw file is absent', async () => {
  const {ctx} = browser({fetch: async url => {
    if (url.endsWith('researcher-index.json')) return response(JSON.stringify(index()));
    if (url.includes('_AI_enhanced_')) return response(jsonl([raw('one', {AI: good})]));
    return response('', 404);
  }});
  assert.equal(rows(ctx, await ctx.loadPaperDate('2026-10-21', 'English')).length, 0);
});

test('raw fetch failures fail explicitly even when valid AI files exist', async () => {
  const {ctx} = browser({fetch: async url => {
    if (url.endsWith('researcher-index.json')) return response(JSON.stringify(index()));
    if (url.includes('_AI_enhanced_')) return response(jsonl([raw('one', {AI: good})]));
    return response('', 503);
  }});
  await assert.rejects(ctx.loadPaperDate('2026-10-21', 'English'), /Raw papers unavailable.*503/);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const categories = ['physics.plasm-ph', 'physics.acc-ph', 'physics.optics', 'physics.flu-dyn', 'physics.atom-ph', 'physics.comp-ph'];
const context = vm.createContext({console});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/papers.js'), 'utf8'), context);
function parse(rows) { return context.parseJsonlData(rows.map(JSON.stringify).join('\n'), '2026-10-20'); }
const good = Object.fromEntries(['tldr','motivation','method','result','conclusion'].map(field => [field, `Valid ${field}`]));
function paper(id, categories, ai=good) { return {id, categories, title:'Test', summary:'Original abstract', AI:ai, authors:['A']}; }

test('failed AI falls back to original abstract and hides all error fields', () => {
  const data=parse([paper('one',['physics.plasm-ph'],{...good,tldr:'Summary generation failed'})]);
  const row=context.uniquePapers(data)[0];
  assert.equal(row.summary,'Original abstract');
  assert.equal(row.aiAvailable,false);
  assert.equal(row.motivation,'');
});
test('valid AI keeps enhanced summary',()=>{
  const row=context.uniquePapers(parse([paper('one',['physics.plasm-ph'])]))[0];
  assert.equal(row.summary,'Valid tldr');assert.equal(row.aiAvailable,true);
});
test('cross-listed paper appears in secondary category',()=>{
  const data=parse([paper('one',['cond-mat.mtrl-sci','physics.plasm-ph'])]);
  assert.equal(context.papersForCategory(data,'physics.plasm-ph').length,1);
  assert.equal(context.getAllCategories(data, categories).categoryCounts['physics.plasm-ph'],1);
});
test('category menu contains only the configured subscriptions in their order', () => {
  const data = parse([
    paper('one', ['astro-ph.SR', 'physics.plasm-ph', 'physics.optics']),
    paper('two', ['cs.AI', 'physics.optics']),
    paper('one', ['astro-ph.SR', 'physics.plasm-ph', 'physics.optics'])
  ]);
  const before = JSON.stringify(data);
  const counts = context.getAllCategories(data, categories);
  assert.deepEqual([...counts.sortedCategories], categories);
  assert.deepEqual(Object.keys(counts.categoryCounts), categories);
  assert.equal(counts.categoryCounts['physics.plasm-ph'], 1);
  assert.equal(counts.categoryCounts['physics.optics'], 2);
  assert.equal(counts.categoryCounts['physics.acc-ph'], 0);
  assert.equal(counts.totalCount, 2);
  assert.equal(context.papersForCategory(data, 'physics.plasm-ph').length, 1);
  assert.equal(JSON.stringify(data), before);
  const custom = context.getAllCategories(data, ['physics.optics', 'physics.plasm-ph']);
  assert.deepEqual([...custom.sortedCategories], ['physics.optics', 'physics.plasm-ph']);
  assert.equal(custom.totalCount, counts.totalCount);
});
test('missing browser settings use build defaults without discovering extra filters', () => {
  const code = fs.readFileSync(path.join(__dirname, '../js/papers.js'), 'utf8');
  const built = vm.createContext({console});
  vm.runInContext(code.replace('"__DEFAULT_CATEGORIES__"', JSON.stringify(categories)), built);
  const data = parse([paper('one', ['cs.AI', 'physics.plasm-ph'])]);
  assert.deepEqual([...built.getAllCategories(data).sortedCategories], categories);
  assert.equal(built.getAllCategories(data).totalCount, 1);
  assert.deepEqual([...context.getAllCategories(data).sortedCategories], []);
});
test('all count is unique while category counts may overlap',()=>{
  const data=parse([paper('one',['physics.plasm-ph','physics.optics']),paper('two',['physics.optics']),paper('one',['physics.plasm-ph','physics.optics'])]);
  assert.equal(context.papersForCategory(data,'all').length,2);
  const counts=context.getAllCategories(data, categories);
  assert.equal(counts.totalCount,2);assert.equal(counts.categoryCounts['physics.optics'],2);
  assert.equal(counts.categoryCounts['physics.plasm-ph'],1);
});
test('incomplete or empty AI also falls back without showing placeholders',()=>{
  for(const ai of [null,{}, {...good,method:''}, {...good,result:' Processing failed '}, {...good,tldr:'This content has not passed the compliance test and has been hidden.'}]) {
    const row=context.uniquePapers(parse([paper('one',['physics.plasm-ph'],ai)]))[0];
    assert.equal(row.aiAvailable,false);assert.equal(row.summary,'Original abstract');
  }
});

test('date-range duplicates keep earliest date, valid AI and all categories', () => {
  const late = context.parseJsonlData(JSON.stringify(paper('2610.26164v2', ['physics.optics'])), '2026-10-20');
  const early = context.parseJsonlData(JSON.stringify(paper('2610.26164', ['physics.plasm-ph'], {})), '2026-10-17');
  const rows = context.uniquePapers({...late, ...early});
  assert.equal(rows.length, 1);
  assert.equal(rows[0].date, '2026-10-17');
  assert.equal(rows[0].summary, 'Valid tldr');
  assert.deepEqual([...rows[0].category].sort(), ['physics.optics', 'physics.plasm-ph']);
});

test('statistics uses the shared parser and counts uneven dates accurately', () => {
  const ctx = vm.createContext({console, document: {addEventListener() {}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/papers.js'), 'utf8'), ctx);
  const sharedParser = ctx.parseJsonlData;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/statistic.js'), 'utf8'), ctx);
  assert.equal(ctx.parseJsonlData, sharedParser);
  const early = ctx.parseJsonlData(JSON.stringify(paper('one', ['physics.plasm-ph'], {})), '2026-10-17');
  const late = ctx.parseJsonlData(['one', 'two', 'three', 'four'].map(id => JSON.stringify(paper(id, ['physics.optics']))).join('\n'), '2026-10-20');
  const rows = ctx.uniquePapers({...early, ...late});
  const {allKeywords, keywordTrends} = ctx.countKeywordsByDate(rows, ['2026-10-17', '2026-10-20'], () => ['plasma']);
  assert.equal(rows.length, 4);
  assert.equal(allKeywords.get('plasma'), 4);
  assert.equal(keywordTrends.get('2026-10-17').get('plasma'), 1);
  assert.equal(keywordTrends.get('2026-10-20').get('plasma'), 3);
  assert.equal(ctx.uniquePapers(early)[0].summary, 'Original abstract');
  const html = fs.readFileSync(path.join(__dirname, '../statistic.html'), 'utf8');
  assert.ok(html.indexOf('js/papers.js') < html.indexOf('js/statistic.js'));
});

test('language selection uses the repository edition', () => {
  for(const page of [source, fs.readFileSync(path.join(__dirname, '../js/statistic.js'), 'utf8')]) {
  const first=page.indexOf('function getPreferredLanguage()');
  const last=page.indexOf('async function fetchAvailableDates()',first);
  for(const language of ['English','Chinese']) {
    const ctx=vm.createContext({DATA_CONFIG:{language},window:{dateLanguageMap:new Map([['2026-10-20',['English','Chinese']]])}});
    vm.runInContext(page.slice(first,last),ctx);
    assert.equal(ctx.getPreferredLanguage(),language);
    assert.equal(ctx.selectLanguageForDate('2026-10-20'),language);
    assert.equal(ctx.selectLanguageForDate('missing'),language);
  }
  }
});

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

test('both pages use shared language selection without a language fallback', () => {
  for (const page of [source, fs.readFileSync(path.join(__dirname, '../js/statistic.js'), 'utf8')]) {
    assert.doesNotMatch(page, /function getPreferredLanguage|function selectLanguageForDate/);
    assert.match(page, /initLanguageSelector/);
    assert.match(page, /loadPaperDates/);
  }
});

const konzelPaper = {
  url: 'https://arxiv.org/abs/2610.26476',
  authorList: ['A. Konzel', 'J. Vieira'],
  title: 'Spatiotemporal spherical Gaussian pulses',
  date: '2027-01-01'
};
const konzelFilename = '2026-ArXiv-A.-Konzel-Spatiotemporal-spherical-Gaussian-pulses.pdf';

function pdfContext(overrides = {}) {
  const ctx = vm.createContext({TextEncoder, document: {addEventListener() {}}, ...overrides});
  vm.runInContext(source, ctx);
  return ctx;
}

test('ChatGPT handoff copies the paper in the selected language and exposes a manual fallback', async () => {
  const elements = Object.fromEntries(['chatgptLink', 'chatgptFeedback', 'chatgptStatus', 'chatgptPrompt']
    .map(id => [id, {select() { this.selected = true; }}]));
  let copied;
  const ctx = pdfContext({document: {addEventListener() {}, getElementById: id => elements[id]},
    navigator: {clipboard: {writeText: async text => { copied = text; }}}, getPreferredLanguage: () => 'Chinese'});
  const source = ctx.paperPdfSource(konzelPaper.url);
  ctx.bindChatGPT(konzelPaper, source);
  await elements.chatgptLink.onclick();
  assert.match(copied, /请阅读/);
  assert.ok([konzelPaper.title, source.url, konzelPaper.url].every(term => copied.includes(term)));
  assert.equal(elements.chatgptPrompt.hidden, true);
  ctx.navigator.clipboard.writeText = async () => { throw new Error('denied'); };
  await elements.chatgptLink.onclick();
  assert.equal(elements.chatgptPrompt.value, copied);
  assert.equal(elements.chatgptPrompt.hidden, false);
  assert.equal(elements.chatgptPrompt.selected, true);
});

test('PDF names use the ID year, original first author and full title', () => {
  const ctx = pdfContext();
  const info = ctx.paperPdfSource(konzelPaper.url);
  assert.equal(info.url, 'https://arxiv.org/pdf/2610.26476');
  const names = ctx.paperPdfNames(konzelPaper, info);
  assert.equal(names.full, konzelFilename);
  assert.equal(names.download, konzelFilename);
  const legacy = ctx.paperPdfSource('http://www.arxiv.org/pdf/math.GT/9908123v2.pdf#page=3');
  assert.equal(legacy.year, 1999);
  assert.equal(legacy.url, 'https://arxiv.org/pdf/math.GT/9908123v2');
  assert.equal(ctx.paperPdfSource('https://arxiv.org/abs/physics/0301123').year, 2003);
  assert.equal(ctx.paperPdfSource('https://arxiv.org/abs/0704.0001v3').year, 2007);
  const unicode = ctx.paperPdfNames({authorList: ['李 M. Öztürk'], title: 'β/γ: 激光 <pulse>?'}, legacy);
  assert.equal(unicode.download, '1999-ArXiv-李-M.-Öztürk-β-γ-激光-pulse.pdf');
  const long = ctx.paperPdfNames({...konzelPaper, title: '激光🌞'.repeat(60) + ' END'}, info);
  assert.ok(long.full.endsWith('激光🌞-END.pdf'));
  assert.ok(long.download.endsWith('-2610.26476.pdf'));
  assert.ok(Buffer.byteLength(long.download, 'utf8') <= 255);
  assert.equal(Buffer.from(long.download).toString('utf8'), long.download);
});

test('PDF preview accepts only official paper URLs and valid ID paths', () => {
  const ctx = pdfContext();
  for (const bad of [
    'javascript:alert(1)', 'https://arxiv.org.attacker.test/abs/2610.26476',
    'https://arxiv.org@attacker.test/abs/2610.26476', 'https://user@arxiv.org/pdf/2610.26476',
    'https://arxiv.org/pdf/2610.26476/extra', 'https://arxiv.org/abs/2613.26476',
    'https://arxiv.org/abs/%2F2610.26476', 'https://arxiv.org/search/?id=2610.26476'
  ]) assert.equal(ctx.paperPdfSource(bad), null, bad);
});

function pdfDownloadHarness(request) {
  const elements = {};
  for (const id of ['downloadPaperPdf', 'pdfDownloadStatus', 'pdfDownloadFallback', 'suggestedPdfName']) {
    elements[id] = {addEventListener(event, handler) {this[event] = handler;}, isConnected: true, hidden: true};
  }
  const downloads = [];
  const revoked = [];
  const cleanup = [];
  let savedBlob;
  const ctx = pdfContext({
    document: {
      addEventListener() {}, getElementById: id => elements[id], body: {appendChild() {}},
      createElement: () => ({click() {downloads.push(this);}, remove() {this.removed = true;}})
    },
    URL: {
      createObjectURL(blob) {savedBlob = blob; return 'blob:paper';},
      revokeObjectURL(url) {revoked.push(url);}
    },
    setTimeout: callback => cleanup.push(callback), fetch: request
  });
  vm.runInContext("openPaperId = '2610.26476'", ctx);
  const info = ctx.paperPdfSource(konzelPaper.url);
  ctx.bindPdfDownload(info, ctx.paperPdfNames(konzelPaper, info));
  return {elements, downloads, cleanup, revoked, savedBlob: () => savedBlob};
}

test('preview downloads the PDF bytes with its suggested name and releases the object URL', async () => {
  const bytes = new Blob(['%PDF-1.7\n'], {type: 'application/pdf'});
  const harness = pdfDownloadHarness(async (url, options) => {
    assert.equal(url, 'https://arxiv.org/pdf/2610.26476');
    assert.equal(options.credentials, 'omit');
    return {ok: true, blob: async () => bytes};
  });
  await harness.elements.downloadPaperPdf.click();
  assert.equal(harness.elements.suggestedPdfName.value, konzelFilename);
  assert.equal(harness.downloads.length, 1);
  assert.equal(harness.downloads[0].download, konzelFilename);
  assert.equal(harness.downloads[0].href, 'blob:paper');
  assert.ok(harness.downloads[0].removed);
  assert.equal(harness.savedBlob(), bytes);
  harness.cleanup.forEach(fn => fn());
  assert.deepEqual(harness.revoked, ['blob:paper']);
});

test('blocked requests and non-PDF bodies show the manual save instructions', async () => {
  for (const request of [
    async () => {throw new TypeError('Failed to fetch');},
    async () => ({ok: false}),
    async () => ({ok: true, blob: async () => new Blob(['<html>Error</html>'], {type: 'application/pdf'})})
  ]) {
    const {elements, downloads} = pdfDownloadHarness(request);
    await elements.downloadPaperPdf.click();
    assert.equal(downloads.length, 0);
    assert.match(elements.pdfDownloadStatus.textContent, /Open the PDF/);
    assert.equal(elements.pdfDownloadFallback.hidden, false);
    assert.equal(elements.suggestedPdfName.value, konzelFilename);
    assert.equal(elements.downloadPaperPdf.disabled, false);
  }
});

test('a PDF request cannot start another download after the preview was replaced', async () => {
  let finish;
  const {elements, downloads} = pdfDownloadHarness(() => new Promise(resolve => {finish = resolve;}));
  const pending = elements.downloadPaperPdf.click();
  assert.equal(elements.downloadPaperPdf.disabled, true);
  elements.downloadPaperPdf.isConnected = false;
  finish({ok: true, blob: async () => new Blob(['%PDF-1.7\n'])});
  await pending;
  assert.equal(downloads.length, 0);
});

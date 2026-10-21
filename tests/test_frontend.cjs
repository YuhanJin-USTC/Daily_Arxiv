const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const start = source.indexOf('const AI_ERROR_PLACEHOLDERS');
const end = source.indexOf('function renderCategoryFilter', start);
const context = vm.createContext({console});
vm.runInContext(source.slice(start, end), context);
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
  assert.equal(context.getAllCategories(data).categoryCounts['physics.plasm-ph'],1);
});
test('all count is unique while category counts may overlap',()=>{
  const data=parse([paper('one',['physics.plasm-ph','physics.optics']),paper('two',['physics.optics']),paper('one',['physics.plasm-ph','physics.optics'])]);
  assert.equal(context.papersForCategory(data,'all').length,2);
  const counts=context.getAllCategories(data);
  assert.equal(counts.totalCount,2);assert.equal(counts.categoryCounts['physics.optics'],2);
  assert.equal(counts.categoryCounts['physics.plasm-ph'],1);
});
test('incomplete or empty AI also falls back without showing placeholders',()=>{
  for(const ai of [null,{}, {...good,method:''}, {...good,result:' Processing failed '}, {...good,tldr:'This content has not passed the compliance test and has been hidden.'}]) {
    const row=context.uniquePapers(parse([paper('one',['physics.plasm-ph'],ai)]))[0];
    assert.equal(row.aiAvailable,false);assert.equal(row.summary,'Original abstract');
  }
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

const test = require('node:test');
const assert = require('node:assert/strict');
const {validateSiteUrl, validatePaperId, selectPublishedAI, assertPublishedDetail, isSitePage, redact, runChecks} = require('../scripts/check_live_site.cjs');
const site = 'https://yuhanjin-ustc.github.io/Daily_Arxiv/';

test('live browser credentials can only target the authorized repository Pages root', () => {
  assert.equal(validateSiteUrl(), site);
  assert.equal(validateSiteUrl(site), site);
  for (const value of ['https://example.org/Daily_Arxiv/', 'http://yuhanjin-ustc.github.io/Daily_Arxiv/',
    'https://yuhanjin-ustc.github.io/daily-arxiv/',
    'https://yuhanjin-ustc.github.io/another-repo/', 'https://yuhanjin-ustc.github.io/Daily_Arxiv/?redirect=https://example.org',
    'https://user:pass@yuhanjin-ustc.github.io/Daily_Arxiv/', 'https://yuhanjin-ustc.github.io:8443/Daily_Arxiv/',
    'https://yuhanjin-ustc.github.io/Daily_Arxiv/#credentials', 'https://yuhanjin-ustc.github.io.evil.example/Daily_Arxiv/']) {
    assert.throws(() => validateSiteUrl(value), /authorized/);
  }
});

test('login redirects stay inside the authorized path and reject URL credentials', () => {
  assert.equal(isSitePage(site + 'login.html?redirect=index.html', site, ['login.html']), true);
  for (const value of ['https://example.org/Daily_Arxiv/login.html', 'https://yuhanjin-ustc.github.io/old/login.html',
    'https://user:pass@yuhanjin-ustc.github.io/Daily_Arxiv/login.html', site + 'settings.html']) {
    assert.equal(isSitePage(value, site, ['login.html']), false);
  }
});

test('reports redact literal secrets recursively without treating them as regular expressions', () => {
  const secret = 'quoted".$🔒';
  const data = {error: `before ${secret} after`, nested: [{message: secret}], count: 3};
  assert.deepEqual(redact(data, secret), {error: 'before [redacted] after', nested: [{message: '[redacted]'}], count: 3});
  assert.equal(data.nested[0].message, secret);
});

test('unauthorized URL, repository and missing password stop before loading browser dependencies', async () => {
  await assert.rejects(runChecks({SITE_URL: 'https://example.org/'}), /authorized/);
  await assert.rejects(runChecks({VERIFY_PAPER_ID: '../data'}), /VERIFY_PAPER_ID/);
  await assert.rejects(runChecks({SITE_URL: site}), /ACCESS_PASSWORD/);
  await assert.rejects(runChecks({SITE_URL: site, ACCESS_PASSWORD: 'synthetic-only', GITHUB_REPOSITORY: 'other/repository'}), /workflow repository/);
  await assert.rejects(runChecks({SITE_URL: site, ACCESS_PASSWORD: 'synthetic-only'}), /PLAYWRIGHT_MODULE/);
});

test('optional verification accepts one normalized arXiv ID and rejects URLs or malformed IDs', () => {
  assert.equal(validatePaperId(), null);
  assert.equal(validatePaperId(''), null);
  assert.equal(validatePaperId('2610.29709v2'), '2610.29709');
  assert.equal(validatePaperId('hep-th/9901001'), 'hep-th/9901001');
  for (const value of ['2613.29709', '2610.29709v0', ' 2610.29709', '2610.29709\n',
    'https://arxiv.org/abs/2610.29709', '2610.29709,2610.29951', '../2610.29709', 2610.29709]) {
    assert.throws(() => validatePaperId(value), /VERIFY_PAPER_ID/);
  }
});

const raw = {id: '2610.29709v1', summary: 'Exact original abstract.'};
const english = {tldr: 'A short summary.', motivation: 'The reason.', method: 'The method.', result: 'The result.', conclusion: 'The conclusion.'};
const chinese = {tldr: '中文摘要。', motivation: '研究动机。', method: '研究方法。', result: '研究结果。', conclusion: '研究结论。'};
const enhanced = AI => ({...raw, AI});
const detail = (expected, language) => ({id: expected.id, language, available: true, abstract: raw.summary,
  fields: expected.fields, heading: 'TL;DR', unavailable: 0, rendered: expected.fields, renderedAbstract: raw.summary});

test('published AI selection binds normalized ID and exact abstract, and rejects incomplete or conflicting data', () => {
  const expected = selectPublishedAI([raw], [enhanced(english)], '2610.29709');
  assert.deepEqual(expected.fields, Object.values(english));
  assert.deepEqual(selectPublishedAI([raw], [enhanced(english), enhanced(english)], '2610.29709'), expected);
  assert.throws(() => selectPublishedAI([], [enhanced(english)], '2610.29709'), /raw data/);
  assert.throws(() => selectPublishedAI([raw], [], '2610.29709'), /exact published/);
  assert.throws(() => selectPublishedAI([raw], [{...enhanced(english), summary: 'Changed abstract.'}], '2610.29709'), /exact published/);
  assert.throws(() => selectPublishedAI([raw], [enhanced({...english, conclusion: ''})], '2610.29709'), /five fields/);
  assert.throws(() => selectPublishedAI([raw], [enhanced(english), enhanced({...english, result: 'Conflicting result.'})], '2610.29709'), /fields conflict/);
  assert.throws(() => selectPublishedAI([raw], [enhanced({...english, tldr: raw.summary})], '2610.29709'), /differ from the raw/);
});

test('visible detail must match every selected-language AI field, not raw or the other language', () => {
  const en = selectPublishedAI([raw], [enhanced(english)], '2610.29709');
  const zh = selectPublishedAI([raw], [enhanced(chinese)], '2610.29709');
  assertPublishedDetail(detail(en, 'English'), en, 'English');
  assertPublishedDetail(detail(zh, 'Chinese'), zh, 'Chinese');
  for (const invalid of [
    {...detail(zh, 'Chinese'), id: '2610.29951'},
    {...detail(zh, 'Chinese'), available: false},
    {...detail(zh, 'Chinese'), language: 'English'},
    {...detail(zh, 'Chinese'), fields: en.fields},
    {...detail(zh, 'Chinese'), rendered: en.fields},
    {...detail(zh, 'Chinese'), rendered: [raw.summary, ...zh.fields.slice(1)]},
    {...detail(zh, 'Chinese'), rendered: [...zh.fields.slice(0, 4), 'Wrong conclusion.']},
    {...detail(zh, 'Chinese'), unavailable: 1},
    {...detail(zh, 'Chinese'), renderedAbstract: 'Changed abstract.'}
  ]) assert.throws(() => assertPublishedDetail(invalid, zh, 'Chinese'));
});

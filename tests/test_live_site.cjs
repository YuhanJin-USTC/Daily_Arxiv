const test = require('node:test');
const assert = require('node:assert/strict');
const {validateSiteUrl, isSitePage, redact, runChecks} = require('../scripts/check_live_site.cjs');
const site = 'https://yuhanjin-ustc.github.io/daily-arxiv/';

test('live browser credentials can only target the authorized repository Pages root', () => {
  assert.equal(validateSiteUrl(), site);
  assert.equal(validateSiteUrl(site), site);
  for (const value of ['https://example.org/daily-arxiv/', 'http://yuhanjin-ustc.github.io/daily-arxiv/',
    'https://yuhanjin-ustc.github.io/another-repo/', 'https://yuhanjin-ustc.github.io/daily-arxiv/?redirect=https://example.org',
    'https://user:pass@yuhanjin-ustc.github.io/daily-arxiv/', 'https://yuhanjin-ustc.github.io:8443/daily-arxiv/',
    'https://yuhanjin-ustc.github.io/daily-arxiv/#credentials', 'https://yuhanjin-ustc.github.io.evil.example/daily-arxiv/']) {
    assert.throws(() => validateSiteUrl(value), /authorized/);
  }
});

test('login redirects stay inside the authorized path and reject URL credentials', () => {
  assert.equal(isSitePage(site + 'login.html?redirect=index.html', site, ['login.html']), true);
  for (const value of ['https://example.org/daily-arxiv/login.html', 'https://yuhanjin-ustc.github.io/old/login.html',
    'https://user:pass@yuhanjin-ustc.github.io/daily-arxiv/login.html', site + 'settings.html']) {
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
  await assert.rejects(runChecks({SITE_URL: site}), /ACCESS_PASSWORD/);
  await assert.rejects(runChecks({SITE_URL: site, ACCESS_PASSWORD: 'synthetic-only', GITHUB_REPOSITORY: 'other/repository'}), /workflow repository/);
  await assert.rejects(runChecks({SITE_URL: site, ACCESS_PASSWORD: 'synthetic-only'}), /PLAYWRIGHT_MODULE/);
});

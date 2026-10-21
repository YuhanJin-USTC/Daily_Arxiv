const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const REPOSITORY = 'yuhanjin-ustc/daily-arxiv';
const SITE = 'https://yuhanjin-ustc.github.io/daily-arxiv/';

function validateSiteUrl(value = SITE) {
  const url = new URL(value);
  if (url.origin !== new URL(SITE).origin || url.pathname !== '/daily-arxiv/' ||
      url.username || url.password || url.search || url.hash) {
    throw new Error('SITE_URL must be the authorized Daily-Arxiv Pages URL.');
  }
  return url.href;
}

function isSitePage(value, site, pages) {
  const url = new URL(value);
  return !url.username && !url.password && url.origin === new URL(site).origin && pages.some(page =>
    url.pathname === new URL(page, site).pathname
  );
}

function redact(value, password) {
  if (typeof value === 'string') return password ? value.split(password).join('[redacted]') : value;
  if (Array.isArray(value)) return value.map(item => redact(item, password));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redact(item, password)]));
  }
  return value;
}

async function runChecks(env = process.env) {
  const site = validateSiteUrl(env.SITE_URL || SITE);
  const password = env.ACCESS_PASSWORD;
  if (!password) throw new Error('ACCESS_PASSWORD must be provided through the job environment.');
  if (env.GITHUB_REPOSITORY && env.GITHUB_REPOSITORY.toLowerCase() !== REPOSITORY) {
    throw new Error('The workflow repository does not match the authorized site.');
  }
  if (!env.PLAYWRIGHT_MODULE) throw new Error('PLAYWRIGHT_MODULE must point to the installed Playwright module.');
  const {chromium} = require(path.resolve(env.PLAYWRIGHT_MODULE));
  const output = path.resolve(env.BROWSER_REPORT_DIR || 'artifacts/live-browser');
  fs.mkdirSync(output, {recursive: true});
  const report = {site, checks: [], screenshots: [], pageErrors: [], started: new Date().toISOString()};
  const browserEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => key !== 'ACCESS_PASSWORD'));
  let browser;
  const ready = page => page.waitForFunction(() => document.querySelectorAll('.paper-card').length > 0 &&
    document.querySelector('#paperContainer')?.getAttribute('aria-busy') !== 'true');
  const finished = page => page.waitForFunction(() => document.querySelector('#paperContainer')?.getAttribute('aria-busy') === 'false');
  try {
    browser = await chromium.launch({headless: true, env: browserEnv,
      ...(env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath: path.resolve(env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)} : {})});
    report.browser = browser.version();
    for (const width of [1440, 768, 390]) {
      // Fresh storage; no videos, traces, or saved sessions.
      const context = await browser.newContext({viewport: {width, height: 1000}});
      const page = await context.newPage();
      page.on('pageerror', error => report.pageErrors.push(redact(error.message, password)));
      await page.goto(site, {waitUntil: 'domcontentloaded'});
      await page.waitForURL(url => isSitePage(url.href, site, ['login.html']));
      assert.equal(await page.evaluate(() => Boolean(Auth.isPasswordEnabled())), true);
      const wrong = password === 'invalid-site-password' ? 'another-invalid-password' : 'invalid-site-password';
      await page.locator('#password').fill(wrong);
      await page.locator('#password').press('Enter');
      await page.locator('#errorMessage').waitFor({state: 'visible'});
      await page.waitForFunction(() => !document.getElementById('loginButton').disabled);
      assert.match(await page.locator('#errorMessage').textContent(), /Invalid password/);
      assert.equal(await page.evaluate(() => Auth.isAuthenticated()), false);
      assert.ok(isSitePage(page.url(), site, ['login.html']));
      await page.locator('#password').fill(password);
      await page.locator('#password').press('Enter');
      await page.waitForURL(url => isSitePage(url.href, site, ['index.html']));
      await ready(page);
      const config = await page.evaluate(() => ({repository: `${DATA_CONFIG.repoOwner}/${DATA_CONFIG.repoName}`.toLowerCase(),
        data: DATA_CONFIG.getDataBaseUrl(), namespace: DATA_CONFIG.namespace, languages: DATA_CONFIG.languages,
        digest: DATA_CONFIG.researchersDigest, auth: AUTH_CONFIG.storageKey, date: currentDate,
        authenticated: Auth.isAuthenticated()}));
      assert.equal(config.repository, REPOSITORY);
      assert.equal(config.data.toLowerCase(), `https://raw.githubusercontent.com/${REPOSITORY}/data`);
      assert.equal(config.namespace, `daily-arxiv:${REPOSITORY}`);
      assert.equal(config.auth, `arxiv_auth:${REPOSITORY}:token`);
      assert.equal(config.authenticated, true);
      assert.deepEqual(config.languages, ['English', 'Chinese']);
      assert.equal(await page.locator('[data-repository-link]').first().evaluate(el => el.href.toLowerCase()), `https://github.com/${REPOSITORY}`);
      const rawText = await page.evaluate(async date => {
        const response = await fetch(DATA_CONFIG.getDataUrl(`data/${date}.jsonl`));
        if (!response.ok) throw new Error('Published raw data is unavailable.');
        return response.text();
      }, config.date);
      const rawIds = new Set(rawText.trim().split('\n').filter(Boolean).map(line => JSON.parse(line).id.replace(/v\d+$/, '')));
      assert.equal(await page.locator('.paper-card').count(), rawIds.size);
      const index = await page.evaluate(async () => {
        const response = await fetch(DATA_CONFIG.getDataUrl('assets/researcher-index.json'));
        if (!response.ok) throw new Error('Published researcher index is unavailable.');
        return response.json();
      });
      assert.equal(index.config_digest, config.digest);
      assert.equal(index.schema_version, 1);
      assert.equal(await page.evaluate(() => getPreferredLanguage()), 'English');
      assert.equal(await page.locator('header [data-ai-language="Chinese"]').textContent(), 'ZH');
      const shot = async name => {
        assert.equal(await page.locator('#password').count(), 0, 'Never capture a password form.');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const filename = `${name}-${width}.png`;
        await page.screenshot({path: path.join(output, filename), animations: 'disabled'});
        report.screenshots.push(filename);
      };
      await shot('home');
      await page.locator('header [data-ai-language="Chinese"]').focus();
      await page.keyboard.press('Enter');
      await finished(page);
      assert.equal(await page.evaluate(() => getPreferredLanguage()), 'Chinese');
      assert.equal(await page.locator('.paper-card').count(), rawIds.size);
      await page.locator('.paper-card').first().click();
      const title = await page.locator('#modalTitle').textContent();
      await page.locator('#paperModal [data-ai-language="English"]').click();
      await finished(page);
      assert.equal(await page.locator('#modalTitle').textContent(), title);
      await shot('detail');
      await page.locator('#closeModal').click();
      await page.locator('header [data-ai-language="Chinese"]').click();
      await finished(page);await page.reload();await ready(page);
      assert.equal(await page.evaluate(() => getPreferredLanguage()), 'Chinese');
      await page.goto(new URL('statistic.html', site).href);
      if (width < 768) await page.getByRole('button', {name: 'Got it'}).click();
      await page.waitForSelector('.statistics-section');
      assert.equal(await page.evaluate(() => getPreferredLanguage()), 'Chinese');
      assert.equal(await page.evaluate(() => new Set(allPapersData.map(p => normalizePaperId(p.id))).size === allPapersData.length), true);
      if (await page.locator('.keyword-item').count()) {
        await page.locator('.keyword-item').first().click();
        const keyword = await page.locator('#selectedKeyword').textContent();
        await page.locator('#paperSidebar [data-ai-language="English"]').click();
        await page.waitForFunction(() => allPapersData.length && allPapersData.every(paper => paper.aiLanguage === 'English'));
        assert.equal(await page.locator('#selectedKeyword').textContent(), keyword);
        assert.ok(await page.locator('#paperSidebar.active').count());
        await page.locator('.close-sidebar').click();
      }
      await shot('statistics');
      await page.goto(new URL('settings.html', site).href);
      await page.waitForSelector('#saveSettings');await shot('settings');
      assert.match(await page.locator('.browser-preferences-note').textContent(), /only in this browser/);
      await page.locator('#authorInput').fill('Browser-only test author');
      await page.locator('#addAuthor').click();await page.locator('#saveSettings').click();
      await page.reload();
      assert.match(await page.locator('#selectedAuthors').textContent(), /Browser-only test author/);
      if (width === 1440) {
        await page.goto(new URL('index.html', site).href);await ready(page);
        if (await page.evaluate(() => getPreferredLanguage()) !== 'English') {
          await page.locator('header [data-ai-language="English"]').click();await finished(page);
        }
        const aiUrl = `${config.data}/data/${config.date}_AI_enhanced_Chinese.jsonl`;
        await page.route(aiUrl, route => route.fulfill({status: 404, body: ''}));
        await page.locator('header [data-ai-language="Chinese"]').click();await finished(page);
        assert.equal(await page.locator('.paper-card').count(), rawIds.size);
        assert.equal(await page.locator('.ai-summary-status').count(), rawIds.size);
        assert.equal(await page.evaluate(() => uniquePapers(paperData).every(paper => !paper.aiAvailable && paper.summary === paper.details)), true);
        await shot('missing-language');
        await page.unroute(aiUrl);
        const rawUrl = `${config.data}/data/${config.date}.jsonl`;
        await page.route(rawUrl, route => route.fulfill({status: 404, body: ''}));
        await page.locator('header [data-ai-language="English"]').click();await finished(page);
        assert.equal(await page.locator('.paper-card').count(), 0);
        await page.unroute(rawUrl);
        report.checks.push({scenario: 'Browser-only simulated AI 404 and raw 404', result: 'Missing AI shows every raw paper and its exact abstract; AI-only responses show no paper. No server data changed.'});
      }
      report.checks.push({width, rawIds: rawIds.size, config, passed: ['wrong and correct native login', 'namespaced authentication',
        'EN/ZH keyboard control', 'raw authoritative counts', 'retained detail', 'refresh language preference',
        'statistics dedup and retained sidebar', 'browser-only settings persistence', 'no horizontal overflow']});
      await context.close();
    }
    assert.deepEqual(report.pageErrors, []);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = redact(error.message, password);
    throw new Error(report.error);
  } finally {
    report.finished = new Date().toISOString();
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(redact(report, password), null, 2) + '\n');
    if (browser) await browser.close();
  }
  return {status: report.status, screenshots: report.screenshots.length};
}

module.exports = {validateSiteUrl, isSitePage, redact, runChecks};
if (require.main === module) {
  runChecks().then(result => console.log(JSON.stringify(result))).catch(error => {
    console.error(redact(error.message, process.env.ACCESS_PASSWORD));
    process.exitCode = 1;
  });
}

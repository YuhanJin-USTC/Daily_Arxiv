const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const crypto = require('node:crypto');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
const digest = password => crypto.createHash('sha256').update(password, 'utf8').digest('hex');
const password = '  Fictional 密码🔬 café  ';

function storage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    values
  };
}

function authContext(options = {}) {
  const browserStorage = options.storage || storage();
  const location = {pathname: options.pathname || '/chinese/login.html', search: '', href: ''};
  const context = vm.createContext({
    console, TextEncoder, Uint8Array, Date, URLSearchParams,
    window: {crypto: options.crypto, localStorage: browserStorage, location}
  });
  vm.runInContext(read('js/auth-config.js').replace('DISABLED_NO_PASSWORD_SET_IN_SECRETS', digest(password)), context);
  vm.runInContext(read('js/auth.js'), context);
  context.auth = vm.runInContext('Auth', context);
  context.config = vm.runInContext('AUTH_CONFIG', context);
  return context;
}

function loginContext(auth, search = '') {
  const handlers = {};
  const elements = {
    loginForm: {addEventListener: (event, handler) => { handlers[event] = handler; }, reportValidity: () => true},
    password: {value: password, focus() {}},
    rememberMe: {checked: true},
    errorMessage: {textContent: '', style: {}},
    loginButton: {disabled: true}
  };
  const location = {search, href: ''};
  const context = vm.createContext({Auth: auth, URLSearchParams, window: {location}, document: {getElementById: id => elements[id]}});
  vm.runInContext(read('js/login.js'), context);
  return {elements, location, handlers};
}

test('UTF-8 hashes agree with WebCrypto and preserve all password characters', async () => {
  for (const browserCrypto of [undefined, crypto.webcrypto, {subtle: {digest: async () => { throw new Error('blocked'); }}}]) {
    const ctx = authContext({crypto: browserCrypto});
    for (const value of [password, 'ASCII only', '虚构🔬', 'café', 'unpaired\ud800']) {
      assert.equal(await ctx.auth.hashPassword(value), digest(value));
    }
    assert.equal(await ctx.auth.login(password.trim()), false);
    assert.equal(await ctx.auth.login(password), true);
    assert.equal(ctx.auth.isAuthenticated(), true);
  }
});

test('two project paths keep independent sessions on one origin', async () => {
  const shared = storage();
  const chinese = authContext({storage: shared, pathname: '/chinese/login.html'});
  const english = authContext({storage: shared, pathname: '/english/index.html'});
  assert.notEqual(chinese.config.storageKey, english.config.storageKey);
  await chinese.auth.login(password);
  assert.equal(english.auth.isAuthenticated(), false);
  await english.auth.login(password);
  chinese.auth.logout();
  assert.equal(english.auth.isAuthenticated(), true);
});

test('storage read/write failures stay distinct from a wrong password', async () => {
  const readBlocked = authContext({storage: {getItem() {throw new Error('SecurityError');}}});
  assert.throws(() => readBlocked.auth.isAuthenticated(), {code: 'AUTH_STORAGE_UNAVAILABLE'});
  readBlocked.auth.requireAuth();
  assert.match(readBlocked.window.location.href, /error=storage/);
  const writeBlocked = authContext({storage: {...storage(), setItem() {throw new Error('QuotaExceededError');}}});
  assert.equal(await writeBlocked.auth.login('wrong fictional password'), false);
  await assert.rejects(writeBlocked.auth.login(password), {code: 'AUTH_STORAGE_UNAVAILABLE'});
  const page = loginContext(writeBlocked.auth);
  await page.handlers.submit({preventDefault() {}});
  assert.match(page.elements.errorMessage.textContent, /storage is unavailable/);
  assert.doesNotMatch(page.elements.errorMessage.textContent, /Invalid password/);
  assert.equal(page.location.href, '');
});

test('invalid expiration and a changed configured password cannot authenticate', async () => {
  const ctx = authContext();
  await ctx.auth.login(password);
  ctx.window.localStorage.setItem(ctx.config.storageExpireKey, 'not-a-date');
  assert.equal(ctx.auth.isAuthenticated(), false);
  await ctx.auth.login(password);
  ctx.config.passwordHash = digest('different fictional password');
  assert.equal(ctx.auth.isAuthenticated(), false);
});

test('native Enter and button submits invoke login once while a request is pending', async () => {
  let finish;
  let calls = 0;
  const page = loginContext({isAuthenticated: () => false, login: value => {
    assert.equal(value, password);
    calls++;
    return new Promise(resolve => {finish = resolve;});
  }});
  let prevented = 0;
  const first = page.handlers.submit({preventDefault() {prevented++;}});
  const second = page.handlers.submit({preventDefault() {prevented++;}});
  assert.equal(calls, 1);
  assert.equal(page.elements.loginButton.disabled, true);
  finish(false);
  await Promise.all([first, second]);
  assert.equal(prevented, 2);
  assert.equal(page.elements.password.value, password);
  assert.equal(page.elements.loginButton.disabled, false);
  assert.match(page.elements.errorMessage.textContent, /Invalid password/);
  assert.deepEqual(Object.keys(page.handlers), ['submit']);
  assert.doesNotMatch(read('js/login.js') + read('login.html'), /keypress|dispatchEvent/);
});

test('storage failure during page load still installs a guarded form handler', async () => {
  const auth = {isAuthenticated() {throw Object.assign(new Error(), {code: 'AUTH_STORAGE_UNAVAILABLE'});}, async login() {throw Object.assign(new Error(), {code: 'AUTH_STORAGE_UNAVAILABLE'});}};
  const page = loginContext(auth);
  let prevented = false;
  await page.handlers.submit({preventDefault() {prevented = true;}});
  assert.equal(prevented, true);
  assert.match(page.elements.errorMessage.textContent, /storage is unavailable/);
  assert.match(read('login.html'), /<form[^>]*method="post"/);
  assert.match(read('login.html'), /<button[^>]*id="loginButton"[^>]*disabled/);
});

test('a protected-page storage failure shows a message without a redirect loop', () => {
  const auth = {isAuthenticated() {throw new Error('must not retry the blocked storage');}};
  const page = loginContext(auth, '?redirect=index.html&error=storage');
  assert.equal(page.location.href, '');
  assert.match(page.elements.errorMessage.textContent, /storage is unavailable/);
  assert.equal(page.elements.loginButton.disabled, false);
});

test('successful sign-in redirects only within the current project', async () => {
  for (const [search, expected] of [['?redirect=statistic.html', 'statistic.html'], ['?redirect=https://example.org', 'index.html'], ['?redirect=../english/', 'index.html']]) {
    const page = loginContext({isAuthenticated: () => false, login: async () => true}, search);
    await page.handlers.submit({preventDefault() {}});
    assert.equal(page.location.href, expected);
    assert.equal(page.elements.loginButton.disabled, true);
  }
});

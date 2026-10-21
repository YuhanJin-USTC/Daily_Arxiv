const form = document.getElementById('loginForm');
const passwordInput = document.getElementById('password');
const rememberMe = document.getElementById('rememberMe');
const errorMessage = document.getElementById('errorMessage');
const loginButton = document.getElementById('loginButton');
const parameters = new URLSearchParams(window.location.search);
const requestedPage = parameters.get('redirect');
const redirect = ['index.html', 'statistic.html', 'settings.html'].includes(requestedPage)
    ? requestedPage : 'index.html';
let submitting = false;

function showLoginError(error) {
    errorMessage.textContent = error && error.code === 'AUTH_STORAGE_UNAVAILABLE'
        ? 'Browser storage is unavailable. Allow site storage and try again.'
        : 'Sign-in could not be completed. Reload this page and try again.';
    errorMessage.style.display = 'block';
}

form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || !form.reportValidity()) return;
    submitting = true;
    loginButton.disabled = true;
    errorMessage.style.display = 'none';
    let redirecting = false;
    try {
        if (await Auth.login(passwordInput.value, rememberMe.checked)) {
            window.location.href = redirect;
            redirecting = true;
        } else {
            errorMessage.textContent = 'Invalid password. Check the password and this site address, then try again.';
            errorMessage.style.display = 'block';
            passwordInput.focus();
        }
    } catch (error) {
        showLoginError(error);
    } finally {
        submitting = redirecting;
        loginButton.disabled = redirecting;
    }
});

loginButton.disabled = false;
try {
    if (parameters.get('error') === 'storage') {
        showLoginError({code: 'AUTH_STORAGE_UNAVAILABLE'});
    } else if (Auth.isAuthenticated()) {
        window.location.href = redirect;
    }
} catch (error) {
    showLoginError(error);
}

const DEMO_MODE = false;
const LOGIN_URL = '/api/login';
const REDIRECT_TO = '/';
const REQUEST_TIMEOUT_MS = 10000;
const STORAGE_KEY = 'biringan_code';

const card = document.getElementById('login-card');
const form = document.getElementById('login-form');
const codeInput = document.getElementById('employee-code');
const passwordInput = document.getElementById('password');
const rememberBox = document.getElementById('remember');
const toggleBtn = document.getElementById('toggle-password');
const loginBtn = document.getElementById('login-btn');
const loginLabel = document.getElementById('login-label');
const loginIcon = document.getElementById('login-icon');
const loginSpinner = document.getElementById('login-spinner');
const alertBox = document.getElementById('login-alert');
const alertText = document.getElementById('alert-text');
const alertIcon = document.getElementById('alert-icon');
const codeError = document.getElementById('code-error');
const passwordError = document.getElementById('password-error');
const capsWarning = document.getElementById('caps-warning');

// ---------------------------------------------------------------- Helpers
// Turns anything typed or pasted into "biri-123456" (digits only, max 6).
function formatCode(raw) {
    const digits = String(raw).replace(/\D/g, '').slice(0, 6);
    return digits ? 'biri-' + digits : '';
}

function showAlert(message, type = 'error') {
    alertText.textContent = message;
    alertBox.classList.toggle('success', type !== 'error');
    alertIcon.className = type === 'error'
        ? 'fas fa-circle-exclamation'
        : type === 'info' ? 'fas fa-circle-info' : 'fas fa-circle-check';
    alertBox.hidden = false;
}

function hideAlert() {
    alertBox.hidden = true;
}

function shakeCard() {
    card.classList.remove('shake');
    void card.offsetWidth;          // restart the animation
    card.classList.add('shake');
}

function setLoading(on, label) {
    loginBtn.disabled = on;
    loginSpinner.hidden = !on;
    loginIcon.hidden = on;
    loginLabel.textContent = label || (on ? 'Logging in...' : 'Log In');
}

function clearFieldError(input, errorEl) {
    input.classList.remove('invalid');
    errorEl.textContent = '';
}

// ---------------------------------------------------------------- Remembered ID
try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        codeInput.value = formatCode(saved);
        rememberBox.checked = true;
        passwordInput.focus();      // ID already filled, so jump to the password
    }
} catch (e) { /* storage unavailable */ }

// ---------------------------------------------------------------- Input behaviour
codeInput.addEventListener('input', () => {
    const formatted = formatCode(codeInput.value);
    if (codeInput.value !== formatted) codeInput.value = formatted;
    clearFieldError(codeInput, codeError);
    hideAlert();
});

passwordInput.addEventListener('input', () => {
    clearFieldError(passwordInput, passwordError);
    hideAlert();
});

// Caps Lock warning on the password field
function checkCaps(e) {
    if (typeof e.getModifierState !== 'function') return;
    capsWarning.hidden = !e.getModifierState('CapsLock');
}
passwordInput.addEventListener('keydown', checkCaps);
passwordInput.addEventListener('keyup', checkCaps);
passwordInput.addEventListener('blur', () => { capsWarning.hidden = true; });

toggleBtn.addEventListener('click', () => {
    const show = passwordInput.type === 'password';
    passwordInput.type = show ? 'text' : 'password';
    toggleBtn.querySelector('i').className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
    toggleBtn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    passwordInput.focus();
});

document.getElementById('forgot-link').addEventListener('click', (e) => {
    e.preventDefault();
    showAlert('Please contact your administrator to reset your password.', 'info');
});

// ---------------------------------------------------------------- Validation
function validate() {
    const code = codeInput.value.trim();
    const password = passwordInput.value;
    let firstBad = null;

    clearFieldError(codeInput, codeError);
    clearFieldError(passwordInput, passwordError);

    if (!code) {
        codeError.textContent = 'Employee ID is required.';
        firstBad = codeInput;
    } else if (!/^biri-\d{6}$/i.test(code)) {
        codeError.textContent = 'Enter all 6 digits of your Employee ID.';
        firstBad = codeInput;
    }
    if (firstBad) codeInput.classList.add('invalid');

    if (!password) {
        passwordError.textContent = 'Password is required.';
        passwordInput.classList.add('invalid');
        firstBad = firstBad || passwordInput;
    }

    if (firstBad) {
        firstBad.focus();
        shakeCard();
        return false;
    }
    return true;
}

// ---------------------------------------------------------------- Submit
async function sendLogin(code, password) {
    if (DEMO_MODE) return { success: true };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
        const res = await fetch(LOGIN_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employee_code: code, password }),
            signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok && !data.message) {
            data.success = false;
            data.message = res.status >= 500
                ? 'Server error. Please try again in a moment.'
                : 'Login failed (' + res.status + ').';
        }
        return data;
    } finally {
        clearTimeout(timer);
    }
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (loginBtn.disabled) return;      // block double submits
    hideAlert();
    if (!validate()) return;

    const code = codeInput.value.trim().toLowerCase();
    const password = passwordInput.value;

    setLoading(true);
    let redirecting = false;

    try {
        const result = await sendLogin(code, password);

        if (!result.success) {
            showAlert(result.message || 'Invalid employee ID or password.');
            shakeCard();
            passwordInput.select();
            return;
        }

        try {
            if (rememberBox.checked) localStorage.setItem(STORAGE_KEY, code);
            else localStorage.removeItem(STORAGE_KEY);
        } catch (err) { /* ignore */ }

        redirecting = true;
        showAlert('Login successful. Redirecting...', 'success');
        setLoading(true, 'Redirecting...');
        setTimeout(() => { window.location.href = result.redirect || REDIRECT_TO; }, 600);
    } catch (err) {
        showAlert(err.name === 'AbortError'
            ? 'The server took too long to respond. Please try again.'
            : 'Could not reach the server. Please try again.');
        shakeCard();
    } finally {
        if (!redirecting) setLoading(false);   // stay disabled while redirecting
    }
});
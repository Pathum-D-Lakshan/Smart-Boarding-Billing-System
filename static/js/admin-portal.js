/* Native centered dialogs progressively enhance the same protected GET/POST forms. */
(() => {
    const dialog = document.getElementById('admin-dialog');
    const content = document.getElementById('admin-dialog-content');
    if (!dialog || !content || typeof dialog.showModal !== 'function') return;
    let opener = null, generation = 0, saving = false;
    function clearPasswords() {
        content.querySelectorAll('input[name="current_password"]').forEach(field => { field.value = ''; field.type = 'password'; });
    }
    function focusContent() {
        const target = content.querySelector('.admin-errors') || content.querySelector('#admin-record-title');
        target?.focus();
    }
    async function load(url, options = {}) {
        const current = ++generation;
        const response = await fetch(url, { ...options, credentials: 'same-origin', headers: { 'X-Requested-With': 'AdminDialog' } });
        if (current !== generation) return;
        if (response.redirected) { window.location.assign(response.url); return; }
        if (![200,400,409,429].includes(response.status)) throw new Error('Could not load these details.');
        const html = await response.text();
        if (current !== generation) return;
        clearPasswords();
        content.innerHTML = html;
        if (!dialog.open) dialog.showModal();
        focusContent();
    }
    document.addEventListener('click', async event => {
        const eye = event.target.closest('[data-admin-eye]');
        if (eye) {
            const field = document.getElementById(eye.getAttribute('aria-controls'));
            if (!field) return;
            const show = field.type === 'password'; field.type = show ? 'text' : 'password';
            eye.setAttribute('aria-pressed', String(show)); eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            return;
        }
        if (event.target.closest('[data-admin-close]')) { dialog.close(); return; }
        const link = event.target.closest('a[data-admin-open]');
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || saving) return;
        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        event.preventDefault(); opener = dialog.open ? opener : link;
        try { await load(url.href); } catch { window.location.assign(url.href); }
    });
    document.addEventListener('submit', async event => {
        const form = event.target;
        if (!form.matches('[data-admin-decision]') || !dialog.open) return;
        event.preventDefault();
        if (saving || !form.reportValidity()) return;
        saving = true;
        const submit = form.querySelector('button[type="submit"]');
        const body = new FormData(form);
        if (submit) submit.disabled = true;
        try { await load(form.action, { method: 'POST', body }); }
        catch {
            clearPasswords();
            const message = document.createElement('p'); message.className = 'admin-errors';
            message.setAttribute('role', 'alert');
            message.textContent = 'Could not confirm the outcome. Reload this record before submitting again.';
            content.prepend(message);
        } finally { saving = false; if (submit?.isConnected) submit.disabled = false; }
    });
    dialog.addEventListener('close', () => { generation++; clearPasswords(); opener?.focus(); });
    window.addEventListener('pageshow', event => { clearPasswords(); if (event.persisted) window.location.reload(); });
})();

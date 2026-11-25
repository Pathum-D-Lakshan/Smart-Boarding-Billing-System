(() => {
    const native = typeof document.createElement('dialog').showModal === 'function';
    let modal = null, body = null, closer = null, opener = null, scroll = null;
    let requestNumber = 0, posting = false, restore = null;
    function clearPasswords(root) {
        for (const input of root.querySelectorAll('input[name="current_password"]')) { input.value = ''; input.type = 'password'; }
        for (const button of root.querySelectorAll('[data-pay-eye]')) { button.setAttribute('aria-label', 'Show password'); button.setAttribute('aria-pressed', 'false'); }
    }
    function bind(root) {
        for (const eye of root.querySelectorAll('[data-pay-eye]')) {
            if (eye.dataset.bound) continue;
            eye.dataset.bound = 'true'; eye.hidden = false;
            eye.addEventListener('click', () => {
                const input = document.getElementById(eye.dataset.payEye);
                const show = input.type === 'password'; input.type = show ? 'text' : 'password';
                eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); eye.setAttribute('aria-pressed', String(show));
            });
        }
        if (native) for (const cancel of root.querySelectorAll('[data-maintenance-close]')) {
            cancel.addEventListener('click', event => { event.preventDefault(); hide(); });
        }
    }
    function hide() { if (!posting && modal?.open) modal.close(); }
    function ensureModal() {
        if (modal) return;
        modal = document.createElement('dialog'); modal.className = 'maint-dialog'; modal.setAttribute('aria-labelledby', 'maintenance-dialog-title');
        const header = document.createElement('header'); header.className = 'maint-dialog-header';
        const title = document.createElement('h2'); title.id = 'maintenance-dialog-title'; title.textContent = 'Maintenance Details';
        closer = document.createElement('button'); closer.type = 'button'; closer.className = 'maint-button maint-dialog-close'; closer.textContent = '\u00d7'; closer.setAttribute('aria-label', 'Close Maintenance Details');
        closer.addEventListener('click', hide); header.append(title, closer);
        body = document.createElement('div'); body.className = 'maint-dialog-content'; modal.append(header, body); document.body.append(modal);
        modal.addEventListener('cancel', event => { event.preventDefault(); hide(); });
        modal.addEventListener('click', event => { const box = modal.getBoundingClientRect(); if (event.target === modal && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) hide(); });
        modal.addEventListener('close', () => {
            if (modal.open) return;
            ++requestNumber; clearPasswords(modal);
            // Native-dialog dismissal must not reveal a second inline form.
            // Browsers without dialog support never hide the fallback markup.
            if (restore) { restore.replaceChildren(); restore.hidden = true; restore = null; }
            document.body.removeAttribute('data-maintenance-dialog-open');
            if (opener?.isConnected) opener.focus({preventScroll: true});
            if (scroll && typeof window.scrollTo === 'function') window.scrollTo(scroll.x, scroll.y);
        });
    }
    function show(trigger) {
        ensureModal(); opener = trigger; scroll = {x: window.scrollX || 0, y: window.scrollY || 0};
        if (!modal.open) modal.showModal(); document.body.setAttribute('data-maintenance-dialog-open', ''); closer.focus();
    }
    async function load(address, trigger, alreadyOpen = false) {
        const endpoint = new URL(address, window.location.href);
        if (endpoint.origin !== window.location.origin || posting) return;
        ensureModal(); const ticket = ++requestNumber;
        if (!alreadyOpen) show(trigger);
        clearPasswords(body); body.textContent = 'Loading maintenance details...';
        try {
            const response = await window.fetch(endpoint.href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Maintenance-Modal': '1'}});
            const payload = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
            if (ticket !== requestNumber || !modal.open) return;
            if (!response.ok || !payload?.html) throw new Error(payload?.error || 'Could not load details. Close and refresh maintenance history.');
            body.innerHTML = payload.html; bind(body);
            document.getElementById('maintenance-dialog-title').textContent = payload.title || 'Maintenance Details';
            (body.querySelector('[aria-invalid="true"]') || body.querySelector('.maint-detail') || closer).focus({preventScroll: true});
        } catch (error) { if (ticket === requestNumber && modal.open) body.textContent = error.message; }
    }
    document.addEventListener('click', event => {
        const link = event.target.closest?.('[data-maintenance-view]');
        if (!link || !native || typeof window.fetch !== 'function' || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const endpoint = new URL(link.getAttribute('href'), window.location.href);
        if (endpoint.origin !== window.location.origin) return;
        event.preventDefault(); load(endpoint.href, modal?.open ? opener : link, !!modal?.open);
    });
    document.addEventListener('submit', event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (!form.matches?.('[data-maintenance-post]')) return;
        if (posting || form.dataset.maintenanceSubmitting) { event.preventDefault(); return; }
        const endpoint = new URL(form.getAttribute('action'), window.location.href);
        if (endpoint.origin !== window.location.origin) { event.preventDefault(); clearPasswords(form); return; }
        // Keep actual inputs enabled until the browser serializes the native POST.
        // Mutations never auto-retry: an uncertain outcome requires reading history.
        posting = true; form.dataset.maintenanceSubmitting = 'true'; if (closer) closer.disabled = true;
        for (const button of form.querySelectorAll('button[type="submit"]')) { button.dataset.maintenanceLabel = button.textContent; button.disabled = true; button.textContent = 'Saving...'; }
    });
    bind(document);
    const initial = document.querySelector('[data-maintenance-initial]');
    if (initial && native) {
        show(null); restore = initial; body.replaceChildren(...initial.childNodes); initial.hidden = true;
        (body.querySelector('[aria-invalid="true"]') || body.querySelector('.maint-detail') || closer).focus({preventScroll: true});
    }
    window.addEventListener('pagehide', () => clearPasswords(document));
    window.addEventListener('pageshow', () => {
        posting = false; clearPasswords(document); if (closer) closer.disabled = false;
        for (const form of document.querySelectorAll('[data-maintenance-submitting]')) delete form.dataset.maintenanceSubmitting;
        for (const button of document.querySelectorAll('[data-maintenance-label]')) { button.disabled = false; button.textContent = button.dataset.maintenanceLabel; delete button.dataset.maintenanceLabel; }
    });
})();

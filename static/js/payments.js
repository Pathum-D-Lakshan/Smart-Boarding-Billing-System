(() => {
    const native = typeof document.createElement('dialog').showModal === 'function';
    let modal = null, body = null, closer = null, opener = null, scroll = null;
    let requestNumber = 0, posting = false, restore = null;
    function clearPasswords(root) {
        for (const input of root.querySelectorAll('input[name="current_password"]')) { input.value = ''; input.type = 'password'; }
        for (const button of root.querySelectorAll('[data-pay-eye]')) { button.setAttribute('aria-label', 'Show password'); button.setAttribute('aria-pressed', 'false'); }
    }
    function bindFilePicker(input) {
        const field = input.parentElement;
        const error = field.querySelector('[data-pay-file-error]');
        const filename = field.querySelector('[data-pay-file-name]');
        const preview = field.querySelector('[data-pay-file-preview]');
        const remove = field.querySelector('[data-pay-file-remove]');

        function update(removed = false) {
            const file = input.files?.[0];
            let message = '';
            if (file && !/\.(?:jpe?g|png|pdf)$/i.test(file.name)) message = 'Choose a JPG, JPEG, PNG or static PDF bank slip.';
            else if (file && (!file.size || file.size > Number(input.dataset.maxBytes))) message = 'Choose a non-empty slip within the displayed upload-size limit.';
            input.setCustomValidity(message);
            input.setAttribute('aria-invalid', String(Boolean(message)));
            if (error) error.textContent = message;
            if (filename) {
                filename.textContent = removed ? 'Slip removed. Choose another file.' : file && !message ? `Selected file: ${file.name}` : '';
                filename.hidden = !filename.textContent;
            }
            if (remove) remove.hidden = !file;
            if (!preview) return;
            preview.hidden = true;
            preview.removeAttribute('src');
            if (!file || message || !/\.(?:jpe?g|png)$/i.test(file.name) || !window.FileReader) return;
            const reader = new window.FileReader();
            reader.addEventListener('load', () => {
                // A previous read may finish after the user removes or replaces it.
                if (input.files?.[0] === file) preview.setAttribute('src', reader.result);
            });
            reader.readAsDataURL(file);
        }

        preview?.addEventListener('load', () => { preview.hidden = !preview.getAttribute('src'); });
        preview?.addEventListener('error', () => { preview.hidden = true; });
        input.addEventListener('change', () => update());
        remove?.addEventListener('click', () => {
            if (posting) return;
            input.value = '';
            update(true);
            input.focus();
        });
    }
    function bind(root) {
        for (const button of root.querySelectorAll('[data-bank-copy]')) button.hidden = false;
        for (const qr of root.querySelectorAll('[data-upload-qr]')) {
            if (qr.dataset.bound) continue;
            qr.dataset.bound = 'true';
            const seconds = Math.max(0, Math.min(900, Number(qr.dataset.expiresSeconds) || 0));
            const deadline = Date.now() + seconds * 1000;
            function tick() {
                if (qr.dataset.expired || qr.isConnected === false) return;
                const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
                const status = qr.querySelector('[data-qr-expiry-status]');
                if (status) status.textContent = `One-time link · ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')} remaining`;
                if (remaining) window.setTimeout(tick, 1000);
            }
            window.setTimeout(() => {
                qr.dataset.expired = 'true';
                const status = qr.querySelector('[data-qr-expiry-status]');
                if (status) status.textContent = 'This upload link has expired. Close this window and create a new QR code.';
                const image = qr.querySelector('img'); if (image) image.removeAttribute('src');
                const input = qr.querySelector('#secure-mobile-link'); if (input) input.value = '';
                const share = qr.querySelector('[data-qr-whatsapp]'); if (share) { share.removeAttribute('href'); share.setAttribute('aria-disabled', 'true'); }
                for (const button of qr.querySelectorAll('[data-bank-copy]')) button.disabled = true;
            }, seconds * 1000);
            tick();
        }
        for (const eye of root.querySelectorAll('[data-pay-eye]')) {
            if (eye.dataset.bound) continue;
            eye.dataset.bound = 'true'; eye.hidden = false;
            eye.addEventListener('click', () => {
                const input = document.getElementById(eye.dataset.payEye);
                const show = input.type === 'password'; input.type = show ? 'text' : 'password';
                eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); eye.setAttribute('aria-pressed', String(show));
            });
        }
        const decisions = root.querySelectorAll('[data-pay-decision]');
        const buttons = root.querySelector('[data-pay-decision-buttons]');
        if (buttons) buttons.hidden = false;
        for (const section of decisions) { section.hidden = !section.open; }
        for (const button of root.querySelectorAll('[data-pay-open]')) button.addEventListener('click', () => {
            if (posting) return;
            clearPasswords(root);
            for (const section of decisions) { section.open = section.dataset.payDecision === button.dataset.payOpen; section.hidden = !section.open; }
            root.querySelector('[data-pay-decision]:not([hidden]) input[name="current_password"]')?.focus();
        });
        for (const back of root.querySelectorAll('[data-pay-back]')) {
            back.hidden = false;
            back.addEventListener('click', () => { if (posting) return; clearPasswords(root); for (const section of decisions) { section.hidden = true; section.open = false; } buttons?.querySelector('button')?.focus(); });
        }
        if (native) for (const cancel of root.querySelectorAll('[data-pay-close]')) {
            cancel.hidden = false;
            cancel.addEventListener('click', event => {
                if (modal?.open) { event.preventDefault(); hide(); }
            });
        }
        for (const input of root.querySelectorAll('[data-pay-file]')) bindFilePicker(input);
    }
    function hide() { if (!posting && modal?.open) modal.close(); }
    function ensureModal() {
        if (modal) return;
        modal = document.createElement('dialog'); modal.className = 'pay-dialog'; modal.setAttribute('aria-labelledby', 'payment-dialog-title');
        const header = document.createElement('header'); header.className = 'pay-dialog-header';
        const title = document.createElement('h2'); title.id = 'payment-dialog-title'; title.textContent = 'Payment Details';
        closer = document.createElement('button'); closer.type = 'button'; closer.className = 'pay-button pay-dialog-close'; closer.textContent = '\u00d7'; closer.setAttribute('aria-label', 'Close Payment Details');
        closer.addEventListener('click', hide); header.append(title, closer);
        body = document.createElement('div'); body.className = 'pay-dialog-content'; modal.append(header, body); document.body.append(modal);
        modal.addEventListener('cancel', event => { event.preventDefault(); hide(); });
        modal.addEventListener('click', event => { const box = modal.getBoundingClientRect(); if (event.target === modal && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) hide(); });
        modal.addEventListener('close', () => {
            if (modal.open) return;
            ++requestNumber; clearPasswords(modal);
            if (restore) { restore.replaceChildren(...body.childNodes); restore.hidden = false; restore = null; }
            document.body.removeAttribute('data-payment-dialog-open');
            if (opener?.isConnected) opener.focus({preventScroll: true});
            if (scroll && typeof window.scrollTo === 'function') window.scrollTo(scroll.x, scroll.y);
        });
    }
    function show(trigger) {
        ensureModal(); opener = trigger; scroll = {x: window.scrollX || 0, y: window.scrollY || 0};
        if (!modal.open) modal.showModal(); document.body.setAttribute('data-payment-dialog-open', ''); closer.focus();
    }
    function renderPayload(payload) {
        body.innerHTML = payload.html; bind(body);
        const kind = ['qr', 'bank', 'submission', 'withdrawal'].includes(payload.modal_kind) ? payload.modal_kind : '';
        modal.className = 'pay-dialog' + (kind ? ' pay-dialog-' + kind : '');
        document.getElementById('payment-dialog-title').textContent = payload.title || 'Payment Details';
        (body.querySelector('[aria-invalid="true"]') || body.querySelector('.pay-detail') || closer).focus({preventScroll: true});
    }
    async function createQR(form) {
        if (posting) return;
        const endpoint = new URL(form.getAttribute('action'), window.location.href);
        if (endpoint.origin !== window.location.origin) return;
        const values = new window.FormData(form);
        if (!modal?.open) show(form.querySelector('button[type="submit"]'));
        else ensureModal();
        const ticket = ++requestNumber;
        posting = true; closer.disabled = true; modal.className = 'pay-dialog pay-dialog-qr';
        body.textContent = 'Checking secure mobile connection…';
        try {
            const response = await window.fetch(endpoint.href, {method: 'POST', body: values, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Payment-Modal': '1'}});
            const payload = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
            if (ticket !== requestNumber || !modal.open) return;
            // Validation responses include the safe retry/device-upload controls.
            if (payload?.html) renderPayload(payload);
            else throw new Error(payload?.error || 'Could not create QR. Refresh My Payments and try again.');
        } catch (error) { if (ticket === requestNumber && modal.open) body.textContent = error.message; }
        finally { posting = false; closer.disabled = false; }
    }
    async function load(address, trigger, alreadyOpen = false) {
        const endpoint = new URL(address, window.location.href);
        if (endpoint.origin !== window.location.origin || posting) return;
        ensureModal(); const ticket = ++requestNumber;
        if (!alreadyOpen) show(trigger);
        clearPasswords(body); body.textContent = 'Loading payment details...';
        try {
            const response = await window.fetch(endpoint.href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Payment-Modal': '1'}});
            const payload = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
            if (ticket !== requestNumber || !modal.open) return;
            if (!response.ok || !payload?.html) throw new Error(payload?.error || 'Could not load details. Close and refresh payment history.');
            renderPayload(payload);
        } catch (error) { if (ticket === requestNumber && modal.open) body.textContent = error.message; }
    }
    document.addEventListener('click', async event => {
        const copy = event.target.closest?.('[data-bank-copy]');
        if (copy) {
            event.preventDefault();
            const field = document.getElementById(copy.dataset.bankCopy);
            const feedback = document.getElementById(copy.dataset.copyStatus);
            if (!field || !feedback) return;
            try {
                if (!window.navigator?.clipboard?.writeText) throw new Error('Clipboard unavailable');
                await window.navigator.clipboard.writeText(field.value);
                feedback.textContent = (copy.dataset.copyLabel || 'Account number') + ' copied.';
            } catch {
                const disclosure = field.closest('details'); if (disclosure) disclosure.open = true;
                field.focus(); field.select();
                feedback.textContent = (copy.dataset.copyLabel || 'Account number') + ' selected. Copy it manually.';
            }
            return;
        }
        if (event.target.closest?.('[data-payment-print]')) { event.preventDefault(); window.print(); return; }
        const link = event.target.closest?.('[data-payment-view]');
        if (!link || !native || typeof window.fetch !== 'function' || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const endpoint = new URL(link.getAttribute('href'), window.location.href);
        if (endpoint.origin !== window.location.origin) return;
        event.preventDefault(); load(endpoint.href, link);
    });
    document.addEventListener('submit', event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (form.matches?.('[data-payment-qr]') && native && typeof window.fetch === 'function') {
            event.preventDefault(); createQR(form); return;
        }
        if ((form.matches?.('[data-pay-cash-select]') || form.matches?.('[data-pay-bill-select]')) && native && modal?.open && typeof window.fetch === 'function') {
            event.preventDefault(); const endpoint = new URL(form.getAttribute('action'), window.location.href);
            endpoint.search = new URLSearchParams(new window.FormData(form)).toString(); load(endpoint.href, opener, true); return;
        }
        if (!form.matches?.('[data-payment-post]')) return;
        if (posting || form.dataset.paymentSubmitting) { event.preventDefault(); return; }
        const endpoint = new URL(form.getAttribute('action'), window.location.href);
        if (endpoint.origin !== window.location.origin) { event.preventDefault(); clearPasswords(form); return; }
        // Keep actual inputs enabled until the browser serializes the native POST.
        // Mutations never auto-retry: an uncertain outcome requires reading history.
        posting = true; form.dataset.paymentSubmitting = 'true'; if (closer) closer.disabled = true;
        for (const button of form.querySelectorAll('button[type="submit"]')) { button.dataset.paymentLabel = button.textContent; button.disabled = true; button.textContent = 'Saving...'; }
    });
    bind(document);
    const initial = document.querySelector('[data-payment-initial]');
    if (initial && native) {
        show(null); restore = initial; body.replaceChildren(...initial.childNodes); initial.hidden = true;
        document.getElementById('payment-dialog-title').textContent = initial.dataset.paymentTitle || 'Payment Details';
        if (body.querySelector('[data-upload-qr]')) modal.className = 'pay-dialog pay-dialog-qr';
        (body.querySelector('[aria-invalid="true"]') || body.querySelector('.pay-detail') || closer).focus({preventScroll: true});
    }
    window.addEventListener('pagehide', () => clearPasswords(document));
    window.addEventListener('pageshow', () => {
        posting = false; clearPasswords(document); if (closer) closer.disabled = false;
        for (const form of document.querySelectorAll('[data-payment-submitting]')) delete form.dataset.paymentSubmitting;
        for (const button of document.querySelectorAll('[data-payment-label]')) { button.disabled = false; button.textContent = button.dataset.paymentLabel; delete button.dataset.paymentLabel; }
    });
})();

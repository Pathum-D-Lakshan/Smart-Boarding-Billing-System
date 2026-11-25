(() => {
    const nativeDialogs = typeof document.createElement('dialog').showModal === 'function';
    const preview = document.getElementById('bill-preview-form');
    const generate = document.getElementById('bill-generate-form');
    const status = document.getElementById('bill-preview-status');
    let activeDialog = null, posting = false, previewGeneration = 0, previewTimer;
    const sources = new Map();

    function clearPasswords(root) {
        for (const input of root.querySelectorAll('input[name="current_password"]')) {
            input.value = ''; input.type = 'password';
        }
        for (const button of root.querySelectorAll('[data-bill-eye]')) {
            button.setAttribute('aria-pressed', 'false'); button.setAttribute('aria-label', 'Show password');
        }
    }
    function eyes(root) {
        for (const button of root.querySelectorAll('[data-bill-eye]')) {
            if (button.dataset.bound) continue;
            button.dataset.bound = 'true'; button.hidden = false;
            button.addEventListener('click', () => {
                const input = document.getElementById(button.dataset.billEye);
                const show = input.type === 'password'; input.type = show ? 'text' : 'password';
                button.setAttribute('aria-pressed', String(show));
                button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            });
        }
    }
    function chosen() {
        return preview ? [...preview.querySelectorAll('input[name="selected_ids"]')].filter(input => input.checked && !input.disabled).map(input => input.value) : [];
    }
    function putSelection(form, ids) {
        const holder = form.querySelector('[data-bill-selected-fields]');
        if (!holder) return;
        holder.replaceChildren();
        for (const [name, value] of [['selection_empty', '1'], ...ids.map(id => ['selected_ids', id])]) {
            const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; holder.append(input);
        }
    }
    function dialog(title, id, onClose) {
        const element = document.createElement('dialog'); element.className = 'bill-dialog';
        element.setAttribute('aria-labelledby', id);
        const header = document.createElement('header'); header.className = 'bill-dialog-header';
        const heading = document.createElement('h2'); heading.id = id; heading.textContent = title;
        const close = document.createElement('button'); close.type = 'button'; close.className = 'bill-button bill-dialog-close';
        close.setAttribute('aria-label', 'Close ' + title); close.textContent = '\u00d7';
        header.append(heading, close);
        const body = document.createElement('div'); body.className = 'bill-dialog-content';
        element.append(header, body); document.body.append(element);
        let opener = null, scroll = null;
        function hide() { if (!posting && element.open) element.close(); }
        close.addEventListener('click', hide);
        element.addEventListener('cancel', event => { event.preventDefault(); hide(); });
        element.addEventListener('click', event => {
            const box = element.getBoundingClientRect();
            if (event.target === element && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) hide();
        });
        element.addEventListener('close', () => {
            if (element.open) return;
            clearPasswords(element); if (onClose) onClose(body);
            if (activeDialog === element) activeDialog = null;
            document.body.removeAttribute('data-bill-dialog-open');
            if (opener?.isConnected) opener.focus({preventScroll: true});
            if (scroll && typeof window.scrollTo === 'function') window.scrollTo(scroll.x, scroll.y);
        });
        return {element, body, close, hide, show(trigger) {
            if (posting) return;
            if (activeDialog && activeDialog !== element) activeDialog.close();
            opener = trigger; scroll = {x: window.scrollX || 0, y: window.scrollY || 0};
            if (!element.open) element.showModal(); activeDialog = element;
            document.body.setAttribute('data-bill-dialog-open', '');
            const invalid = body.querySelector('[aria-invalid="true"]');
            const field = body.querySelector('input:not([type="hidden"]), select, textarea');
            (invalid || field || close).focus();
        }};
    }
    if (nativeDialogs) for (const source of document.querySelectorAll('[data-bill-modal]')) {
        const summary = source.querySelector('summary');
        const section = source.querySelector('section');
        const button = document.createElement('button'); button.type = 'button'; button.className = summary.className || 'bill-button bill-secondary'; button.textContent = summary.textContent;
        const modal = dialog(summary.textContent, 'bill-modal-' + source.dataset.billModal);
        modal.body.append(section); source.before(button); const wasOpen = source.open; source.hidden = true;
        for (const cancel of section.querySelectorAll('[data-bill-cancel]')) { cancel.hidden = false; cancel.addEventListener('click', modal.hide); }
        button.addEventListener('click', () => {
            for (const form of section.querySelectorAll('[data-bill-selection-form]')) putSelection(form, chosen());
            modal.show(button);
        });
        sources.set(source.dataset.billModal, {button, modal});
        if (wasOpen) modal.show(button);
    }
    eyes(document);
    for (const form of document.querySelectorAll('[data-bill-adjustment]')) {
        const apply = form.querySelector('[name="apply_to"]');
        const targets = form.querySelector('[data-bill-targets]');
        const targetInput = form.querySelector('[name="targets"]');
        const recurrence = form.querySelector('[name="recurrence"]');
        const end = form.querySelector('[data-bill-recurrence-end]');
        const valueType = form.querySelector('[name="value_type"]');
        function update() {
            targets.hidden = apply.value !== 'selected'; targetInput.required = apply.value === 'selected';
            if (end) { end.hidden = recurrence.value !== 'monthly'; end.querySelector('input').required = recurrence.value === 'monthly'; }
            if (valueType) form.querySelector('[name="value"]').max = valueType.value === 'percentage' ? '100' : '999999999.99';
        }
        for (const control of [apply, recurrence, valueType].filter(Boolean)) control.addEventListener('change', update);
        update();
    }
    function invalidate() {
        if (!generate) return;
        generate.querySelector('[name="preview_token"]').value = '';
        document.getElementById('bill-generate').disabled = true;
        const checkbox = generate.querySelector('[name="confirm_generate"]'); if (checkbox) checkbox.checked = false;
    }
    async function recalculate() {
        if (!preview || typeof window.fetch !== 'function' || posting) return;
        const ticket = ++previewGeneration;
        const focused = document.activeElement?.id;
        invalidate(); status.textContent = 'Recalculating selected bills on the server...';
        const endpoint = new URL(preview.getAttribute('action'), window.location.href);
        if (endpoint.origin !== window.location.origin) return;
        try {
            const response = await window.fetch(endpoint.href, {method: 'POST', body: new window.FormData(preview), credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Bill-Preview': '1'}});
            const payload = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
            if (ticket !== previewGeneration) return;
            if (!response.ok || !payload?.html) throw new Error(payload?.error || 'Could not recalculate. Refresh and try again.');
            // A new server version may also change the due date/configuration shown
            // outside this partial. Never confirm a fresh token against old labels.
            const version = preview.querySelector('[name="version"]');
            if (version && String(payload.cycle_version) !== version.value) {
                throw new Error('Billing inputs changed. Refresh this period before reviewing and generating bills.');
            }
            document.getElementById('bill-preview-content').innerHTML = payload.html;
            if (generate) {
                putSelection(generate, payload.selected_ids);
                generate.querySelector('[name="preview_token"]').value = payload.preview_token || '';
                document.getElementById('bill-generate').disabled = !payload.preview_token || payload.blocked;
            }
            for (const element of document.querySelectorAll('[data-bill-summary]')) {
                const key = element.dataset.billSummary;
                if (payload.summary[key] !== undefined) element.textContent = String(payload.summary[key]);
            }
            if (focused) document.getElementById(focused)?.focus({preventScroll: true});
            status.textContent = payload.blocked ? (payload.message || 'Correct the highlighted inputs before generation.') : 'Preview updated. Review the selection and confirm before issuing.';
        } catch (error) { if (ticket === previewGeneration) status.textContent = error.message; }
    }
    if (preview && typeof window.fetch === 'function') {
        preview.addEventListener('submit', event => { event.preventDefault(); window.clearTimeout(previewTimer); recalculate(); });
        preview.addEventListener('change', event => {
            if (event.target.name !== 'selected_ids') return;
            ++previewGeneration; invalidate(); window.clearTimeout(previewTimer);
            previewTimer = window.setTimeout(recalculate, 200);
        });
        const selectAll = document.querySelector('[data-bill-select-all]');
        if (selectAll) {
            selectAll.hidden = false;
            selectAll.addEventListener('click', () => { for (const checkbox of preview.querySelectorAll('input[name="selected_ids"]')) if (!checkbox.disabled) checkbox.checked = true; recalculate(); });
        }
    }
    const period = document.querySelector('[data-bill-period-form]');
    if (period && preview) period.addEventListener('input', () => {
        ++previewGeneration; invalidate();
        window.clearTimeout(previewTimer);
        status.textContent = 'Use Load / Save Period to review the changed month or due date before generation.';
    });
    let invoice = null, invoiceGeneration = 0;
    function invoiceDialog() {
        if (!invoice) invoice = dialog('Bill Details', 'bill-modal-invoice', () => { ++invoiceGeneration; });
        return invoice;
    }
    document.addEventListener('click', async event => {
        const print = event.target.closest?.('[data-bill-print]');
        if (print) { event.preventDefault(); window.print(); return; }
        const link = event.target.closest?.('[data-bill-view]');
        if (!link || !nativeDialogs || typeof window.fetch !== 'function' || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const endpoint = new URL(link.getAttribute('href'), window.location.href);
        if (endpoint.origin !== window.location.origin) return;
        event.preventDefault(); const modal = invoiceDialog(); const ticket = ++invoiceGeneration;
        modal.body.textContent = 'Loading bill details...'; modal.show(link);
        try {
            const response = await window.fetch(endpoint.href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Bill-Dialog': '1'}});
            const payload = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
            if (ticket !== invoiceGeneration || !modal.element.open) return;
            if (!response.ok || !payload?.html) throw new Error(payload?.error || 'Could not load this bill.');
            modal.body.innerHTML = payload.html; eyes(modal.body);
            modal.body.querySelector('.bill-invoice')?.focus({preventScroll: true});
        } catch (error) { if (ticket === invoiceGeneration) modal.body.textContent = error.message; }
    });
    const initial = document.querySelector('[data-bill-initial-detail]');
    if (initial && nativeDialogs) {
        const modal = dialog('Bill Details', 'bill-modal-initial', body => { initial.replaceChildren(...body.childNodes); initial.hidden = false; });
        modal.body.replaceChildren(...initial.childNodes); initial.hidden = true; modal.show(null);
    }
    document.addEventListener('submit', event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (!form.matches?.('form') || !form.querySelector('[name="csrf_token"]')) return;
        if (form.dataset.billSubmitting) { event.preventDefault(); return; }
        for (const selected of form.querySelectorAll('[data-bill-selected-fields]')) {
            if (form !== generate) putSelection(form, chosen());
        }
        form.dataset.billSubmitting = 'true'; posting = true;
        for (const button of form.querySelectorAll('button[type="submit"]')) {
            button.dataset.billLabel = button.textContent; button.disabled = true; button.textContent = 'Saving...';
        }
    });
    window.addEventListener('pageshow', event => {
        posting = false;
        for (const form of document.querySelectorAll('[data-bill-submitting]')) delete form.dataset.billSubmitting;
        for (const button of document.querySelectorAll('[data-bill-label]')) { button.disabled = false; button.textContent = button.dataset.billLabel; delete button.dataset.billLabel; }
        if (event.persisted && preview) recalculate();
    });
})();

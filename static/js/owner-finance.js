(() => {
    const root = document.getElementById('finance-workspace');
    const live = document.getElementById('finance-live');
    const recovery = document.getElementById('finance-recovery');
    const native = typeof document.createElement('dialog').showModal === 'function';
    let modal = null, content = null, close = null, opener = null, scroll = null, restore = null, modalUrl = null;
    let posting = false, readTicket = 0, modalTicket = 0, recoveryState = null, pendingAttempt = null, mutationTicket = 0;
    function message(text, error = false) { if (!live) return; live.textContent = text; live.hidden = !text; live.classList.toggle('finance-error', error); }
    function clearPasswords(scope) {
        for (const input of scope.querySelectorAll('input[name="current_password"]')) { input.value = ''; input.type = 'password'; }
        for (const eye of scope.querySelectorAll('[data-pay-eye]')) { eye.setAttribute('aria-label', 'Show password'); eye.setAttribute('aria-pressed', 'false'); }
    }
    function bind(scope) {
        for (const category of scope.querySelectorAll('[data-expense-category]')) {
            if (category.dataset.bound) continue;
            category.dataset.bound = 'true';
            const sync = (changed = false) => {
                const form = category.closest('form');
                const utility = category.value !== 'other';
                const sharing = form.querySelector('[data-expense-sharing]');
                const sharingField = form.querySelector('[data-expense-sharing-field]');
                const sharedOther = !utility && sharing?.value === '1';
                if (sharingField) sharingField.hidden = utility;
                const period = form.querySelector('[data-utility-period]');
                if (period) { period.hidden = !(utility || sharedOther); period.querySelector('input').required = utility || sharedOther; }
                form.querySelector('[name="amount"]').min = utility ? '0' : '0.01';
                const name = form.querySelector('[name="expense_name"]');
                if (changed && (!name.value || ['Electricity Bill', 'Water Bill'].includes(name.value))) name.value = utility ? (category.value === 'electricity' ? 'Electricity Bill' : 'Water Bill') : '';
            };
            category.addEventListener('change', () => sync(true));
            category.closest('form').querySelector('[data-expense-sharing]')?.addEventListener('change', () => sync()); sync();
        }
        for (const eye of scope.querySelectorAll('[data-pay-eye]')) {
            if (eye.dataset.financeBound) continue;
            eye.dataset.financeBound = 'true'; eye.hidden = false;
            eye.addEventListener('click', () => {
                const input = document.getElementById(eye.dataset.payEye); const show = input.type === 'password';
                input.type = show ? 'text' : 'password'; eye.setAttribute('aria-label', show ? 'Hide password' : 'Show password'); eye.setAttribute('aria-pressed', String(show));
            });
        }
        if (native) {
            for (const button of scope.querySelectorAll('[data-finance-close]')) { button.hidden = false; button.addEventListener('click', hide); }
            for (const link of scope.querySelectorAll('[data-finance-fallback]')) link.hidden = true;
        }
    }
    function safeUrl(address) { const url = new URL(address, window.location.href); if (url.origin !== window.location.origin) throw new Error('Invalid form destination. Refresh this page.'); return url; }
    async function json(response) {
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Could not confirm the response. Refresh saved records.');
        return response.json();
    }
    function viewUrl(view) {
        const url = safeUrl('/owner/income-expenses'); url.search = new URLSearchParams(view).toString(); return url;
    }
    function applyWorkspace(payload) {
        if (!root || !payload.workspace_html) return;
        root.innerHTML = payload.workspace_html; bind(root);
        if (payload.filters && window.history?.replaceState) window.history.replaceState({}, '', viewUrl(payload.filters).href);
    }
    function hide() { if (!posting && modal?.open) modal.close(); }
    function ensureModal() {
        if (modal) return;
        modal = document.createElement('dialog'); modal.className = 'finance-dialog'; modal.setAttribute('aria-labelledby', 'finance-dialog-title');
        const header = document.createElement('header'); header.className = 'finance-dialog-header';
        const title = document.createElement('h2'); title.id = 'finance-dialog-title'; title.textContent = 'Expense Details';
        close = document.createElement('button'); close.type = 'button'; close.className = 'finance-button finance-dialog-close'; close.textContent = '\u00d7'; close.setAttribute('aria-label', 'Close expense dialog'); close.addEventListener('click', hide);
        header.append(title, close); content = document.createElement('div'); content.className = 'finance-dialog-content'; modal.append(header, content); document.body.append(modal);
        modal.addEventListener('cancel', event => { event.preventDefault(); hide(); });
        modal.addEventListener('click', event => { const box = modal.getBoundingClientRect(); if (event.target === modal && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) hide(); });
        modal.addEventListener('close', () => {
            if (modal.open) return;
            ++modalTicket; clearPasswords(modal); document.body.removeAttribute('data-finance-dialog-open');
            if (restore) { restore.replaceChildren(...content.childNodes); restore.hidden = false; restore = null; }
            const fallback = root?.querySelector('[data-finance-modal]') || document.getElementById('expense-name');
            if (opener?.isConnected) opener.focus({preventScroll: true}); else fallback?.focus({preventScroll: true});
            if (scroll && typeof window.scrollTo === 'function') window.scrollTo(scroll.x, scroll.y);
        });
    }
    function show(trigger) {
        ensureModal(); opener = trigger; scroll = {x: window.scrollX || 0, y: window.scrollY || 0};
        if (!modal.open) modal.showModal(); document.body.setAttribute('data-finance-dialog-open', ''); close.focus();
    }
    function focusForm() { (content.querySelector('[aria-invalid="true"]') || content.querySelector('input:not([type="hidden"])') || close).focus({preventScroll: true}); }
    async function loadModal(address, trigger, existing = false) {
        const url = safeUrl(address); const ticket = ++modalTicket; modalUrl = url.href;
        if (!existing) show(trigger);
        clearPasswords(content); content.textContent = 'Loading saved expense...';
        try {
            const response = await window.fetch(url.href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Finance-Modal': '1'}});
            const payload = await json(response);
            if (ticket !== modalTicket || !modal.open) return;
            if (!response.ok || !payload.modal_html) throw new Error(payload.error || 'Could not load this expense.');
            content.innerHTML = payload.modal_html; bind(content); focusForm();
        } catch (error) { if (ticket === modalTicket && modal.open) content.textContent = error.message; }
    }
    async function readWorkspace(address, keepFocus = true) {
        const ticket = ++readTicket; const focused = keepFocus ? document.activeElement?.id : null;
        const response = await window.fetch(safeUrl(address).href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Finance-Request': '1'}});
        const payload = await json(response);
        if (!response.ok || !payload.workspace_html) throw new Error(payload.error || 'Could not refresh saved records.');
        if (ticket !== readTicket) return null;
        applyWorkspace(payload); if (focused) document.getElementById(focused)?.focus({preventScroll: true}); return payload;
    }
    function showRecovery(error) {
        message(error.message, true); if (recovery) recovery.hidden = false;
        if (modal?.open) {
            content.replaceChildren(); const text = document.createElement('p'); text.textContent = error.message;
            const button = document.createElement('button'); button.type = 'button'; button.className = 'finance-button'; button.textContent = 'Refresh Saved Values'; button.dataset.financeRecover = ''; button.addEventListener('click', recover);
            content.append(text, button); button.focus();
        }
    }
    async function recover() {
        if (!recoveryState || posting) return;
        const state = recoveryState;
        try {
            const view = {month: state.month, q: '', page: '1'};
            if (state.kind === 'add') view.attempt_key = state.fields.request_key;
            const payload = await readWorkspace(viewUrl(view), false); if (!payload) return;
            if (state.kind === 'add' && !payload.recovered && state.modal && modal?.open) await loadModal(state.modal, opener, true);
            if (state.kind === 'add' && !payload.recovered) {
                const form = document.getElementById('expense-add-form');
                for (const [name, value] of Object.entries(state.fields)) { const input = form?.querySelector('[name="' + name + '"]'); if (input) input.value = value; }
                form?.querySelector('[data-expense-category]')?.dispatchEvent(new window.Event('change', {bubbles: true}));
            }
            if (state.kind !== 'add' && state.modal && modal?.open) await loadModal(state.modal, opener, true);
            recoveryState = null; if (recovery) recovery.hidden = true;
            message(payload.recovered ? 'Saved expense found. Review the refreshed records.' : 'Saved values refreshed. An unresolved Add keeps its original request key for a safe retry.');
        } catch (error) { showRecovery(error); }
    }
    document.getElementById('finance-refresh')?.addEventListener('click', recover);
    document.addEventListener('click', event => {
        const link = event.target.closest?.('[data-finance-modal]');
        const page = event.target.closest?.('[data-finance-page]');
        if (event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || posting) return;
        if (link && native && typeof window.fetch === 'function') {
            event.preventDefault();
            const url = safeUrl(link.getAttribute('href'));
            if (link.matches('[data-finance-add]')) {
                // The month picker can change before the workspace GET replaces this link.
                const month = document.getElementById('finance-month')?.value;
                if (month) url.searchParams.set('month', month);
            }
            loadModal(url.href, link);
        }
        else if (page && root && typeof window.fetch === 'function') { event.preventDefault(); readWorkspace(page.getAttribute('href')).catch(error => message(error.message, true)); }
    });
    document.addEventListener('change', event => {
        if (event.target.id !== 'finance-month' || !root || typeof window.fetch !== 'function' || posting) return;
        readWorkspace(viewUrl({month: event.target.value})).catch(error => message(error.message, true));
    });
    document.addEventListener('reset', event => {
        const form = event.target; if (form.id !== 'expense-add-form') return;
        if (posting || recoveryState) { event.preventDefault(); return; }
        window.setTimeout(() => {
            form.querySelector('[name="expense_name"]').value = ''; form.querySelector('[name="amount"]').value = '';
            form.querySelector('[name="expense_date"]').value = form.dataset.defaultDate;
            for (const input of form.querySelectorAll('[aria-invalid]')) input.removeAttribute('aria-invalid');
            form.querySelector('[name="expense_name"]').focus();
        }, 0);
    });
    document.addEventListener('submit', async event => {
        if (event.defaultPrevented || !root || typeof window.fetch !== 'function') return;
        const form = event.target;
        if (form.matches?.('[data-finance-filter]')) {
            event.preventDefault(); if (posting) return;
            const url = safeUrl(form.getAttribute('action')); url.search = new URLSearchParams(new window.FormData(form)).toString();
            try { await readWorkspace(url); } catch (error) { message(error.message, true); } return;
        }
        if (!form.matches?.('[data-finance-post]')) return;
        const adding = form.dataset.financePost === 'add';
        // Standalone Add uses the normal redirect back to the month and its flash notice.
        if (adding && document.querySelector('[data-finance-initial]')) return;
        event.preventDefault(); if (posting || recoveryState || !form.reportValidity()) return;
        let endpoint;
        try { endpoint = safeUrl(form.getAttribute('action')); } catch (error) { clearPasswords(form); message(error.message, true); return; }
        const body = new window.FormData(form); const fields = {};
        for (const name of ['expense_name', 'amount', 'expense_date', 'request_key', 'category', 'utility_period', 'notes','charge_to_tenants']) { const value = body.get(name); if (value !== null) fields[name] = value; }
        const month = form.dataset.financePost === 'edit'
            ? body.get('accounting_period') || fields.expense_date?.slice(0, 7) || body.get('view_month')
            : body.get('view_month');
        const selected = document.getElementById('finance-month')?.value;
        if (adding && !modal?.open && selected && selected !== month) {
            message('Wait for the selected accounting month to load before saving.', true);
            return;
        }
        const attempt = {kind: form.dataset.financePost, month, fields, modal: modal?.open ? modalUrl : null};
        const writeTicket = ++mutationTicket; pendingAttempt = attempt;
        posting = true; ++readTicket; clearPasswords(form); if (close) close.disabled = true; message('Saving expense...');
        for (const button of form.querySelectorAll('button[type="submit"]')) button.disabled = true;
        try {
            const response = await window.fetch(endpoint.href, {method: 'POST', body, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Finance-Request': '1'}});
            const payload = await json(response);
            if (writeTicket !== mutationTicket) return;
            if (response.ok && payload.workspace_html) {
                applyWorkspace(payload); posting = false; hide(); message(payload.notice || 'Expense saved.');
            } else if (response.status < 500 && payload.modal_html && modal?.open) {
                content.innerHTML = payload.modal_html; bind(content); clearPasswords(content); focusForm(); message('Review the highlighted fields.', true);
            } else if (response.status < 500 && payload.workspace_html) { applyWorkspace(payload); message('Review the highlighted fields.', true); }
            else throw new Error(payload.error || 'Could not confirm the save. Refresh saved records before trying again.');
        } catch (error) { if (writeTicket === mutationTicket) { recoveryState = attempt; showRecovery(error); } }
        finally { if (writeTicket === mutationTicket) { pendingAttempt = null; posting = false; if (close) close.disabled = false; if (!recoveryState && form.isConnected) for (const button of form.querySelectorAll('button[type="submit"]')) button.disabled = false; } }
    });
    bind(document);
    const initial = document.querySelector('[data-finance-initial]');
    if (initial && native) { show(null); restore = initial; content.replaceChildren(...initial.childNodes); initial.hidden = true; focusForm(); }
    window.addEventListener('pagehide', () => clearPasswords(document));
    window.addEventListener('pageshow', event => {
        clearPasswords(document);
        if (!event.persisted || !root) return;
        if (posting && pendingAttempt) {
            ++mutationTicket; recoveryState = pendingAttempt; pendingAttempt = null; posting = false; if (close) close.disabled = false;
            showRecovery(new Error('Returned after an uncertain save. Refresh saved records before trying again.'));
        } else readWorkspace(window.location.href).catch(error => message(error.message, true));
    });
})();

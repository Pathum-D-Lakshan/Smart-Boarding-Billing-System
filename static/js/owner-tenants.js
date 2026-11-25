(() => {
    const dialog = document.getElementById('tn-dialog');
    function eye(password, button) {
        if (!password || !button) return;
        button.hidden = false;
        button.addEventListener('click', () => {
            const show = password.type === 'password';
            password.type = show ? 'text' : 'password';
            button.setAttribute('aria-pressed', String(show));
            button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
        });
    }
    if (!dialog || typeof dialog.showModal !== 'function' || typeof window.fetch !== 'function') {
        eye(document.getElementById('tn-password'), document.getElementById('tn-password-toggle'));
        return; // Real POST forms and details links still work without enhancement.
    }
    const content = document.getElementById('tn-content');
    const close = document.getElementById('tn-close');
    const feedback = document.getElementById('tn-feedback');
    const recovery = document.getElementById('tn-recovery');
    const login = document.getElementById('tn-login');
    const live = document.getElementById('tn-live');
    const headers = {'Accept': 'application/json', 'X-Tenant-Modal': '1'};
    let saving = false, generation = 0, opener = null, currentUrl = null, scroll = null;
    let controls = [];
    function busy(value) {
        saving = value;
        close.disabled = value;
        dialog.setAttribute('aria-busy', String(value));
        if (value) {
            controls = [...content.querySelectorAll('button')].map(button => [button, button.disabled]);
            controls.forEach(([button]) => { button.disabled = true; });
        } else {
            controls.forEach(([button, wasDisabled]) => { button.disabled = wasDisabled; });
            controls = [];
        }
    }
    function clearFeedback() { feedback.hidden = true; recovery.hidden = true; login.hidden = true; }
    function failed(message, expired = false) {
        feedback.textContent = message;
        feedback.hidden = false;
        recovery.hidden = false;
        login.hidden = !expired;
        const form = content.querySelector('#tn-change-form');
        if (form) form.hidden = true; // Unknown POST outcomes require a read-only refresh.
        const manage = content.querySelector('#tn-open-manage');
        if (manage) manage.disabled = true;
        feedback.focus();
    }
    async function payload(response) {
        const data = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
        if (!data?.html) {
            const error = new Error(data?.error || 'Could not confirm the operation. Refresh this tenancy before trying again.');
            error.expired = response.status === 401 || response.redirected;
            throw error;
        }
        return data;
    }
    function updatePage(data) {
        const current = document.getElementById('tn-results');
        if (current && data.results_html) {
            const form = current.querySelector('.tn-filters');
            const edits = ['q', 'status', 'room', 'sort'].map(name => [name, form?.elements.namedItem(name)?.value]);
            const template = document.createElement('template');
            template.innerHTML = data.results_html;
            const next = template.content.querySelector('#tn-results');
            if (next) {
                current.replaceWith(next);
                for (const [name, value] of edits) {
                    const field = next.querySelector('.tn-filters')?.elements.namedItem(name);
                    if (field && value !== undefined) field.value = value;
                }
            }
        }
        if (data.summary) for (const count of document.querySelectorAll('[data-tn-count]')) {
            const value = data.summary[count.dataset.tnCount];
            if (Number.isInteger(value) && value >= 0) count.textContent = String(value);
        }
    }
    function initialize(intent = null) {
        const root = content.querySelector('#tn-detail');
        if (!root) return;
        const form = root.querySelector('#tn-change-form');
        if (!form) { root.focus({preventScroll: true}); return; }
        const fields = form.querySelector('[data-tn-edit]');
        const confirm = form.querySelector('[data-tn-confirm]');
        const password = form.querySelector('#tn-password');
        const toggle = form.querySelector('#tn-password-toggle');
        const action = form.querySelector('#tn-action');
        const date = form.querySelector('#tn-date');
        const dateField = form.querySelector('#tn-date-field');
        const dateLabel = form.querySelector('#tn-date-label');
        const dateHelp = form.querySelector('#tn-date-help');
        const submit = form.querySelector('#tn-save');
        const open = root.querySelector('#tn-open-manage');
        const removalButton = root.querySelector('[data-tn-removal]');
        const financial = form.querySelector('#tn-financial-review');
        const financialCheck = form.querySelector('#tn-confirm-financial');
        let confirming = false;
        eye(password, toggle);
        function clearPassword() {
            password.value = '';
            password.type = 'password';
            toggle.setAttribute('aria-pressed', 'false');
            toggle.setAttribute('aria-label', 'Show password');
        }
        const dates = new Map([[action.value, date.value]]);
        let previousAction = action.value;
        function nextDay(iso) {
            if (!iso) return '';
            const day = new Date(iso + 'T00:00:00Z');
            day.setUTCDate(day.getUTCDate() + 1);
            return day.toISOString().slice(0, 10);
        }
        function updateAction() {
            if (action.value !== previousAction) {
                dates.set(previousAction, date.value);
                date.value = dates.get(action.value) || '';
                previousAction = action.value;
            }
            dateField.hidden = ['cancel','request_removal'].includes(action.value);
            date.required = !['cancel','request_removal'].includes(action.value);
            const today = form.dataset.today || '';
            const start = form.dataset.startDate || '';
            const end = form.dataset.endDate || '';
            date.min = '';
            date.max = '';
            date.readOnly = false;
            if (financial) financial.hidden = action.value !== 'request_removal';
            if (financialCheck) {
                financialCheck.disabled = !confirming || action.value !== 'request_removal';
                financialCheck.required = confirming && action.value === 'request_removal';
            }
            const reason = form.querySelector('#tn-reason');
            if (reason) reason.required = action.value === 'request_removal';
            if (action.value === 'request_removal') {
                date.value = '';
            } else if (action.value === 'start') {
                if (!date.value) date.value = start;
                date.min = nextDay(today);
                date.max = end;
                if (dateLabel) dateLabel.textContent = 'New Start Date';
                if (dateHelp) dateHelp.textContent = 'Choose a future start date. The existing start is ' + start + '. Your agreed rent stays unchanged.';
            } else if (action.value === 'schedule') {
                if (!date.value) date.value = end;
                date.min = [nextDay(today), start].sort().at(-1);
                if (dateLabel) dateLabel.textContent = 'Planned Checkout Date';
                if (dateHelp) dateHelp.textContent = 'Choose a future checkout on or after ' + start + '. The unit remains assigned until checkout.';
            } else if (action.value === 'confirm') {
                if (!date.value) date.value = today;
                date.min = start;
                date.max = today;
                if (dateLabel) dateLabel.textContent = 'Completed Checkout Date';
                if (dateHelp) dateHelp.textContent = 'Choose today or a past date on or after ' + start + '. This preserves the completed agreement in history.';
            }
        }
        function stage(value) {
            confirming = value;
            form.hidden = false;
            fields.hidden = value;
            confirm.hidden = !value;
            password.disabled = !value;
            password.required = value;
            updateAction();
            clearPassword();
            submit.textContent = value ? (action.value === 'request_removal' ? 'Send Request to Admin' : 'Confirm Action') : 'Review Changes';
            const label = action.selectedOptions[0]?.textContent || action.value;
            form.querySelector('#tn-proposed').textContent = label + (action.value === 'request_removal' ? ' — tenant stays active until Admin approval' : action.value === 'cancel' ? ' — checkout becomes Not scheduled' : ' — ' + date.value);
            (value ? password : action).focus();
        }
        open.hidden = false;
        open.addEventListener('click', () => stage(false));
        if (removalButton) {
            removalButton.hidden = false;
            removalButton.addEventListener('click', () => { action.value = 'request_removal'; updateAction(); stage(false); });
        }
        for (const button of form.querySelectorAll('[data-tn-cancel]')) {
            button.hidden = false;
            button.addEventListener('click', () => stage(false));
        }
        for (const button of form.querySelectorAll('[data-tn-back]')) {
            button.hidden = false;
            button.addEventListener('click', () => { clearPassword(); form.hidden = true; open.focus(); });
        }
        action.addEventListener('change', updateAction);
        updateAction();
        form.addEventListener('submit', async event => {
            event.preventDefault();
            if (saving || !form.reportValidity()) return;
            if (!confirming) { stage(true); return; }
            // A control named "action" shadows HTMLFormElement.action in browsers.
            // Read the attribute and restrict the destination before sending a password.
            const actionUrl = form.getAttribute('action');
            const endpoint = actionUrl ? new URL(actionUrl, window.location.href) : null;
            if (!endpoint || endpoint.origin !== window.location.origin) {
                clearPassword();
                failed('Could not locate the save action. Refresh this tenancy before trying again.');
                return;
            }
            const body = new window.FormData(form);
            clearPassword();
            const ticket = generation;
            clearFeedback(); busy(true); live.textContent = 'Saving your confirmed action.';
            try {
                const response = await window.fetch(endpoint.href, {method: 'POST', body, headers, credentials: 'same-origin', cache: 'no-store'});
                const data = await payload(response);
                if (ticket !== generation) return;
                busy(false);
                content.innerHTML = data.html;
                updatePage(data);
                initialize();
                live.textContent = response.ok ? (data.notice || 'Tenancy updated and history saved.') : 'Review the validation feedback.';
            } catch (error) {
                busy(false);
                if (ticket === generation) failed(error.message, error.expired);
            } finally { busy(false); }
        });
        if (intent && [...action.options].some(option => option.value === intent)) { action.value = intent; updateAction(); stage(false); }
        else if (form.dataset.passwordError === 'true') stage(true);
        else if (form.dataset.hasError === 'true') stage(false);
        else { form.hidden = true; confirm.hidden = true; password.disabled = true; root.focus({preventScroll: true}); }
    }
    function closeDialog() { if (!saving && dialog.open) dialog.close(); }
    close.addEventListener('click', closeDialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
    dialog.addEventListener('click', event => {
        const box = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) closeDialog();
    });
    dialog.addEventListener('close', () => {
        if (dialog.open) return;
        generation++;
        const password = content.querySelector('#tn-password');
        if (password) { password.value = ''; password.type = 'password'; }
        document.body.removeAttribute('data-tn-modal-open');
        if (opener?.isConnected) opener.focus({preventScroll: true});
        else document.getElementById('tn-results')?.focus({preventScroll: true});
        if (scroll && typeof window.scrollTo === 'function') window.scrollTo(scroll.x, scroll.y);
    });
    async function load(url, trigger = opener, intent = null, refresh = false) {
        if (saving) return;
        const address = new URL(url, window.location.href);
        if (address.origin !== window.location.origin) return;
        currentUrl = address.href; opener = trigger;
        const ticket = ++generation;
        clearFeedback(); content.replaceChildren();
        const loading = document.createElement('p'); loading.className = 'jr-loading'; loading.textContent = 'Loading tenancy details…'; content.append(loading);
        if (!dialog.open) { scroll = {x: window.scrollX || 0, y: window.scrollY || 0}; dialog.showModal(); }
        document.body.setAttribute('data-tn-modal-open', ''); close.focus();
        try {
            const data = await payload(await window.fetch(currentUrl, {headers, credentials: 'same-origin', cache: 'no-store'}));
            if (ticket !== generation || !dialog.open) return;
            content.innerHTML = data.html;
            // Viewing details also reflects an Admin decision made in another session.
            updatePage(data);
            initialize(intent);
        } catch (error) { if (ticket === generation && dialog.open) failed(error.message, error.expired); }
    }
    document.addEventListener('click', event => {
        const link = event.target.closest?.('[data-tn-view]');
        if (!link || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); load(link.dataset.dialogUrl, link, link.dataset.tnManage);
    });
    document.getElementById('tn-refresh').addEventListener('click', () => { if (currentUrl) load(currentUrl, opener, null, true); });
    const initial = document.getElementById('tn-initial-detail');
    if (initial) {
        currentUrl = initial.dataset.dialogUrl;
        content.replaceChildren(...initial.childNodes); initial.remove();
        scroll = {x: window.scrollX || 0, y: window.scrollY || 0};
        dialog.showModal(); document.body.setAttribute('data-tn-modal-open', ''); initialize(new URL(window.location.href).searchParams.get('manage'));
    }
})();

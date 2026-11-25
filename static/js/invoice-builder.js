/* Student-specific draft charges; all final money is recomputed by Flask. */
(() => {
    const root = document.getElementById('invoice-builder');
    if (!root) return;
    const get = id => document.getElementById(id);
    const selection = get('invoice-selection'), student = get('invoice-student'), search = get('invoice-student-search');
    const month = get('invoice-month'), due = get('invoice-due'), list = get('invoice-student-options');
    const options = Array.from(list.querySelectorAll('[data-student-option]'));
    const paper = get('invoice-paper-container'), table = get('invoice-items'), notices = get('invoice-notices');
    const details = get('invoice-student-details'), status = get('invoice-progress');
    const review = get('invoice-review'), add = get('invoice-add-button'), confirm = get('invoice-confirm-send');
    const dialog = get('invoice-confirm-dialog'), adjustment = get('invoice-adjust-dialog');
    const addForm = get('invoice-add-item'), editCancel = get('invoice-edit-cancel');
    const customDialog = get('invoice-custom-dialog'), expenseDialog = get('invoice-expense-dialog');
    const discountDialog = get('invoice-discount-dialog'); let discount = null;
    let selectedExpenses = [], savedExpenses = [], pendingExpenses = new Set();
    const initialPaper = paper.innerHTML;
    let items = [], overrides = [], charges = [], version = 0, timer = null, snapshot = null;
    let ready = false, eligible = false, loading = false, posting = false, editing = null, adjusting = null, activeOption = -1;

    function message(text, error = false) { status.textContent = text; status.classList.toggle('invoice-error', error); get('invoice-custom-feedback').textContent = text; get('invoice-discount-feedback').textContent = text; }
    function safeUrl(value) {
        const url = new URL(value, window.location.href);
        if (url.origin !== window.location.origin) throw new Error('Invalid destination. Refresh this page.');
        return url;
    }
    function closeModal(modal) {
        if (posting) return;
        if (modal.open && typeof modal.close === 'function') modal.close(); else modal.removeAttribute('open');
    }
    function openModal(modal) {
        if (typeof modal.showModal === 'function') modal.showModal(); else modal.setAttribute('open', '');
    }
    function controls() {
        get('invoice-load').disabled = posting || loading || !student.value;
        add.disabled = posting || loading || !eligible;
        get('invoice-other-expenses').disabled = posting || loading || !eligible;
        get('invoice-custom-open').disabled = posting || loading || !eligible;
        get('invoice-discount-open').disabled = posting || loading || !eligible;
        get('invoice-discount-open').textContent = discount ? '− Edit Discount' : '− Add Discount';
        review.disabled = posting || loading || !ready || !snapshot || editing !== null;
        confirm.disabled = posting || loading || !ready || !snapshot;
        get('invoice-print-preview').disabled = posting || loading || !eligible;
        for (const node of [search, month, due, get('invoice-reset'), get('invoice-new')]) node.disabled = posting;
        for (const node of table.querySelectorAll('[data-invoice-edit],[data-invoice-remove],[data-invoice-adjust],[data-invoice-waive],[data-invoice-restore],[data-invoice-discount-edit],[data-invoice-discount-remove]')) node.disabled = posting || loading;
        root.setAttribute('aria-busy', String(posting || loading));
    }
    function resetEditor() {
        editing = null; addForm.reset(); editCancel.hidden = false; add.textContent = 'Add to Bill';
        get('invoice-item-name').setCustomValidity(''); get('invoice-item-amount').setCustomValidity('');
    }
    function invalidate(clear = false) {
        ++version; window.clearTimeout(timer); snapshot = null; ready = false; loading = false;
        closeModal(dialog); closeModal(adjustment); get('invoice-confirm-body').replaceChildren();
        paper.innerHTML = initialPaper;
        if (clear) {
            items = []; overrides = []; charges = []; selectedExpenses = []; savedExpenses = []; discount = null; eligible = false; resetEditor(); closeModal(customDialog); closeModal(expenseDialog); closeModal(discountDialog);
            details.replaceChildren(); notices.replaceChildren(); table.textContent = 'Choose a Student to load their charges automatically.';
        }
        controls();
    }
    const clone = value => JSON.parse(JSON.stringify(value));
    function payload() { return {tenancy_id: student.value, month: month.value, due_date: due.value, items: clone(items), overrides: clone(overrides), selected_expenses: clone(selectedExpenses), discount:clone(discount)}; }
    async function json(response) {
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Could not confirm the response. Check View Sent Bills before retrying.');
        return response.json();
    }
    async function calculate() {
        if (posting || !student.value || !selection.reportValidity()) return false;
        const focused = document.activeElement?.id;
        invalidate(); const ticket = version, requested = payload();
        loading = true; controls(); message('Updating invoice…');
        const body = new window.FormData(); body.set('csrf_token', get('invoice-csrf').value); body.set('payload', JSON.stringify(requested));
        try {
            const response = await window.fetch(safeUrl(root.dataset.previewUrl).href, {method: 'POST', body, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Invoice-Builder': '1'}});
            const data = await json(response);
            if (ticket !== version) return null;
            if (!response.ok) throw new Error(data.error || 'Could not prepare this invoice.');
            const restoreFocus = document.activeElement?.id === focused;
            items = data.items; overrides = data.overrides || []; charges = data.charges || [];
            selectedExpenses = data.selected_expenses || []; savedExpenses = data.expenses || [];
            discount = data.discount || null;
            ready = data.ready; eligible = data.eligible;
            table.innerHTML = data.items_html; paper.innerHTML = data.paper_html; details.innerHTML = data.student_html;
            get('invoice-confirm-body').innerHTML = data.confirmation_html;
            notices.replaceChildren();
            for (const text of data.messages) { const p = document.createElement('p'); p.className = 'invoice-notice'; p.textContent = text; notices.append(p); }
            snapshot = ready ? {...requested, items: clone(items), overrides: clone(overrides), discount:clone(discount), cycle_id: data.cycle_id, preview_token: data.preview_token} : null;
            message(ready ? 'Review the invoice, then Issue & Send.' : data.messages.join(' ') || 'This draft is not ready to issue. Refresh charges and review the highlighted fields.');
            if (focused && restoreFocus) get(focused)?.focus({preventScroll: true});
            return true;
        } catch (error) { if (ticket === version) { ready = false; snapshot = null; message(error.message, true); } return false; }
        finally { if (ticket === version) { loading = false; controls(); } }
    }
    function changed() {
        if (posting) return;
        invalidate(true);
        if (student.value && selection.checkValidity()) timer = window.setTimeout(calculate, 120);
        else message('Choose a Student and valid billing dates.');
    }
    function showOptions(show) {
        list.hidden = !show; search.setAttribute('aria-expanded', String(show));
        if (!show) { search.removeAttribute('aria-activedescendant'); activeOption = -1; }
    }
    function visibleOptions() { return options.filter(option => !option.hidden); }
    function choose(option) {
        if (posting || !option) return;
        student.value = option.dataset.studentOption; search.value = option.textContent.trim(); search.setCustomValidity('');
        for (const node of options) node.setAttribute('aria-selected', String(node === option));
        search.focus(); showOptions(false); changed();
    }
    search.addEventListener('focus', () => { if (student.value) for (const option of options) option.hidden = false; showOptions(true); });
    search.addEventListener('click', () => showOptions(true));
    search.addEventListener('input', () => {
        if (posting) return;
        const query = search.value.trim().toLocaleLowerCase();
        student.value = ''; search.setCustomValidity('');
        for (const option of options) option.hidden = !option.textContent.toLocaleLowerCase().includes(query);
        showOptions(true); activeOption = -1; invalidate(true);
    });
    for (const option of options) option.addEventListener('click', () => choose(option));
    search.addEventListener('keydown', event => {
        const visible = visibleOptions();
        if (event.key === 'Escape') { event.preventDefault(); showOptions(false); return; }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault(); showOptions(true);
            if (!visible.length) return;
            activeOption = activeOption < 0 ? (event.key === 'ArrowDown' ? 0 : visible.length - 1) : (activeOption + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length;
            search.setAttribute('aria-activedescendant', visible[activeOption].id);
            for (const option of options) option.classList.toggle('invoice-option-active', option === visible[activeOption]);
            visible[activeOption].scrollIntoView({block: 'nearest'}); return;
        }
        if (event.key === 'Enter' && !list.hidden && visible.length) { event.preventDefault(); choose(visible[activeOption < 0 ? 0 : activeOption]); }
    });
    document.addEventListener('click', event => { if (!get('invoice-student-options').contains(event.target) && event.target !== search) showOptions(false); });
    selection.addEventListener('submit', event => {
        event.preventDefault(); showOptions(false);
        if (!student.value) { search.setCustomValidity('Choose a Student from the approved tenancy list.'); search.reportValidity(); return; }
        calculate();
    });
    month.addEventListener('change', () => {
        if (/^\d{4}-\d{2}$/.test(month.value)) {
            const [year, number] = month.value.split('-').map(Number);
            due.min = month.value + '-01'; due.value = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
            for (const id of ['invoice-expenses','invoice-settings']) {
                const link = safeUrl(get(id).href); link.searchParams.set('month', month.value); get(id).href = link.href;
            }
        }
        changed();
    });
    due.addEventListener('input', () => { if (!posting) { invalidate(); if (student.value && selection.checkValidity()) timer = window.setTimeout(calculate, 200); } });
    addForm.addEventListener('input', event => event.target.setCustomValidity?.(''));
    addForm.addEventListener('submit', async event => {
        event.preventDefault();
        if (posting || loading || !eligible || !addForm.reportValidity()) return;
        const name = get('invoice-item-name'), amount = get('invoice-item-amount');
        name.setCustomValidity(name.value.trim() && !/[\u0000-\u001f]/.test(name.value) ? '' : 'Enter a charge description.');
        amount.setCustomValidity(/^[0-9]{1,12}(\.[0-9]{1,2})?$/.test(amount.value) ? '' : 'Use an amount with at most two decimals.');
        if (!name.reportValidity() || !amount.reportValidity()) return;
        if (editing === null && items.length >= 20) { message('Add no more than 20 extra charges.', true); return; }
        const previous = clone(items), entry = {description: name.value.trim(), amount: amount.value};
        if (editing === null) items.push(entry); else items[editing] = entry;
        const ticket = version + 1, applied = await calculate();
        if (ticket !== version) return;
        if (applied) { resetEditor(); closeModal(customDialog); } else items = previous;
        controls();
    });
    editCancel.addEventListener('click', () => { resetEditor(); closeModal(customDialog); controls(); });
    get('invoice-custom-open').addEventListener('click', () => { if (!eligible || loading || posting) return; resetEditor(); openModal(customDialog); get('invoice-item-name').focus(); });
    for (const button of customDialog.querySelectorAll('[data-custom-close]')) button.addEventListener('click', () => { resetEditor(); closeModal(customDialog); controls(); });
    customDialog.addEventListener('cancel', event => { event.preventDefault(); resetEditor(); closeModal(customDialog); controls(); });
    function editCharge(key) {
        const charge = charges.find(line => line.key === key);
        if (!charge?.editable) return;
        adjusting = key;
        get('invoice-adjust-title').textContent = 'Edit Charge';
        get('invoice-adjust-description').value = charge.description;
        get('invoice-adjust-original').textContent = 'Calculated share: LKR ' + charge.original;
        get('invoice-adjust-amount').value = charge.amount;
        get('invoice-adjust-description').setCustomValidity(''); get('invoice-adjust-amount').setCustomValidity('');
        get('invoice-adjust-save').textContent = 'Save Changes';
        openModal(adjustment); get('invoice-adjust-description').focus();
    }
    table.addEventListener('click', async event => {
        if (posting || loading) return;
        const edit = event.target.closest?.('[data-invoice-edit]');
        const remove = event.target.closest?.('[data-invoice-remove]');
        const adjust = event.target.closest?.('[data-invoice-adjust]');
        const waive = event.target.closest?.('[data-invoice-waive]');
        const restore = event.target.closest?.('[data-invoice-restore]');
        const discountEdit = event.target.closest?.('[data-invoice-discount-edit]');
        const discountRemove = event.target.closest?.('[data-invoice-discount-remove]');
        if (discountEdit) { openDiscount(); return; }
        if (discountRemove) { const previous=clone(discount); discount=null; const ticket=version+1,applied=await calculate(); if(!applied&&ticket===version)discount=previous; controls(); return; }
        if (edit) {
            const index = Number(edit.dataset.invoiceEdit); if (!items[index]) return;
            editing = index; openModal(customDialog);
            get('invoice-item-name').value = items[index].description; get('invoice-item-amount').value = items[index].amount;
            add.textContent = 'Save Changes'; editCancel.hidden = false; controls(); get('invoice-item-name').focus();
        } else if (remove) {
            const previous = clone(items); items.splice(Number(remove.dataset.invoiceRemove), 1); resetEditor();
            const ticket = version + 1, applied = await calculate(); if (!applied && ticket === version) items = previous;
        } else if (adjust) editCharge(adjust.dataset.invoiceAdjust);
        else if (waive) {
            const key = waive.dataset.invoiceWaive, charge = charges.find(line => line.key === key);
            if (!charge?.editable) return;
            const previous = clone(overrides); overrides = overrides.filter(line => line.key !== key);
            overrides.push({key, amount:'0.00', description:charge.description});
            const ticket = version + 1, applied = await calculate(); if (!applied && ticket === version) overrides = previous;
        }
        else if (restore) {
            const previous = clone(overrides); overrides = overrides.filter(line => line.key !== restore.dataset.invoiceRestore);
            const ticket = version + 1, applied = await calculate(); if (!applied && ticket === version) overrides = previous;
        }
    });
    get('invoice-adjust-form').addEventListener('input', event => event.target.setCustomValidity?.(''));
    get('invoice-adjust-form').addEventListener('submit', async event => {
        event.preventDefault();
        if (posting || loading || !adjusting || !event.target.reportValidity()) return;
        const amount = get('invoice-adjust-amount'), description = get('invoice-adjust-description');
        amount.setCustomValidity(/^[0-9]{1,12}(\.[0-9]{1,2})?$/.test(amount.value) ? '' : 'Enter a non-negative amount with at most two decimals.');
        description.setCustomValidity(description.value.trim() && !/[\u0000-\u001f]/.test(description.value) ? '' : 'Enter a charge description.');
        if (!amount.reportValidity() || !description.reportValidity()) return;
        const previous = clone(overrides);
        overrides = overrides.filter(line => line.key !== adjusting);
        overrides.push({key: adjusting, amount: amount.value, description: description.value.trim()});
        closeModal(adjustment);
        const ticket = version + 1, applied = await calculate(); if (!applied && ticket === version) overrides = previous;
    });
    for (const button of adjustment.querySelectorAll('[data-adjust-close]')) button.addEventListener('click', () => closeModal(adjustment));
    adjustment.addEventListener('cancel', event => { event.preventDefault(); closeModal(adjustment); });
    function renderExpenses() {
        const container = get('invoice-expense-list'); container.replaceChildren();
        const query = get('invoice-expense-search').value.trim().toLocaleLowerCase(), category = get('invoice-expense-category').value;
        let matches = 0;
        for (const expense of savedExpenses) {
            if (!expense.name.toLocaleLowerCase().includes(query) || category && expense.category !== category) continue;
            matches++;
            const row = document.createElement('label'); row.className = 'invoice-expense-row';
            const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = String(expense.expense_id);
            const removed = charges.find(line => line.key === 'expense:'+checkbox.value)?.waived;
            const included = selectedExpenses.map(String).includes(checkbox.value) && !removed;
            checkbox.disabled = !expense.available || included;
            checkbox.checked = included || pendingExpenses.has(checkbox.value);
            checkbox.setAttribute('aria-label','Add '+expense.name);
            checkbox.addEventListener('change', () => { if (checkbox.checked) pendingExpenses.add(checkbox.value); else pendingExpenses.delete(checkbox.value); updateExpenseCount(); });
            const info = document.createElement('span'), name = document.createElement('strong'), meta = document.createElement('small');
            name.textContent = expense.name; meta.textContent = expense.category.charAt(0).toUpperCase()+expense.category.slice(1)+' · '+expense.date+' · '+(removed ? 'Available to Add' : expense.state);
            info.append(name); info.append(meta);
            const money = document.createElement('span'), total = document.createElement('small'), share = document.createElement('strong');
            total.textContent = 'Recorded: LKR '+expense.amount; share.textContent = 'Student share: LKR '+expense.share;
            money.append(total); money.append(share); row.append(checkbox); row.append(info); row.append(money); container.append(row);
        }
        if (!matches) { const empty = document.createElement('p'); empty.textContent = 'No saved expenses match this billing month and filter.'; container.append(empty); }
        updateExpenseCount();
    }
    function updateExpenseCount() { get('invoice-expense-count').textContent = pendingExpenses.size+' selected'; get('invoice-expense-add').disabled = !pendingExpenses.size || loading || posting; }
    get('invoice-other-expenses').addEventListener('click', async () => {
        if (!eligible || loading || posting) return;
        if (await calculate()) { pendingExpenses = new Set(); get('invoice-expense-search').value = ''; get('invoice-expense-category').value = ''; renderExpenses(); openModal(expenseDialog); get('invoice-expense-search').focus(); }
    });
    get('invoice-expense-search').addEventListener('input',renderExpenses); get('invoice-expense-category').addEventListener('change',renderExpenses);
    for (const button of expenseDialog.querySelectorAll('[data-expense-close]')) button.addEventListener('click', () => closeModal(expenseDialog));
    expenseDialog.addEventListener('cancel', event => { event.preventDefault(); closeModal(expenseDialog); });
    get('invoice-expense-add').addEventListener('click', async () => {
        if (!pendingExpenses.size || loading || posting) return;
        const previous = clone(selectedExpenses), previousOverrides = clone(overrides);
        selectedExpenses = [...new Set([...selectedExpenses.map(String),...pendingExpenses])];
        overrides = overrides.filter(line => !pendingExpenses.has(line.key.replace(/^expense:/,'')) || !line.key.startsWith('expense:'));
        closeModal(expenseDialog);
        const ticket = version + 1, applied = await calculate(); if (!applied && ticket === version) { selectedExpenses = previous; overrides = previousOverrides; }
    });
    function openDiscount() {
        if (posting || loading || !eligible) return;
        const description=get('invoice-discount-description'), amount=get('invoice-discount-amount');
        description.value=discount?.description || 'Discount'; amount.value=discount?.amount || '';
        description.setCustomValidity(''); amount.setCustomValidity(''); get('invoice-discount-feedback').textContent='';
        get('invoice-discount-title').textContent=discount ? 'Edit Discount' : 'Add Discount'; openModal(discountDialog); amount.focus();
    }
    get('invoice-discount-open').addEventListener('click',openDiscount);
    for(const button of discountDialog.querySelectorAll('[data-discount-close]'))button.addEventListener('click',()=>closeModal(discountDialog));
    discountDialog.addEventListener('cancel',event=>{event.preventDefault();closeModal(discountDialog);});
    get('invoice-discount-form').addEventListener('input',event=>event.target.setCustomValidity?.(''));
    get('invoice-discount-form').addEventListener('submit',async event=>{
        event.preventDefault(); if(posting||loading||!eligible||!event.target.reportValidity())return;
        const description=get('invoice-discount-description'), amount=get('invoice-discount-amount');
        description.setCustomValidity(description.value.trim()&&!/[\u0000-\u001f]/.test(description.value)?'':'Enter a discount description.');
        amount.setCustomValidity(/^[0-9]{1,12}(\.[0-9]{1,2})?$/.test(amount.value)?'':'Enter a positive amount with at most two decimals.');
        if(!description.reportValidity()||!amount.reportValidity())return;
        const previous=clone(discount); discount={description:description.value.trim(),amount:amount.value};
        const ticket=version+1,applied=await calculate(); if(ticket!==version)return;
        if(applied)closeModal(discountDialog); else discount=previous; controls();
    });
    get('invoice-reset').addEventListener('click', () => { if (!posting) { invalidate(true); message('Draft reset. Select or refresh the Student to reload charges.'); } });
    get('invoice-new').addEventListener('click', () => {
        if (posting) return;
        selection.reset(); student.value = ''; search.value = ''; search.setCustomValidity('');
        for (const option of options) option.hidden = false;
        showOptions(false); invalidate(true); search.focus(); root.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
    review.addEventListener('click', () => {
        if (!ready || !snapshot || posting || loading || editing !== null) return;
        openModal(dialog); confirm.focus();
    });
    for (const button of dialog.querySelectorAll('[data-invoice-close]')) button.addEventListener('click', () => closeModal(dialog));
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeModal(dialog); });
    confirm.addEventListener('click', async () => {
        if (posting || loading || !ready || !snapshot) return;
        const request = {...snapshot, confirm_send: 'yes'}, ticket = ++version;
        posting = true; ready = false; snapshot = null; window.clearTimeout(timer); controls();
        confirm.textContent = 'Issuing…'; message('Issuing the reviewed invoice…');
        const body = new window.FormData(); body.set('csrf_token', get('invoice-csrf').value); body.set('payload', JSON.stringify(request));
        try {
            const response = await window.fetch(safeUrl(root.dataset.issueUrl).href, {method: 'POST', body, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', 'X-Invoice-Builder': '1'}});
            const data = await json(response); if (ticket !== version) return;
            if (!response.ok) throw new Error(data.error || 'Could not confirm issuance.');
            window.location.assign(safeUrl(data.redirect_url).href);
        } catch (error) {
            if (ticket !== version) return;
            posting = false; closeModal(dialog); message(error.message + ' Check View Sent Bills; reload before another send.', true);
            confirm.textContent = 'Confirm & Send'; controls();
        }
    });
    get('invoice-print-preview').addEventListener('click', () => { if (eligible && !loading && !posting) window.print(); });
    window.addEventListener('pageshow', event => {
        if (event.persisted) { const uncertain = posting; posting = false; invalidate(true); message(uncertain ? 'A send may have completed. Check View Sent Bills before another invoice.' : 'Refresh the Student charges before sending.'); }
    });
    window.addEventListener('pagehide', () => { snapshot = null; ready = false; });
    controls();
})();

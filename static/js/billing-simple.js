/* The final signed server preview, never browser totals, authorizes issuance. */
(() => {
    const confirm = document.getElementById('monthly-send-confirmation');
    const month = document.getElementById('simple-month');
    const due = document.getElementById('simple-due');
    month?.addEventListener('change', () => {
        if (!/^\d{4}-\d{2}$/.test(month.value) || !due) return;
        due.min = month.value + '-01';
        const [year, number] = month.value.split('-').map(Number);
        const next = new Date(Date.UTC(year, number, 0));
        due.value = next.toISOString().slice(0, 10);
    });
    let pending = null;
    function open(dialog) {
        if (dialog && !dialog.open && typeof dialog.showModal === 'function') dialog.showModal();
    }
    document.addEventListener('click', event => {
        const trigger = event.target.closest?.('[data-monthly-open]');
        if (trigger) open(document.getElementById(trigger.dataset.monthlyOpen));
        const close = event.target.closest?.('[data-monthly-close]');
        if (close) close.closest('dialog')?.close();
    });
    document.addEventListener('submit', event => {
        const form = event.target;
        if (!form.matches?.('[data-monthly-send]') || form.dataset.confirmed === 'yes') return;
        event.preventDefault(); pending = form;
        document.getElementById('monthly-send-count').textContent = 'Publish and email ' + form.dataset.count + ' reviewed bill(s)?';
        open(confirm);
    });
    document.getElementById('monthly-confirm-send')?.addEventListener('click', event => {
        if (!pending) return;
        event.currentTarget.disabled = true;
        pending.dataset.confirmed = 'yes';
        pending.requestSubmit();
        pending = null;
    });
})();

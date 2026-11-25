(() => {
    const modal = document.getElementById("jr-details-dialog");
    // Regular links and POST forms remain usable without dialog/fetch support.
    if (!modal || typeof modal.showModal !== "function" || typeof window.fetch !== "function") return;
    const content = document.getElementById("jr-dialog-content");
    const closeButton = document.getElementById("jr-details-close");
    const feedback = document.getElementById("jr-client-feedback");
    const recovery = document.getElementById("jr-recovery");
    const loginAgain = document.getElementById("jr-login-again");
    const liveStatus = document.getElementById("jr-modal-status");
    const headers = { "Accept": "application/json", "X-Join-Request-Modal": "1" };
    let generation = 0;
    let saving = false;
    let currentUrl = null;
    let opener = null;
    let busyControls = [];
    let pageScroll = null;

    function setSaving(value) {
        saving = value;
        modal.setAttribute("aria-busy", String(value));
        closeButton.disabled = value;
        if (value) {
            busyControls = [...content.querySelectorAll("button")].map(control => [control, control.disabled]);
            for (const [control] of busyControls) control.disabled = true;
            liveStatus.textContent = "Saving your decision. Please wait.";
        } else {
            for (const [control, wasDisabled] of busyControls) control.disabled = wasDisabled;
            busyControls = [];
        }
    }

    function clearFeedback() {
        feedback.hidden = true;
        feedback.textContent = "";
        recovery.hidden = true;
        loginAgain.hidden = true;
    }

    function showFeedback(message, expired = false) {
        if (!content.querySelector("#request-details")) content.replaceChildren();
        feedback.textContent = message;
        feedback.hidden = false;
        recovery.hidden = false;
        loginAgain.hidden = !expired;
        feedback.focus();
        liveStatus.textContent = message;
    }

    function closeDetails() {
        if (!saving && modal.open) modal.close();
    }
    closeButton.addEventListener("click", closeDetails);
    modal.addEventListener("cancel", event => { event.preventDefault(); closeDetails(); });
    modal.addEventListener("click", event => {
        const rect = modal.getBoundingClientRect();
        if (event.target === modal && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) closeDetails();
    });
    modal.addEventListener("close", () => {
        if (modal.open) return;
        generation++; // Ignore a late GET response after the Owner closes the dialog.
        document.body.removeAttribute("data-jr-modal-open");
        if (opener?.isConnected) opener.focus({ preventScroll: true });
        else document.getElementById("jr-results")?.focus({ preventScroll: true });
        if (pageScroll && typeof window.scrollTo === "function") window.scrollTo(pageScroll.x, pageScroll.y);
    });

    function updatePage(payload) {
        const current = document.getElementById("jr-results");
        if (current && payload.results_html) {
            const form = current.querySelector(".jr-filters");
            const edits = ["q", "status", "sort"].map(name => [name, form?.elements.namedItem(name)?.value]);
            const template = document.createElement("template");
            template.innerHTML = payload.results_html;
            const replacement = template.content.querySelector("#jr-results");
            if (replacement) {
                current.replaceWith(replacement);
                for (const [name, value] of edits) {
                    const field = replacement.querySelector(".jr-filters")?.elements.namedItem(name);
                    if (field && value !== undefined) field.value = value;
                }
            }
        }
        if (!payload.summary) return;
        for (const counter of document.querySelectorAll("[data-jr-count]")) {
            const value = payload.summary[counter.dataset.jrCount];
            if (Number.isInteger(value) && value >= 0) counter.textContent = String(value);
        }
        const pending = payload.summary.pending;
        const navigation = document.querySelector('.owner-sidebar a[title="Join Requests"]');
        if (navigation && Number.isInteger(pending) && pending >= 0) {
            let badge = navigation.querySelector(".nav-request-count");
            if (!badge && pending) {
                badge = document.createElement("span");
                badge.className = "nav-status nav-request-count";
                navigation.append(badge);
            }
            if (badge) {
                badge.hidden = !pending;
                badge.textContent = String(pending);
                badge.setAttribute("aria-label", pending + " pending requests");
            }
        }
    }

    async function responseData(response) {
        const type = response.headers.get("Content-Type") || "";
        let payload;
        if (type.includes("application/json")) payload = await response.json();
        if (!payload?.html) {
            const failure = new Error("Request unavailable");
            failure.expired = response.status === 401 || response.redirected;
            failure.safeMessage = payload?.error || (failure.expired
                ? "Your session expired. Log in again to continue."
                : response.status === 400 ? "The form expired. Refresh this request before trying again."
                : "Could not load the current request. Refresh before trying again.");
            throw failure;
        }
        return payload;
    }

    function initializeDetails(preferredStep = "details") {
        const root = content.querySelector("#request-details");
        if (!root) return;
        const steps = [...root.querySelectorAll("[data-jr-step]")];
        function showStep(name) {
            if (saving) return;
            const step = steps.find(item => item.dataset.jrStep === name) || steps[0];
            for (const item of steps) item.hidden = item !== step;
            root.dataset.currentStep = step.dataset.jrStep;
            content.scrollTop = 0;
            const field = step.querySelector('[aria-invalid="true"]') || step.querySelector("select, textarea, input:not([type=hidden])");
            (field || root).focus({ preventScroll: !field });
            liveStatus.textContent = step.dataset.jrStep === "details" ? "Request details loaded." : "Review and confirm your " + step.dataset.jrStep + " decision.";
        }
        for (const kind of ["approve", "reject"]) {
            const button = root.querySelector("#jr-" + kind + "-open");
            if (button) {
                button.hidden = false;
                button.addEventListener("click", () => showStep(kind));
            }
        }
        for (const control of root.querySelectorAll("[data-jr-back]")) {
            control.hidden = false;
            control.addEventListener("click", event => { event.preventDefault(); showStep("details"); });
        }
        for (const control of root.querySelectorAll("[data-jr-close]")) {
            control.addEventListener("click", event => { event.preventDefault(); closeDetails(); });
        }
        const unit = root.querySelector("#jr-approve-unit");
        const rent = root.querySelector("#jr-approve-rent");
        if (unit && rent) {
            function updateRent() { rent.textContent = unit.selectedOptions[0]?.dataset.rent || "Choose a rental unit to review its agreed monthly rent."; }
            unit.addEventListener("change", updateRent);
            updateRent();
        }
        for (const form of root.querySelectorAll("form")) {
            form.addEventListener("submit", async event => {
                event.preventDefault();
                if (saving || !form.reportValidity()) return;
                const fields = new window.FormData(form);
                const step = root.dataset.currentStep;
                const ticket = generation;
                const submit = form.querySelector('[type="submit"]');
                const label = submit.innerHTML;
                clearFeedback();
                setSaving(true);
                submit.textContent = "Saving\u2026";
                try {
                    // Reuse the CSRF-protected POST; prices and ownership stay server-validated.
                    const response = await window.fetch(form.action, { method: "POST", body: fields, headers, credentials: "same-origin", cache: "no-store" });
                    const payload = await responseData(response);
                    if (ticket !== generation) return;
                    setSaving(false);
                    content.innerHTML = payload.html;
                    updatePage(payload);
                    initializeDetails(response.ok ? "details" : step);
                    if (response.status >= 500) showFeedback(payload.error || "Could not confirm this decision. Refresh the request before trying again.");
                } catch (error) {
                    if (ticket === generation) showFeedback(error.safeMessage || "Could not confirm this decision. Refresh the request to check its status before trying again.", error.expired);
                } finally {
                    setSaving(false);
                    submit.innerHTML = label;
                }
            });
        }
        const invalid = steps.find(step => step.dataset.showError === "true");
        showStep(invalid?.dataset.jrStep || preferredStep);
    }

    async function loadRequest(url, trigger = opener, refreshBackground = false) {
        if (saving) return;
        const address = new URL(url, window.location.href);
        if (address.origin !== window.location.origin) return;
        currentUrl = address.href;
        opener = trigger;
        const ticket = ++generation;
        clearFeedback();
        content.replaceChildren();
        const loading = document.createElement("p");
        loading.className = "jr-loading";
        loading.textContent = "Loading request details\u2026";
        loading.setAttribute("role", "status");
        content.append(loading);
        if (!modal.open) {
            pageScroll = { x: window.scrollX || 0, y: window.scrollY || 0 };
            modal.showModal();
        }
        document.body.setAttribute("data-jr-modal-open", "");
        closeButton.focus();
        try {
            const response = await window.fetch(currentUrl, { headers, credentials: "same-origin", cache: "no-store" });
            const payload = await responseData(response);
            if (ticket !== generation || !modal.open) return;
            content.innerHTML = payload.html;
            if (refreshBackground) updatePage(payload);
            initializeDetails();
        } catch (error) {
            if (ticket === generation && modal.open) showFeedback(error.safeMessage || "Could not load request details. Please try refreshing the request.", error.expired);
        }
    }

    document.addEventListener("click", event => {
        const link = event.target.closest?.("[data-jr-view]");
        if (!link || event.defaultPrevented || event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        loadRequest(link.dataset.dialogUrl, link);
    });
    document.getElementById("jr-refresh-request").addEventListener("click", () => { if (currentUrl) loadRequest(currentUrl, opener, true); });
    const initial = document.getElementById("jr-initial-detail");
    if (initial) {
        currentUrl = new URL(initial.dataset.dialogUrl, window.location.href).href;
        content.replaceChildren(...initial.childNodes);
        initial.remove();
        pageScroll = { x: window.scrollX || 0, y: window.scrollY || 0 };
        modal.showModal();
        document.body.setAttribute("data-jr-modal-open", "");
        initializeDetails();
    }
})();

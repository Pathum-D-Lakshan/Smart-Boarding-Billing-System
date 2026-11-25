(() => {
    const form = document.getElementById("boarding-edit-form") || document.getElementById("room-edit-form") || document.getElementById("bed-edit-form");
    const dialog = document.getElementById("boarding-password-dialog");
    const password = document.getElementById("current_password");
    const saveButton = document.getElementById("boarding-save-changes");
    const confirmButton = document.getElementById("boarding-confirm-save");
    const toggle = document.getElementById("owner-password-toggle");
    function maskPassword() {
        password.type = "password";
        if (toggle) {
            toggle.setAttribute("aria-label", "Show password");
            toggle.setAttribute("aria-pressed", "false");
        }
    }
    if (password && toggle) {
        maskPassword();
        toggle.hidden = false;
        toggle.addEventListener("click", () => {
            const show = password.type === "password";
            password.type = show ? "text" : "password";
            toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
            toggle.setAttribute("aria-pressed", String(show));
        });
    }
    if (!form || !dialog || typeof dialog.showModal !== "function" || typeof HTMLFormElement === "undefined") return;

    const nativeSubmit = HTMLFormElement.prototype.submit;
    const feedback = document.createElement("p");
    feedback.className = "owner-message owner-message-error";
    feedback.setAttribute("role", "alert");
    feedback.hidden = true;
    form.prepend(feedback);
    let submitting = false;
    let focusAfterClose = saveButton;
    // Validate explicitly so a field outside the modal cannot silently block a save.
    form.noValidate = true;

    // Disabled while closed so native form validation can check the edited fields first.
    dialog.close();
    password.value = "";
    password.disabled = true;
    dialog.querySelectorAll("[hidden]").forEach((control) => { control.hidden = false; });

    function openConfirmation() {
        maskPassword();
        password.disabled = false;
        if (!dialog.open) dialog.showModal();
        password.focus();
    }

    dialog.addEventListener("close", () => {
        // An earlier close event can arrive after a password-error dialog reopens.
        if (dialog.open) return;
        password.value = "";
        maskPassword();
        password.disabled = true;
        confirmButton.disabled = false;
        confirmButton.textContent = "Confirm & Save";
        focusAfterClose.focus();
        focusAfterClose = saveButton;
    });
    dialog.querySelectorAll("[data-password-cancel]").forEach((button) => {
        button.addEventListener("click", () => dialog.close());
    });

    form.addEventListener("invalid", (event) => {
        const field = event.target;
        if (field === password) return;
        field.setAttribute("aria-invalid", "true");
        const label = field.labels?.[0]?.textContent?.replace(/\s+/g, " ").trim() || "the highlighted field";
        feedback.textContent = "Please check " + label + ". " + (field.validationMessage || "");
        feedback.hidden = false;
        if (dialog.open) {
            focusAfterClose = field;
            dialog.close();
        }
    }, true);

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (submitting) return;
        feedback.hidden = true;
        if (!dialog.open) {
            password.disabled = true;
            if (!form.reportValidity()) return;
            openConfirmation();
        } else {
            if (!form.reportValidity()) return;
            // Native submission includes checked facilities, files, CSRF and the password.
            // Server-side validation and ownership checks remain authoritative.
            submitting = true;
            confirmButton.disabled = true;
            confirmButton.textContent = "Saving…";
            try {
                nativeSubmit.call(form);
            } catch {
                submitting = false;
                confirmButton.disabled = false;
                confirmButton.textContent = "Confirm & Save";
                dialog.close();
                feedback.textContent = "Could not submit your changes. Please try again.";
                feedback.hidden = false;
            }
        }
    });

    if (typeof window !== "undefined") window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        submitting = false;
        confirmButton.disabled = false;
        confirmButton.textContent = "Confirm & Save";
        password.value = "";
        maskPassword();
        if (dialog.open) dialog.close();
        password.disabled = true;
    });

    document.querySelectorAll('a[href="#current_password"]').forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            openConfirmation();
        });
    });
    if (dialog.dataset.passwordError === "true") openConfirmation();
    else {
        const serverErrors = document.getElementById("boarding-form-errors") || document.getElementById("boarding-save-error");
        if (serverErrors) serverErrors.focus();
    }
})();

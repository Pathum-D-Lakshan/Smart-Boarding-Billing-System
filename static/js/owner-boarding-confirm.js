(() => {
    const form = document.getElementById("boarding-edit-form");
    const dialog = document.getElementById("boarding-password-dialog");
    const password = document.getElementById("current_password");
    const saveButton = document.getElementById("boarding-save-changes");
    const confirmButton = document.getElementById("boarding-confirm-save");
    if (!form || !dialog || typeof dialog.showModal !== "function") return;

    // Disabled while closed so native form validation can check the edited fields first.
    dialog.close();
    password.value = "";
    password.disabled = true;
    dialog.querySelectorAll("[hidden]").forEach((control) => { control.hidden = false; });

    function openConfirmation() {
        password.disabled = false;
        if (!dialog.open) dialog.showModal();
        password.focus();
    }

    dialog.addEventListener("close", () => {
        // An earlier close event can arrive after a password-error dialog reopens.
        if (dialog.open) return;
        password.value = "";
        password.disabled = true;
        confirmButton.disabled = false;
        confirmButton.textContent = "Confirm & Save";
        saveButton.focus();
    });
    dialog.querySelectorAll("[data-password-cancel]").forEach((button) => {
        button.addEventListener("click", () => dialog.close());
    });

    form.addEventListener("submit", (event) => {
        if (!dialog.open) {
            event.preventDefault();
            openConfirmation();
        } else {
            // The normal POST still verifies the password, ownership and CSRF server-side.
            confirmButton.disabled = true;
            confirmButton.textContent = "Saving…";
        }
    });

    document.querySelectorAll('a[href="#current_password"]').forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            openConfirmation();
        });
    });
    if (dialog.dataset.passwordError === "true") openConfirmation();
})();

/* Shared authentication interactions retain the existing OTP and email checks. */
(() => {
    const loginForm = document.querySelector("[data-remember-email]");
    if (loginForm) {
        const email = loginForm.elements.email;
        const remember = document.getElementById("remember-email");
        const key = "smartboarding-remembered-email";
        const valid = value => value.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
        try {
            const saved = localStorage.getItem(key);
            if (saved && valid(saved)) {
                if (!email.value) email.value = saved;
                remember.checked = true;
            } else if (saved) localStorage.removeItem(key);
        } catch { /* Login remains usable when local preferences are blocked. */ }
        function saveEmailPreference() {
            try {
                const value = email.value.trim();
                if (remember.checked && valid(value)) localStorage.setItem(key, value);
                else localStorage.removeItem(key);
            } catch { /* The browser password manager remains independent of this preference. */ }
        }
        remember.addEventListener("change", saveEmailPreference);
        loginForm.addEventListener("submit", saveEmailPreference);
    }
    // Add a Show/Hide eye button to each password field.
    for (const field of document.querySelectorAll('input[type="password"]')) {
        const wrapper = document.createElement("div");
        wrapper.className = "password-field";
        field.before(wrapper);
        wrapper.append(field);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "password-toggle";
        button.setAttribute("aria-controls", field.id);
        button.setAttribute("aria-label", "Show " + field.labels[0].textContent.trim().toLowerCase());
        button.setAttribute("aria-pressed", "false");
        button.title = "Show password";
        button.innerHTML =
            '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2">' +
            '<path d="M2 12c2.5-4 6-6 10-6s7.5 2 10 6c-2.5 4-6 6-10 6S4.5 16 2 12Z"/>' +
            '<circle cx="12" cy="12" r="2.5"/>' +
            '<path class="eye-slash" d="M3 3l18 18" stroke-linecap="round"/>' +
            '</svg>';
        wrapper.append(button);

        button.addEventListener("click", () => {
            const show = field.type === "password";
            field.type = show ? "text" : "password";
            button.setAttribute("aria-pressed", String(show));
            button.title = show ? "Hide password" : "Show password";
            button.setAttribute("aria-label", (show ? "Hide " : "Show ") + field.labels[0].textContent.trim().toLowerCase());
        });
    }

    // Count down from the remaining time supplied by Flask.
    const countdown = document.getElementById("otp-countdown");
    if (countdown) {
        const deadline = Date.now() + Number(countdown.dataset.seconds) * 1000;
        const display = document.getElementById("otp-time");
        const expiredMessage = document.getElementById("otp-expired");
        const verify = document.getElementById("verify-code");
        const resend = document.getElementById("resend-code");

        function updateCountdown() {
            const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            display.textContent = Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
            verify.disabled = seconds === 0;
            resend.disabled = seconds > 0;
            expiredMessage.hidden = seconds > 0;

            if (seconds === 0) clearInterval(timer);
        }

        const timer = setInterval(updateCountdown, 250);
        updateCountdown();
    }

    // Keep the live duplicate-Gmail check on the registration form.
    const registerForm = document.querySelector("[data-email-check]");
    if (registerForm) {
        const email = registerForm.elements.email;
        const feedback = document.getElementById("email-feedback");
        const gmail = /^[a-z0-9]+(?:\.[a-z0-9]+)*(?:\+[a-z0-9._-]+)?@gmail\.com$/i;
        let timer;
        let revision = 0;

        function showEmailError(message) {
            feedback.textContent = message;
            email.setCustomValidity(message);
            email.setAttribute("aria-invalid", String(Boolean(message)));
        }

        email.addEventListener("input", () => {
            clearTimeout(timer);
            const current = ++revision;
            const address = email.value.trim();

            showEmailError("");

            if (!gmail.test(address)) return;

            timer = setTimeout(async () => {
                try {
                    const response = await fetch(registerForm.dataset.emailCheck, {
                        method: "POST",
                        body: new URLSearchParams({
                            email: address,
                            csrf_token: registerForm.elements.csrf_token.value
                        })
                    });

                    if (!response.ok) return;

                    const result = await response.json();
                    if (current === revision && result.registered) {
                        showEmailError("That Gmail is already registered.");
                    }
                } catch {
                    // The server checks the Gmail again when the form is submitted.
                }
            }, 350);
        });

        email.addEventListener("blur", () => {
            const address = email.value.trim();
            if (address && !gmail.test(address)) {
                showEmailError("Enter a valid @gmail.com address.");
            }
        });
    }
})();

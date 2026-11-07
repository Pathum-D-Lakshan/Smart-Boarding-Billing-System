/* DOM mocks exercise our controller; native browser dialog/validation needs browser QA. */
function runBoardingConfirmTests(source) {
    const checks = [];
    function assert(condition, message) {
        if (!condition) throw new Error(message);
    }
    function harness(supportsModal = true, passwordError = "false", queueCloseEvents = false) {
        const closeEvents = [];
        const elements = {};
        const document = {
            activeElement: null,
            getElementById(id) { return elements[id]; },
            querySelectorAll() { return [errorLink]; },
        };
        function element() {
            return {
                handlers: {}, hidden: true, disabled: false, value: "", textContent: "",
                addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); },
                fire(type, event = {}) { for (const handler of this.handlers[type] || []) handler(event); },
                focus() { document.activeElement = this; },
            };
        }
        const form = elements["boarding-edit-form"] = element();
        form.editedValue = "Unsaved boarding details";
        const password = elements.current_password = element();
        const save = elements["boarding-save-changes"] = element();
        const confirm = elements["boarding-confirm-save"] = element();
        const cancel = element();
        const close = element();
        const errorLink = element();
        const dialog = elements["boarding-password-dialog"] = element();
        dialog.open = true;
        dialog.dataset = { passwordError };
        dialog.showCount = 0;
        dialog.close = function () {
            if (!this.open) return;
            this.open = false;
            if (queueCloseEvents) closeEvents.push(() => this.fire("close"));
            else this.fire("close");
        };
        if (supportsModal) dialog.showModal = function () { this.open = true; this.showCount++; };
        dialog.querySelectorAll = (selector) => selector === "[hidden]" ? [close, cancel, confirm] : [close, cancel];
        new Function("document", source)(document);
        function event() { return { prevented: false, preventDefault() { this.prevented = true; } }; }
        function flushCloseEvents() { while (closeEvents.length) closeEvents.shift()(); }
        return { form, password, save, confirm, cancel, close, dialog, document, errorLink, event, flushCloseEvents };
    }

    let page = harness();
    assert(!page.dialog.open && page.password.disabled, "Initial Edit page must defer password confirmation.");
    checks.push("Password deferred until Save Changes");
    let event = page.event();
    page.form.fire("submit", event);
    assert(event.prevented && page.dialog.open && !page.password.disabled, "First save must open dialog without POST.");
    assert(page.document.activeElement === page.password, "Password must receive focus.");
    checks.push("Save opens confirmation and focuses password");
    page.password.value = "test-only-password";
    page.cancel.fire("click");
    assert(!page.dialog.open && page.password.value === "" && page.password.disabled, "Cancel must clear password.");
    assert(page.form.editedValue === "Unsaved boarding details", "Cancel must preserve edited details.");
    assert(page.document.activeElement === page.save, "Cancel must return focus to Save Changes.");
    checks.push("Cancel clears password and preserves unsaved details");

    page.form.fire("submit", page.event());
    page.password.value = "test-only-password";
    event = page.event();
    page.form.fire("submit", event);
    assert(!event.prevented && page.confirm.disabled, "Confirmed save must allow the normal POST.");
    assert(page.password.value === "test-only-password" && !page.password.disabled, "Password must remain available for form serialization.");
    checks.push("Confirmation permits normal POST and prevents repeated confirm clicks");
    page.dialog.close();
    assert(!page.confirm.disabled && page.password.value === "", "Closing must reset controls and password.");
    checks.push("Dialog close resets confirmation state");

    page = harness(true, "true");
    assert(page.dialog.open && page.document.activeElement === page.password, "Password-only server error must reopen confirmation.");
    checks.push("Server password error reopens dialog");
    page = harness(true, "true", true);
    page.flushCloseEvents();
    assert(page.dialog.open && !page.password.disabled, "Delayed initial close event must not disable the reopened password field.");
    assert(page.document.activeElement === page.password, "Retry field must retain focus after delayed close.");
    checks.push("Wrong-password retry stays editable after delayed close event");
    page.password.value = "corrected-test-password";
    event = page.event();
    page.form.fire("submit", event);
    assert(!event.prevented && !page.password.disabled && page.password.value === "corrected-test-password", "Corrected password must be included in the retry POST.");
    checks.push("Corrected password can be submitted after retry");
    page = harness(true, "true", true);
    page.flushCloseEvents();
    page.password.value = "test-only-password";
    page.cancel.fire("click");
    page.flushCloseEvents();
    assert(!page.dialog.open && page.password.disabled && page.password.value === "", "Actual cancel must still clear and disable the password field.");
    checks.push("Cancel still clears the password with queued close events");
    page = harness();
    event = page.event();
    page.errorLink.fire("click", event);
    assert(event.prevented && page.dialog.open, "Password error summary link must open confirmation.");
    checks.push("Error summary link opens password dialog");
    page = harness(false);
    assert(page.dialog.open && !page.password.disabled && page.confirm.hidden, "Unsupported dialogs must retain inline form fallback.");
    checks.push("Inline fallback without modal support");
    return { passed: checks.length, checks };
}

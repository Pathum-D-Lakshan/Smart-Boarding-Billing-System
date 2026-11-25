/* Run before stylesheets to apply only the non-sensitive theme preference. */
(() => {
    const key = "smartboarding-theme";
    const root = document.documentElement;
    function savedTheme() {
        try { return localStorage.getItem(key) === "light" ? "light" : "dark"; }
        catch { return "dark"; }
    }
    function apply(theme) {
        root.dataset.theme = theme === "light" ? "light" : "dark";
        for (const button of document.querySelectorAll("[data-theme-toggle]")) {
            const label = "Switch to " + (root.dataset.theme === "light" ? "Dark" : "Light") + " Mode";
            button.setAttribute("aria-label", label);
            button.setAttribute("title", label);
            button.setAttribute("aria-pressed", String(root.dataset.theme === "light"));
        }
    }
    function save(theme) {
        apply(theme);
        try { localStorage.setItem(key, root.dataset.theme); return true; } catch { return false; /* Switching remains usable without storage. */ }
    }
    // Settings previews and confirmed saves share the same non-sensitive preference.
    window.SmartBoardingTheme = Object.freeze({ preview: apply, save, saved: savedTheme });
    apply(savedTheme());
    function connectControls() {
        apply(root.dataset.theme);
        document.addEventListener("click", event => {
            if (!event.target.closest?.("[data-theme-toggle]")) return;
            const theme = root.dataset.theme === "light" ? "dark" : "light";
            save(theme);
        });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connectControls, { once: true });
    else connectControls();
    window.addEventListener("pageshow", () => apply(savedTheme()));
    window.addEventListener("storage", event => { if (event.key === key) apply(event.newValue === "light" ? "light" : "dark"); });
})();

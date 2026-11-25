/* Keep the boarding image steady when changing between authentication forms. */
(() => {
    if (!window.matchMedia("(prefers-reduced-motion: no-preference)").matches) return;
    const root = document.documentElement;
    root.classList.add("auth-enter");
    if (!document.referrer) return;
    const previous = new URL(document.referrer);
    if (previous.origin === window.location.origin && previous.pathname === document.currentScript.dataset.authHome) {
        root.classList.add("auth-enter-from-home");
    }
})();

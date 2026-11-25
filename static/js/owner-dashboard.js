(() => {
    const dashboard = document.body;
    const page = document.getElementById("owner-page");
    const sidebar = document.getElementById("owner-sidebar");
    const toggle = document.getElementById("sidebar-toggle");
    const close = document.getElementById("sidebar-close");
    const backdrop = document.getElementById("sidebar-backdrop");
    const mobile = window.matchMedia("(max-width: 800px)");
    const menuRole = dashboard.classList.contains('student-portal') ? 'student' : dashboard.classList.contains('admin-portal') ? 'admin' : 'owner';
    const compactPreferenceKey = menuRole + "-sidebar-compact";

    // Store only the UI preference; navigation still works if storage is blocked.
    try {
        dashboard.toggleAttribute("data-sidebar-compact", localStorage.getItem(compactPreferenceKey) === "true");
    } catch {
        // Fall back to the expanded desktop menu.
    }

    function updateToggle() {
        const expanded = mobile.matches
            ? dashboard.hasAttribute("data-drawer-open")
            : !dashboard.hasAttribute("data-sidebar-compact");
        const action = mobile.matches
            ? (expanded ? "Close" : "Open")
            : (expanded ? "Collapse" : "Expand");

        toggle.setAttribute("aria-expanded", String(expanded));
        toggle.setAttribute("aria-label", action + " " + menuRole + " menu");
    }

    // Keep keyboard focus in the active area when using the mobile drawer.
    function setDrawer(open) {
        const wasOpen = dashboard.hasAttribute("data-drawer-open");
        dashboard.toggleAttribute("data-drawer-open", open);
        close.hidden = !open;
        backdrop.hidden = !open;
        page.inert = open;
        updateToggle();

        if (open) {
            close.focus();
        } else if (wasOpen) {
            toggle.focus();
        }
    }

    toggle.addEventListener("click", () => {
        if (mobile.matches) {
            setDrawer(!dashboard.hasAttribute("data-drawer-open"));
        } else {
            dashboard.toggleAttribute("data-sidebar-compact");
            try {
                localStorage.setItem(compactPreferenceKey, String(dashboard.hasAttribute("data-sidebar-compact")));
            } catch {
                // Keep the current page's menu usable without persistent storage.
            }
            updateToggle();
        }
    });

    close.addEventListener("click", () => setDrawer(false));
    backdrop.addEventListener("click", () => setDrawer(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && dashboard.hasAttribute("data-drawer-open")) {
            setDrawer(false);
        }
    });

    mobile.addEventListener("change", () => {
        const focusedInSidebar = sidebar.contains(document.activeElement);
        setDrawer(false);
        if (mobile.matches && focusedInSidebar) {
            toggle.focus();
        }
    });

    // The sidebar is visible by default until its toggle is ready.
    updateToggle();
    toggle.hidden = false;
    dashboard.setAttribute("data-nav-ready", "");
})();

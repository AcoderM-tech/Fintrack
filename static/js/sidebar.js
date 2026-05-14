/**
 * FinTrack Sidebar — complete rewrite
 * Fixes:
 *  1. State stored in a JS variable (not just DOM classes) → no race on resize/orientation
 *  2. Body scroll locked while sidebar is open on mobile
 *  3. Touch swipe-to-close support
 *  4. Works after HTMX partial swaps (re-binds on htmx:afterSettle)
 *  5. Correct active link detection incl. scope/family query-params
 *  6. Sidebar nav links navigate correctly on mobile (close then navigate)
 *  7. Keyboard: Escape closes sidebar
 */
(function () {
    'use strict';

    /* ── breakpoints ── */
    const MQ_TABLET  = window.matchMedia('(max-width: 1024px)');
    const MQ_MOBILE  = window.matchMedia('(max-width: 768px)');

    /* ── state ── */
    let _open = false;

    /* ── element accessors ── */
    function sidebar()  { return document.getElementById('sidebar');  }
    function overlay()  { return document.getElementById('overlay');  }
    function menuBtn()  { return document.getElementById('mobileMenuBtn'); }

    /* ── open / close ── */
    function setOpen(next) {
        if (_open === next) return;
        _open = next;

        const s = sidebar();
        const o = overlay();
        if (!s || !o) return;

        s.classList.toggle('open', next);
        o.classList.toggle('show', next);

        // Lock body scroll only on mobile overlay mode
        if (MQ_TABLET.matches) {
            document.body.style.overflow = next ? 'hidden' : '';
        }

        // Update aria
        if (menuBtn()) {
            menuBtn().setAttribute('aria-expanded', String(next));
        }
        s.setAttribute('aria-hidden', String(!next && MQ_MOBILE.matches));
    }

    /* ── public API ── */
    window.toggleSidebar = function () {
        if (MQ_TABLET.matches) {
            // Mobile / tablet: drawer mode
            setOpen(!_open);
        } else {
            // Desktop: collapse/expand icon-only mode
            setOpen(false);   // ensure overlay is closed
            document.body.classList.toggle('sidebar-collapsed');
        }
    };

    window.closeSidebar = function () {
        setOpen(false);
        // Also remove desktop-collapse when called from mobile breakpoint
        if (!MQ_TABLET.matches) {
            // don't remove on desktop — keep collapsed state
        }
    };

    /* ── resize / orientation ── */
    MQ_TABLET.addEventListener('change', function (e) {
        if (!e.matches) {
            // Moved to desktop — close drawer, restore scroll
            setOpen(false);
            document.body.style.overflow = '';
        } else {
            // Moved to tablet/mobile — remove desktop collapse
            document.body.classList.remove('sidebar-collapsed');
        }
    });

    /* ── overlay click / touch ── */
    document.addEventListener('click', function (e) {
        if (!_open) return;
        const o = overlay();
        if (o && o.contains(e.target)) {
            setOpen(false);
        }
    });

    /* ── swipe to close (touch) ── */
    (function initSwipe() {
        let touchStartX = 0;
        let touchStartY = 0;

        document.addEventListener('touchstart', function (e) {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }, { passive: true });

        document.addEventListener('touchend', function (e) {
            if (!_open) return;
            const dx = e.changedTouches[0].clientX - touchStartX;
            const dy = e.changedTouches[0].clientY - touchStartY;
            // Swipe left ≥ 60px, horizontal dominant → close
            if (dx < -60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
                setOpen(false);
            }
        }, { passive: true });
    })();

    /* ── keyboard ── */
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && _open) {
            setOpen(false);
        }
    });

    /* ── sidebar link navigation on mobile ── */
    document.addEventListener('DOMContentLoaded', function () {
        bindSidebarLinks();
        syncActiveNav();
        syncMobileNav();
    });

    function bindSidebarLinks() {
        const nav = document.querySelector('.sidebar-nav');
        if (!nav || nav.dataset.sidebarBound) return;
        nav.dataset.sidebarBound = '1';

        nav.addEventListener('click', function (e) {
            if (!MQ_TABLET.matches) return;  // desktop: HTMX handles it normally

            const link = e.target.closest('a.nav-link');
            if (!link) return;
            const href = link.getAttribute('href');
            if (!href || href === '#') return;

            // Close sidebar first, then navigate after short delay for animation
            e.preventDefault();
            e.stopPropagation();
            setOpen(false);
            setTimeout(function () {
                window.location.href = href;
            }, 220);
        }, { capture: true });
    }

    /* ── nav group toggles ── */
    function initNavToggles(root) {
        root = root || document;
        root.querySelectorAll('[data-nav-toggle]').forEach(function (btn) {
            if (btn.dataset.navBound) return;
            btn.dataset.navBound = '1';
            btn.addEventListener('click', function () {
                const group = btn.closest('.nav-group');
                if (group) group.classList.toggle('open');
            });
        });
    }

    /* ── active nav sync ── */
    function syncActiveNav() {
        const state  = document.getElementById('nav-state');
        const fullpath = (state && state.dataset.fullpath) || '';
        const current  = fullpath
            ? new URL(fullpath, window.location.origin)
            : new URL(window.location.href);
        const scope    = (state && state.dataset.scope)  || current.searchParams.get('scope') || 'personal';
        const familyId = (state && state.dataset.family) || '';
        const path     = (state && state.dataset.path)   || current.pathname;
        const curType  = (state && state.dataset.type)   || current.searchParams.get('type') || '';

        const links = Array.from(document.querySelectorAll('.sidebar-nav a.nav-link'));
        links.forEach(function (l) { l.classList.remove('active'); });
        document.querySelectorAll('.nav-group').forEach(function (g) { g.classList.remove('open'); });
        document.querySelectorAll('.nav-group-toggle').forEach(function (b) { b.classList.remove('active'); });

        let best = null, bestScore = -1;
        links.forEach(function (link) {
            let url;
            try { url = new URL(link.href, window.location.origin); } catch (e) { return; }
            if (url.pathname !== path) return;

            const ls = url.searchParams.get('scope');
            if (ls && ls !== scope) return;
            const lf = url.searchParams.get('family_id');
            if (lf && familyId && lf !== familyId) return;
            if (lf && !familyId) return;
            const lt = url.searchParams.get('type');
            if (lt && curType && lt !== curType) return;
            if (lt && !curType) return;

            let score = 1;
            if (ls) score += 2;
            if (lf) score += 2;
            if (lt && curType && lt === curType) score += 3;
            if (score > bestScore) { bestScore = score; best = link; }
        });

        if (!best) {
            best = links.find(function (l) {
                return (l.getAttribute('href') || '').startsWith(path);
            }) || null;
        }

        if (best) {
            best.classList.add('active');
            const group = best.closest('.nav-group');
            if (group) {
                group.classList.add('open');
                const toggle = group.querySelector('.nav-group-toggle');
                if (toggle) toggle.classList.add('active');
            }
        }
    }

    /* ── mobile bottom nav active ── */
    function syncMobileNav() {
        const path  = window.location.pathname;
        const items = document.querySelectorAll('.mobile-nav-item[href], .mobile-nav-fab[href]');
        items.forEach(function (item) { item.classList.remove('active'); });

        let best = null, bestLen = 0;
        items.forEach(function (item) {
            const href = item.getAttribute('href') || '';
            let itemPath = '';
            try { itemPath = new URL(href, window.location.origin).pathname; } catch (e) {}
            if (itemPath && path.startsWith(itemPath) && itemPath.length > bestLen) {
                bestLen = itemPath.length;
                best = item;
            }
        });
        if (best) best.classList.add('active');
    }

    /* ── init & re-init after HTMX swaps ── */
    function init(root) {
        root = root || document;
        initNavToggles(root);
        syncActiveNav();
        syncMobileNav();
    }

    // Initial run
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(); bindSidebarLinks(); });
    } else {
        init();
        bindSidebarLinks();
    }

    // After HTMX partial swap
    document.addEventListener('htmx:afterSettle', function (e) {
        if (!e.target || e.target.id !== 'main-content') return;
        syncActiveNav();
        syncMobileNav();
        // Close sidebar after navigation on mobile
        if (MQ_TABLET.matches && _open) {
            setOpen(false);
        }
    });

    // Expose helpers for HTMX handlers
    window._ft = window._ft || {};
    window._ft.syncActiveNav = syncActiveNav;
    window._ft.syncMobileNav = syncMobileNav;
    window._ft.init = init;

})();

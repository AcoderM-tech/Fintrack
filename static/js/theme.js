/**
 * FinTrack Theme Toggle + Language Switcher
 * Extracted from inline base.html scripts.
 */
(function () {
    'use strict';

    const THEME_KEY = 'fintrack_theme';

    /* ── Theme ── */
    function getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || 'dark';
    }

    function updateToggleIcon(toggle, resolved) {
        if (!toggle) return;
        toggle.innerHTML = resolved === 'light'
            ? '<i class="ti ti-moon"></i>'
            : '<i class="ti ti-sun"></i>';
        const labelLight = toggle.dataset.labelLight || 'Night mode';
        const labelDark  = toggle.dataset.labelDark  || 'Day mode';
        const label = resolved === 'light' ? labelLight : labelDark;
        toggle.setAttribute('aria-label', label);
        toggle.setAttribute('title', label);
    }

    function applyTheme(theme) {
        const resolved = theme === 'light' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', resolved);
        const metaTheme = document.querySelector('meta[name="theme-color"]');
        if (metaTheme) {
            metaTheme.setAttribute('content', resolved === 'light' ? '#f5f7fb' : '#0a0e27');
        }
        document.querySelectorAll('#themeToggle').forEach(function (t) {
            updateToggleIcon(t, resolved);
        });
    }

    function bindThemeToggle(root) {
        root = root || document;
        root.querySelectorAll('#themeToggle').forEach(function (toggle) {
            if (toggle.dataset.themeBound) return;
            toggle.dataset.themeBound = '1';
            toggle.addEventListener('click', function () {
                const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
                localStorage.setItem(THEME_KEY, next);
                applyTheme(next);
            });
        });
        const t = root.querySelector('#themeToggle');
        if (t) updateToggleIcon(t, getCurrentTheme());
    }

    // Apply stored / OS theme on load
    const stored     = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(stored || (prefersDark ? 'dark' : 'light'));
    document.addEventListener('DOMContentLoaded', function () { bindThemeToggle(document); });

    // Expose for HTMX re-bind
    window.applyTheme      = applyTheme;
    window.bindThemeToggle = bindThemeToggle;

    /* ── Language Switcher ── */
    function initLangSwitch(root) {
        root = root || document;
        root.querySelectorAll('.lang-switch').forEach(function (form) {
            if (form.dataset.langBound) return;
            form.dataset.langBound = '1';

            const input   = form.querySelector('input[name="language"]');
            const dots    = Array.from(form.querySelectorAll('.lang-flag-dot'));
            const order   = (form.dataset.langOrder || 'uz,ru,en')
                .split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);

            function submitForm() {
                if (typeof form.requestSubmit === 'function') form.requestSubmit();
                else form.submit();
            }

            function applyLang(lang, submit) {
                const resolved = order.includes(lang) ? lang : (order[0] || 'uz');
                if (input) input.value = resolved;
                dots.forEach(function (dot) {
                    dot.classList.toggle('active', dot.dataset.lang === resolved);
                });
                if (submit) submitForm();
            }

            const current = (input && input.value) || order[0] || 'uz';
            applyLang(current, false);

            dots.forEach(function (dot) {
                dot.addEventListener('click', function () {
                    const lang = (dot.dataset.lang || '').toLowerCase();
                    if (!lang) return;
                    applyLang(lang, true);
                });
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () { initLangSwitch(document); });
    window.initLangSwitch = initLangSwitch;

    /* ── Re-bind after HTMX ── */
    document.addEventListener('htmx:afterSettle', function () {
        bindThemeToggle(document);
        initLangSwitch(document);
    });

})();

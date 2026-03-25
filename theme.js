// Theme toggle — persists in localStorage
(function() {
    const saved = localStorage.getItem('ml-platform-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);

    // Inject toggle button into header
    document.addEventListener('DOMContentLoaded', function() {
        const header = document.querySelector('header');
        if (!header) return;

        const btn = document.createElement('button');
        btn.className = 'theme-toggle';
        btn.title = 'Toggle light/dark mode';
        btn.setAttribute('aria-label', 'Toggle light/dark mode');
        updateIcon(btn);

        btn.addEventListener('click', function() {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('ml-platform-theme', next);
            updateIcon(btn);
        });

        header.appendChild(btn);
    });

    function updateIcon(btn) {
        const theme = document.documentElement.getAttribute('data-theme');
        btn.textContent = theme === 'light' ? '\u{1F319}' : '\u{2600}\u{FE0F}';
    }
})();

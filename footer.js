// Easter egg footer
(function() {
    document.addEventListener('DOMContentLoaded', function() {
        const footer = document.createElement('div');
        footer.style.cssText = 'text-align:center;padding:32px;font-size:13px;color:var(--text-faint);';
        footer.innerHTML = 'Made with <span id="easter-egg" style="cursor:default;font-size:16px;transition:transform 0.2s;display:inline-block;">\u2764\uFE0F</span>';

        const egg = footer.querySelector('#easter-egg');
        egg.addEventListener('mouseenter', function() { egg.textContent = '\uD83C\uDF2E'; egg.style.cursor = 'pointer'; });
        egg.addEventListener('mouseleave', function() { egg.textContent = '\u2764\uFE0F'; egg.style.cursor = 'default'; });
        egg.addEventListener('click', function() { window.open('https://tacospin.com/', '_blank'); });

        document.body.appendChild(footer);
    });
})();

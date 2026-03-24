/* --- HTMX Security: CSRF Token Injection --- */
document.addEventListener('htmx:configRequest', (event) => {
    // Pull the token from the meta tag in the head
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    event.detail.headers['X-CSRFToken'] = csrfToken;
});

/* --- UI Component: Universal Tab Switcher --- */
function switchTab(tabName) {
    // 1. Hide all panes within the current context
    document.querySelectorAll('.report-pane').forEach(p => p.classList.add('hidden'));
    
    // 2. Show target pane
    const targetPane = document.getElementById('pane-' + tabName);
    if (targetPane) targetPane.classList.remove('hidden');

    // 3. Reset all tab button styles
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('bg-white', 'border-gray-200', 'text-blue-600', 'z-10');
        btn.classList.add('bg-gray-100', 'border-transparent', 'text-gray-400');
    });

    // 4. Apply Active styles to selected button
    const activeBtn = document.getElementById('tab-btn-' + tabName);
    if (activeBtn) {
        activeBtn.classList.remove('bg-gray-100', 'border-transparent', 'text-gray-400');
        activeBtn.classList.add('bg-white', 'border-gray-200', 'text-blue-600', 'z-10');
    }
}
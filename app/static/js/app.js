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

/**
 * Sync Engine: Arms a one-time refresh trigger when the window gains focus.
 * Used for "Print" workflows where data changes in a separate tab.
 */
function armFocusSync(url) {
    const container = document.getElementById('focus-sync-container');
    if (!container) {
        console.warn("Sync Engine: #focus-sync-container not found. Refresh aborted.");
        return;
    }

    console.log("Sync Engine: Arming refresh for:", url);

    // 100ms delay ensures the browser focus has fully shifted 
    // to the new tab before we set the "trap" on this one.
    setTimeout(() => {
        container.innerHTML = `
            <div hx-get="${url}" 
                 hx-trigger="focus from:window" 
                 hx-target="#main-content-area" 
                 hx-select="#main-content-area" 
                 hx-swap="innerHTML">
            </div>`;
        
        // Re-initialize HTMX for the newly injected element
        htmx.process(container);
        console.log("Sync Engine: Listener active.");
    }, 100);
}
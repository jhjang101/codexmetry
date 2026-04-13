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

/**
 * Universal Chart.js Initializer
 * Logic: Reads data from DOM, destroys old instances, and applies professional styling.
 */
function initReportChart(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // 1. Capture data from the canvas's own data-attribute
    const rawData = canvas.getAttribute('data-chart-values');
    if (!rawData) return;
    const data = JSON.parse(rawData);

    // 2. Memory Protection: Wipe old chart instance if it exists
    const existingChart = Chart.getChart(canvas);
    if (existingChart) existingChart.destroy();

    // 3. Determine View (Pane 4 uses horizontal bars)
    const isBar = canvasId.includes('clientChart'); 
    
    new Chart(canvas.getContext('2d'), {
        type: isBar ? 'bar' : 'line',
        data: data,
        options: {
            indexAxis: isBar ? 'y' : 'x',
            responsive: true,
            maintainAspectRatio: false, // Critical: Allows inline style to control height
            maxBarThickness: 40,        // Forensic standard: Prevents 'huge' bars
            plugins: {
                legend: { 
                    display: !isBar, 
                    position: 'bottom',
                    labels: { boxWidth: 12, font: { size: 9, weight: 'bold' } }
                }
            },
            scales: {
                x: { 
                    grid: { color: '#f8fafc' }, // Subtle grid lines
                    ticks: { 
                        font: { size: 9 },
                        callback: function(value) {
                            // If Bar, this is a Price. If Line, this is a Month string.
                            if (isBar) return '$' + value.toLocaleString();
                            return this.getLabelForValue(value);
                        }
                    } 
                },
                y: { 
                    grid: { color: '#f1f5f9' }, // Subtle grid lines
                    ticks: { 
                        font: { size: 10, weight: isBar ? 'bold' : 'normal' },
                        callback: function(value) {
                            // If Bar, this is a Client Name string. If Line, this is a Price.
                            if (isBar) return this.getLabelForValue(value);
                            return '$' + value.toLocaleString();
                        }
                    } 
                }
            }
        }
    });
}

/**
 * THE FORTRESS DISPATCHER:
 * Wakes up after HTMX finishes a swap and paints the screen.
 */
document.addEventListener('htmx:afterSettle', function(evt) {
    const charts = ['accrualChart', 'cashChart', 'clientChart'];
    
    // Pushes the execution to the end of the current browser task queue
    setTimeout(() => {
        charts.forEach(id => {
            if (document.getElementById(id)) initReportChart(id);
        });
    }, 0);
});
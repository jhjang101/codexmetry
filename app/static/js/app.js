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

    // 3. Determine View (horizontal bars, doughnuts)
    const isBar = canvasId.includes('clientChart') || 
                  canvasId.includes('productChart') || 
                  canvasId.includes('vendorChart');

    const isDoughnut = canvasId.includes('categoryChart') || 
                       canvasId.includes('expenseCategoryChart');

    // Determine Type string for Chart.js
    let chartType = 'line';
    if (isBar) chartType = 'bar';
    if (isDoughnut) chartType = 'doughnut';

    new Chart(canvas.getContext('2d'), {
        type: chartType,
        data: data,
        options: {
            indexAxis: isBar ? 'y' : 'x',
            responsive: true,
            maintainAspectRatio: false, // Critical: Allows inline style to control height
            maxBarThickness: 40,        // Forensic standard: Prevents 'huge' bars
            plugins: {
                legend: { 
                    display: !isBar, // Bar charts hide legend, Doughnut/Line show them
                    position: isDoughnut ? 'right' : 'bottom',
                    labels: { boxWidth: 10, font: { size: 10, weight: 'bold' } }
                }
            },
            // Only define scales if NOT a doughnut (Doughnuts have no axes)
            scales: isDoughnut ? {} : {
                x: { 
                    grid: { color: '#f3f4f6' }, // Subtle grid lines
                    ticks: { 
                        font: { size: 10 },
                        color: '#4b5563',
                        callback: function(v) { return isBar ? '$' + v.toLocaleString() : this.getLabelForValue(v); }
                    } 
                },
                y: { 
                    grid: { color: '#f3f4f6' }, // Subtle grid lines
                    ticks: { 
                        font: { size: 10, weight: isBar ? 'bold' : 'normal' },
                        color: '#4b5563',
                        callback: function(v) { return isBar ? this.getLabelForValue(v) : '$' + v.toLocaleString(); }
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
    const charts = [
        'accrualChart', 'cashChart', 'clientChart', 
        'categoryChart', 'productChart', 
        'expenseCategoryChart', 'vendorChart'
    ];
    setTimeout(() => {
        charts.forEach(id => {
            if (document.getElementById(id)) initReportChart(id);
        });
    }, 50);
});


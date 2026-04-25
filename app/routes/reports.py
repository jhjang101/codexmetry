from flask import Blueprint, render_template, request, g
from flask_login import login_required
from datetime import datetime, date
import calendar
from zoneinfo import ZoneInfo
from ..services.monthly_reports_service import MonthlyReportService
from ..services.history_reports_service import HistoryReportService
from ..services.analytics_report_service import AnalyticsReportService
from ..services.settings_service import MetadataService
from ..extensions import db
import json

bp = Blueprint('reports', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

@bp.route('/')
def index():
    """
    Messenger: Orchestrates date range selection and fetches the 
    Dual-Perspective financial package from the MonthlyReportService.
    """
    # 1. Determine Business Today (Timezone Aware)
    today = datetime.now(ZoneInfo(g.office_tz))

    # 2. Extract Month/Year from URL (Fallback to Current)
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    # 3. Calculate Date Boundaries (First to Last day of month)
    try:
        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
    except (ValueError, OverflowError):
        # Safety fallback for invalid date inputs
        _, last_day = calendar.monthrange(today.year, today.month)
        start_date = date(today.year, today.month, 1)
        end_date = date(today.year, today.month, last_day)
        year, month = today.year, today.month

    # 4. Brain Call: Fetch the 6-Table Financial Package
    data = MonthlyReportService.get_financial_package(start_date, end_date)

    # 5. Render Full Page (Standard GET)
    return render_template(
        'reports/reports.html', 
        data=data, 
        year=year, 
        month=month, 
        calendar=calendar
    )

# --- HISTORY ROUTES ---

@bp.route('/accrual-history')
def accrual_history():
    """Messenger: Fetches 5-year performance data for the Accrual pane."""
    # 1. Capture user intent (default to monthly)
    mode = request.args.get('mode', 'monthly')
    
    # 2. Fetch the 60-month raw data
    history = HistoryReportService.get_historical_summary(years=5)
    
    # 3. Transform raw data into structured Chart.js JSON
    chart_data = HistoryReportService.get_chart_data(history, perspective='accrual', mode=mode)
    
    return render_template('reports/partials/accrual_history_table.html', 
                           history=history, 
                           chart_json=json.dumps(chart_data),
                           current_mode=mode) # Pass mode to keep dropdown in sync

@bp.route('/cash-history')
def cash_history():
    """Messenger: Fetches 5-year liquidity data for the Cash pane."""
    # Reuse the same service (Zero bloat)
    mode = request.args.get('mode', 'monthly')
    
    history = HistoryReportService.get_historical_summary(years=5)
    
    chart_data = HistoryReportService.get_chart_data(history, perspective='cash', mode=mode)
    
    return render_template('reports/partials/cash_history_table.html', 
                           history=history, 
                           chart_json=json.dumps(chart_data),
                           current_mode=mode)

# --- CLIENT ANALYTICS ROUTES ---

@bp.route('/client-performance')
def client_performance():
    """Messenger: Yearly client ranking and bar chart data."""
    # 1. Capture parameters
    today = datetime.now(ZoneInfo(g.office_tz))
    year = request.args.get('year', today.year, type=int)
    mode = request.args.get('mode', 'revenue')

    # 2. Brain Call
    data = AnalyticsReportService.get_client_performance(year, mode)

    # 3. Chart Prep (Top 10)
    top_10 = data['clients'][:10]
    bar_color = '#2563eb' if mode == 'revenue' else '#15803d'
    
    chart_json = {
        'labels': [c['name'] for c in top_10],
        'datasets': [{
            'label': f'Total {mode.capitalize()} ($)',
            'data': [c['amount'] / 100 for c in top_10],
            'backgroundColor': bar_color + '44',
            'borderColor': bar_color,
            'borderWidth': 1
        }]
    }

    return render_template(
        'reports/partials/client_performance.html',
        data=data,
        chart_json=json.dumps(chart_json),
        current_year=year,
        current_mode=mode
    )

# --- PRODUCT ANALYTICS ROUTES ---

@bp.route('/product-performance')
def product_performance():
    """Messenger: Orchestrates product SKU and category analytics."""
    # 1. Capture user selection
    today = datetime.now(ZoneInfo(g.office_tz))
    year = request.args.get('year', today.year, type=int)

    # 2. Brain Call: Get dual aggregation
    data = AnalyticsReportService.get_product_performance(year)

    # 3. GENERATE DYNAMIC BLUE GRADIENT
    # Uses Hue 220 (Tailwind Blue)
    colors = generate_hsl_gradient(hue=220, count=len(data['categories']))
    
    category_chart_json = {
        'labels': [c['name'] for c in data['categories']],
        'datasets': [{
            'data': [c['amount'] / 100 for c in data['categories']],
            'backgroundColor': colors,
            'borderWidth': 1
        }]
    }

    # 4. Visualization B: Top 10 Products (Horizontal Bar)
    top_10 = data['products'][:10]
    product_chart_json = {
        'labels': [p['name'] for p in top_10],
        'datasets': [{
            'label': 'Product Revenue ($)',
            'data': [p['amount'] / 100 for p in top_10],
            'backgroundColor': '#3b82f644',
            'borderColor': '#3b82f6',
            'borderWidth': 1
        }]
    }

    return render_template(
        'reports/partials/product_performance.html',
        data=data,
        category_chart_json=json.dumps(category_chart_json),
        product_chart_json=json.dumps(product_chart_json),
        current_year=year
    )

# --- EXPENSE ANALYTICS ROUTES ---

@bp.route('/expense-performance')
def expense_performance():
    today = datetime.now(ZoneInfo(g.office_tz))
    year = request.args.get('year', today.year, type=int)
    data = AnalyticsReportService.get_expense_performance(year)

    # 1. GROUP BY CLASSIFICATION for gradient generation
    cogs_cats = [c for c in data['categories'] if c['is_cogs']]
    opex_cats = [c for c in data['categories'] if not c['is_cogs']]

    # 2. GENERATE FAMILY GRADIENTS
    # COGS = Red Family (Hue 0) | OPEX = Amber Family (Hue 25)
    cogs_colors = generate_hsl_gradient(hue=0, count=len(cogs_cats), start_l=50, end_l=80)
    opex_colors = generate_hsl_gradient(hue=30, count=len(opex_cats), start_l=50, end_l=80)

    # 3. MAP COLORS BACK TO ORIGINAL SORTED LIST
    # We create iterators to pop colors in order
    c_iter = iter(cogs_colors)
    o_iter = iter(opex_colors)
    
    colors = []
    for cat in data['categories']:
        if cat['is_cogs']:
            colors.append(next(c_iter))
        else:
            colors.append(next(o_iter))
    
    # Prepare Category Chart
    category_json = {
        'labels': [c['name'] for c in data['categories']],
        'datasets': [{
            'data': [c['amount'] / 100 for c in data['categories']],
            'backgroundColor': colors,
            'borderWidth': 1
        }]
    }

    # Prepare Top 10 VENDORS Bar Chart
    top_10_vendors = data['vendors'][:10]
    vendor_json = {
        'labels': [v['name'] for v in top_10_vendors],
        'datasets': [{
            'label': 'Total Paid ($)',
            'data': [v['amount'] / 100 for v in top_10_vendors],
            'backgroundColor': '#ef444444', # Light Red
            'borderColor': '#dc2626',
            'borderWidth': 1
        }]
    }

    return render_template(
        'reports/partials/expense_performance.html',
        data=data,
        category_chart_json=json.dumps(category_json),
        vendor_chart_json=json.dumps(vendor_json), # NEW ID
        current_year=year
    )

# --- HTMX TARGETED AUDIT ROUTES ---

@bp.route('/revenue-audit')
def revenue_audit():
    """Messenger: Targeted sort for the Revenue Audit table."""
    # 1. Context extraction
    raw_month = request.args.get('month', type=int)
    raw_year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    month = int(raw_month) if raw_month else date.today().month
    year = int(raw_year) if raw_year else date.today().year

    # 2. Date windowing
    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    # 3. Brain Call
    rows = MonthlyReportService._get_invoice_audit(start_date, end_date, sort_by, direction)

    # 4. Return only the partial
    return render_template('reports/partials/revenue_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/payment-audit')
def payment_audit():
    """Messenger: Targeted sort for the Payment Audit table."""
    raw_month = request.args.get('month', type=int)
    raw_year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')
    
    month = int(raw_month) if raw_month else date.today().month
    year = int(raw_year) if raw_year else date.today().year

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = MonthlyReportService._get_payment_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/payment_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/expense-audit')
def expense_audit():
    """Messenger: Targeted sort for the Expense Audit table."""
    raw_month = request.args.get('month', type=int)
    raw_year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    month = int(raw_month) if raw_month else date.today().month
    year = int(raw_year) if raw_year else date.today().year

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = MonthlyReportService._get_expense_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/expense_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/adjustment-audit')
def adjustment_audit():
    """Messenger: Targeted sort for the Adjustment Audit table."""
    raw_month = request.args.get('month')
    raw_year = request.args.get('year')
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    month = int(raw_month) if raw_month else date.today().month
    year = int(raw_year) if raw_year else date.today().year

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = MonthlyReportService._get_adjustment_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/adjustment_table.html', 
                           rows=rows, month=month, year=year)

# --- INTERNAL HELPERS ---

def generate_hsl_gradient(hue, count, start_l=50, end_l=80):
    """
    Brain: Generates a list of HSL strings as a gradient.
    hue: 0-360 (0=Red, 35=Amber, 220=Blue)
    """
    if count <= 0: return []
    if count == 1: return [f'hsl({hue}, 90%, {start_l}%)']
    
    step = (end_l - start_l) / (count - 1)
    return [f'hsl({hue}, 90%, {int(start_l + (i * step))}%)' for i in range(count)]
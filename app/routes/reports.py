from flask import Blueprint, render_template, request
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
    metadata = MetadataService.get_by_id(1)
    tz_name = metadata.timezone if metadata else 'America/Chicago'
    today = datetime.now(ZoneInfo(tz_name))

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
    today = datetime.now()
    year = request.args.get('year', today.year, type=int)
    mode = request.args.get('mode', 'revenue')

    # 2. Brain Call
    data = AnalyticsReportService.get_client_performance(year, mode)

    # 3. Chart Prep (Top 10)
    top_10 = data['clients'][:10]
    bar_color = '#3b82f6' if mode == 'revenue' else '#10b981'
    
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
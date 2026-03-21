from flask import Blueprint, render_template, request
from flask_login import login_required
from datetime import datetime, date
import calendar
from zoneinfo import ZoneInfo
from ..services.reports_service import ReportService
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
    Dual-Perspective financial package from the ReportService.
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
    data = ReportService.get_financial_package(start_date, end_date)

    # 5. Render Full Page (Standard GET)
    return render_template(
        'reports/reports.html', 
        data=data, 
        year=year, 
        month=month, 
        calendar=calendar
    )

@bp.route('/trends')
def trends():
    # 1. Fetch data
    history = ReportService.get_historical_summary(years=5)
    
    # 2. Prep Chart.js JSON
    chart_raw = sorted(history, key=lambda x: x['month_label'])
    chart_data = {
        'labels': [m['month_label'] for m in chart_raw],
        'accrual_revenue': [m['accrual']['revenue'] / 100 for m in chart_raw],
        'accrual_net': [m['accrual']['net_income'] / 100 for m in chart_raw],
        'cash_income': [m['cash']['income'] / 100 for m in chart_raw],
        'cash_net': [m['cash']['net_cash'] / 100 for m in chart_raw]
    }

    # 3. Render partial template
    return render_template(
        'reports/partials/trends_content.html',
        history=history,
        chart_json=json.dumps(chart_data)
    )

# --- HTMX TARGETED AUDIT ROUTES ---

@bp.route('/revenue-audit')
def revenue_audit():
    """Messenger: Targeted sort for the Revenue Audit table."""
    # 1. Context extraction
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    # 2. Date windowing
    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    # 3. Brain Call
    rows = ReportService._get_invoice_audit(start_date, end_date, sort_by, direction)

    # 4. Return only the partial
    return render_template('reports/partials/revenue_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/payment-audit')
def payment_audit():
    """Messenger: Targeted sort for the Payment Audit table."""
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = ReportService._get_payment_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/payment_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/expense-audit')
def expense_audit():
    """Messenger: Targeted sort for the Expense Audit table."""
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = ReportService._get_expense_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/expense_table.html', 
                           rows=rows, month=month, year=year)

@bp.route('/adjustment-audit')
def adjustment_audit():
    """Messenger: Targeted sort for the Adjustment Audit table."""
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    sort_by = request.args.get('sort')
    direction = request.args.get('dir')

    _, last_day = calendar.monthrange(year, month)
    start_date, end_date = date(year, month, 1), date(year, month, last_day)

    rows = ReportService._get_adjustment_audit(start_date, end_date, sort_by, direction)

    return render_template('reports/partials/adjustment_table.html', 
                           rows=rows, month=month, year=year)
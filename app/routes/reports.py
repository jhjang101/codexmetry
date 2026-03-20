from flask import Blueprint, render_template, request
from flask_login import login_required
from datetime import datetime, date
import calendar
from zoneinfo import ZoneInfo
from ..services.reports_service import ReportService
from ..services.settings_service import MetadataService
from ..extensions import db

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
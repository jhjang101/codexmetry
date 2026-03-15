from flask import Blueprint, render_template
from flask_login import login_required
from ..services.dashboard_service import DashboardService

bp = Blueprint('dashboard', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

@bp.route('/')
@bp.route('/dashboard')
def index():
    # Messenger: Simply requests the full data payload from the Brain
    data = DashboardService.get_dashboard_data()
    return render_template('dashboard/dashboard.html', data=data)
from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint('dashboard', __name__)

@bp.before_request

@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

@bp.route('/')
@bp.route('/dashboard')
def index():
    return render_template('dashboard/dashboard.html')
from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint('reports', __name__)

@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

@bp.route('/')
def index():
    return render_template('reports/reports.html')
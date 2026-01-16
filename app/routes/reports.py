from flask import Blueprint, render_template

bp = Blueprint('reports', __name__)

@bp.route('/')
def index():
    return render_template('reports/reports.html')
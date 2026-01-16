from flask import Blueprint, render_template

bp = Blueprint('settings', __name__)

@bp.route('/')
def index():
    return render_template('settings/settings.html')
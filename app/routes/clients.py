from flask import Blueprint, render_template

bp = Blueprint('clients', __name__)

@bp.route('/')
def index():
    return render_template('clients/clients.html')
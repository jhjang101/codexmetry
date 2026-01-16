from flask import Blueprint, render_template

bp = Blueprint('invoices', __name__)

@bp.route('/')
def index():
    return render_template('invoices/invoices.html')
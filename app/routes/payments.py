from flask import Blueprint, render_template

bp = Blueprint('payments', __name__)

@bp.route('/')
def index():
    return render_template('payments/payments.html')
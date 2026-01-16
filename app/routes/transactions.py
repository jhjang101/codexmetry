from flask import Blueprint, render_template

bp = Blueprint('transactions', __name__)

@bp.route('/')
def index():
    return render_template('transactions/transactions.html')
from flask import Blueprint, render_template

bp = Blueprint('purchase_orders', __name__)

@bp.route('/')
def index():
    return render_template('purchase_orders/purchase_orders.html')
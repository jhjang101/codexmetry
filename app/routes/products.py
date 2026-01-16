from flask import Blueprint, render_template

bp = Blueprint('products', __name__)

@bp.route('/')
def index():
    return render_template('products/products.html')
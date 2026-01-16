from flask import Blueprint, render_template

bp = Blueprint('vendors', __name__)

@bp.route('/')
def index():
    return render_template('vendors/vendors.html')
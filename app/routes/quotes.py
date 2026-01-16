from flask import Blueprint, render_template

bp = Blueprint('quotes', __name__)

@bp.route('/')
def index():
    return render_template('quotes/quotes.html')
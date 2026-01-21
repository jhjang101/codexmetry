from flask import Blueprint, render_template, request, redirect, url_for
from ..services.quotes_service import QuoteService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..utils.money import parse_to_cents, format_usd
from ..utils.docs import generate_doc_number 
from ..models import Quote
from datetime import datetime

bp = Blueprint('quotes', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = QuoteService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('quotes/partials/list.html', pagination=pagination)
    
    return render_template('quotes/quotes.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Save Quote Header
        client_id = request.form.get('client_id')
        quote_number = request.form.get('quote_number', '').strip()
        if not quote_number:
            quote_number = generate_doc_number(prefix='Q', model=Quote, column_name='quote_number')
        quote_date = request.form.get('quote_date')
        expiration_date = request.form.get('expiration_date')
        note = request.form.get('note')

        quote_data = {
            'client_id': int(client_id) if client_id else None,
            'quote_number': quote_number,
            'quote_date': datetime.strptime(quote_date, '%Y-%m-%d').date() if quote_date else None,
            'expiration_date': datetime.strptime(expiration_date, '%Y-%m-%d').date() if expiration_date else None,
            'note': note
        }
        new_quote = QuoteService.add(**quote_data)

        # 2. Process and Save Line Items
        items = _parse_items_form(request.form)
        QuoteService.update_items(new_quote.id, items)

        return redirect(url_for('quotes.index'))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all()
    suggested_number = generate_doc_number(prefix='Q', model=Quote, column_name='quote_number')
    return render_template('quotes/form.html', 
                           mode='add', 
                           quote=None, 
                           clients=clients, 
                           products=products,
                           suggested_number=suggested_number
    )

@bp.route('/view/<int:id>')
def view(id):
    quote = QuoteService.get_by_id(id)

    print(quote.total_amount)

    return render_template('quotes/form.html', mode='view', quote=quote)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    quote = QuoteService.get_by_id(id)
    if request.method == 'POST':
        # 1. Update Header
        client_id = request.form.get('client_id')
        quote_number = request.form.get('quote_number', '').strip()
        if not quote_number:
            quote_number = generate_doc_number(prefix='Q', model=Quote, column_name='quote_number')
        quote_date = request.form.get('quote_date')
        expiration_date = request.form.get('expiration_date')
        note = request.form.get('note')
        status = request.form.get('status')

        quote_data = {
            'client_id': int(client_id) if client_id else None,
            'quote_number': quote_number, 
            'quote_date': datetime.strptime(quote_date, '%Y-%m-%d').date() if quote_date else None,
            'expiration_date': datetime.strptime(expiration_date, '%Y-%m-%d').date() if expiration_date else None,
            'note': note,
            'status': status
        }
        QuoteService.update(id, **quote_data)

        # 2. Update Line Items
        items = _parse_items_form(request.form)
        QuoteService.update_items(id, items)

        return redirect(url_for('quotes.view', id=id))

    clients = ClientService.get_all()
    products = ProductService.get_all()
    return render_template('quotes/form.html', mode='edit', quote=quote, clients=clients, products=products)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    QuoteService.archive(id)
    return redirect(url_for('quotes.index'))

# --- HTMX PARTIALS & LIVE MATH ---

@bp.route('/item-row')
def item_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all()
    return render_template('quotes/partials/item_row.html', item=None, products=products)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """The 'No-JS' Calculation Engine: Re-sums totals and returns a partial snippet."""
    quantities = request.form.getlist('qty[]')
    prices = request.form.getlist('unit_price[]')
    
    grand_total = 0
    line_totals = []

    for q, p in zip(quantities, prices):
        qty = int(q) if q and q.isdigit() else 0
        price = parse_to_cents(p)
        line = qty * price
        line_totals.append(format_usd(line))
        grand_total += line

    # We return a JSON-like update or a specific partial that updates the total areas
    return render_template('quotes/partials/calculation_summary.html', 
                           line_totals=line_totals, 
                           grand_total=format_usd(grand_total))

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists from form into a list of dictionaries."""
    product_ids = form_data.getlist('product_id[]')
    quantities = form_data.getlist('qty[]')
    unit_prices = form_data.getlist('unit_price[]')
    
    items = []
    for pid, q, p in zip(product_ids, quantities, unit_prices):
        if pid:
            items.append({
                'product_id': int(pid),
                'quantity': int(q) if q else 1,
                'unit_price': parse_to_cents(p)
            })
    return items
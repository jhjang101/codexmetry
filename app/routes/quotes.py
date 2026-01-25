from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.quotes_service import QuoteService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents, format_usd
from ..utils.docs import generate_doc_number 
from ..models import Quote
from datetime import datetime
import time 

bp = Blueprint('quotes', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['quotes_last_url'] = request.full_path

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

        # 3. COMMIT ATTACHMENTS
        new_files = request.files.getlist('attachments')
        print('new_files:', new_files)
        # We call commit with an empty delete list because it's a new quote
        AttachmentService.commit('Quote', new_quote.id, new_files=new_files)

        flash(f'Quote {new_quote.quote_number} added successfully!', 'success')
        return redirect(url_for('quotes.index'))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all()
    suggested_number = generate_doc_number(prefix='Q', model=Quote, column_name='quote_number')
    initial_row_id = str(int(time.time() * 1000))   
    return render_template('quotes/form.html', 
                           mode='add', 
                           quote=None, 
                           clients=clients, 
                           products=products,
                           suggested_number=suggested_number,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    quote = QuoteService.get_by_id(id)
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

        # 3. COMMIT ATTACHMENTS
        new_files = request.files.getlist('attachments')
        raw_delete_ids = request.form.getlist('delete_ids[]') 
        delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
        AttachmentService.commit('Quote', id, new_files=new_files, delete_ids=delete_ids)

        flash(f'Quote {quote.quote_number} updated successfully!', 'success')
        return redirect(url_for('quotes.view', id=id))

    clients = ClientService.get_all()
    products = ProductService.get_all()
    return render_template('quotes/form.html', mode='edit', quote=quote, clients=clients, products=products)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    quote = QuoteService.archive(id)
    if quote:
        flash(f'Quote {quote.quote_number} has been moved to archives.', 'warning')
    else:
        flash('Quote not found.', 'error')
    return redirect(url_for('quotes.index'))

# --- HTMX PARTIALS & LIVE MATH ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all()
    # Generate a unique row_id based on a timestamp
    row_id = str(int(time.time() * 1000))
    return render_template(
            'quotes/partials/item_row.html', products=products, row_id=row_id, item=None, mode='add')

@bp.route('/get-unit-price')
def get_unit_price():
    """Returns the default_unit_price for the selected product."""
    raw_pid = request.args.get('product_ids[]')
    row_id = request.args.get('row_id')
    
    product_id = int(raw_pid) if raw_pid and raw_pid.strip() else None
    
    # Query product for its default price
    product = ProductService.get_by_id(product_id) if product_id else None 
    default_unit_price = product.default_unit_price if product else 0
    
    return render_template('quotes/partials/unit_price_input.html', 
                           row_id=row_id, 
                           price=default_unit_price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates the specific Line Total and the global Grand Total."""
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    line_total = 0
    grand_total = 0

    # If this is the row the user is currently editing, capture its total
    if row_id in row_ids:
        idx = row_ids.index(row_id)
        line_total = int(quantities[idx]) * parse_to_cents(unit_prices[idx])

    # calculate grand total
    items = [{'qty': q, 'price': p} for q, p in zip(quantities, unit_prices)]
    for item in items:
        qty = int(item['qty'])
        price = parse_to_cents(item['price'])
        grand_total += qty * price

    return render_template('quotes/partials/calculation_result.html', 
                           row_id=row_id,
                           line_total=line_total, 
                           grand_total=grand_total)

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists from form into a list of dictionaries."""
    product_ids = form_data.getlist('product_ids[]')
    quantities = form_data.getlist('quantities[]')
    unit_prices = form_data.getlist('unit_prices[]')
    
    items = []
    for pid, q, p in zip(product_ids, quantities, unit_prices):
        if pid:
            items.append({
                'product_id': int(pid),
                'quantity': int(q) if q else 1,
                'unit_price': parse_to_cents(p)
            })
    return items
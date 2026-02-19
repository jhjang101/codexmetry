from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.quotes_service import QuoteService
from ..services.clients_service import ClientService
from ..services.products_service import ProductService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..utils.docs import generate_doc_number
from ..models import Quote
from ..extensions import db
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
        try:
            # 1. Prepare Header Data
            header_data = {
                'client_id': request.form.get('client_id'),
                'quote_number': request.form.get('quote_number'),
                'quote_date': request.form.get('quote_date'),
                'expiration_date': request.form.get('expiration_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Call Service
            new_quote = QuoteService.add_quote(header_data, items)

            # 4. Save Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Quote', new_quote.id, new_files=new_files)
            
            flash(f"Quote {new_quote.quote_number} added successfully!", "success")
            return redirect(url_for('quotes.index'))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('quotes.add'))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
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
    try:
        quote = QuoteService.get_quote_by_id(id)
        if not quote:
            flash("Quote not found.", "error")
            return redirect(url_for('quotes.index'))
    except Exception as e:
        flash(f"Error loading quote: {str(e)}", "error")
        return redirect(url_for('quotes.index'))

    return render_template('quotes/form.html', mode='view', quote=quote)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    quote = QuoteService.get_quote_by_id(id)
    if not quote:
        flash("Quote not found.", "error")
        return redirect(url_for('quotes.index'))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data
            header_data = {
                'client_id': request.form.get('client_id'),
                'quote_number': request.form.get('quote_number'),
                'quote_date': request.form.get('quote_date'),
                'expiration_date': request.form.get('expiration_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Call Service
            QuoteService.edit_quote(id, header_data, items)

            # 4. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Quote', id, new_files=new_files, delete_ids=delete_ids)

            flash(f"Quote {quote.quote_number} updated successfully!", "success")
            return redirect(url_for('quotes.view', id=id))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('quotes.edit', id=id))
        
    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
    return render_template('quotes/form.html', 
                           mode='edit', 
                           quote=quote, 
                           clients=clients, 
                           products=products)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    """Soft delete the quote."""
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
    products = ProductService.get_all_products()
    # Generate a unique row_id based on a timestamp
    row_id = str(int(time.time() * 1000))
    return render_template('quotes/partials/item_row.html', 
                           products=products, 
                           row_id=row_id, 
                           item=None, 
                           mode='add')

@bp.route('/get-unit-price')
def get_unit_price():
    """Returns the default_unit_price for the selected product."""
    product_id = request.args.get('product_ids[]', type=int)
    row_id = request.args.get('row_id')

    product = ProductService.get_by_id(product_id)
    price = product.default_unit_price if product else 0

    return render_template('quotes/partials/unit_price_input.html', row_id=row_id, price=price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates the specific Line Total and the Grand Total."""
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    line_total = 0
    grand_total = 0

    # calculate grand total
    for r_id, qty, price in zip(row_ids, quantities, unit_prices):
        q = int(qty) if qty else 0
        p = parse_to_cents(price)
        total = q * p
        grand_total += total

        # If this is the row the user is currently editing, capture its total
        if r_id == row_id:
            line_total = total

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
    descriptions = form_data.getlist('descriptions[]')
    
    items = []
    for product_id, qty, price, description in zip(product_ids, quantities, unit_prices, descriptions):
        if product_id:
            items.append({
                'product_id': product_id,
                'quantity': int(qty) if qty else 1,
                'unit_price': price, # Service handles parse_to_cents
                'description': description.strip() if description else ''
            })
    return items
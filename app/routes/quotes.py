from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.orders_service import OrderService
from ..services.quotes_service import QuoteService
from ..services.clients_service import ClientService
from ..services.products_service import ProductService
from ..services.attachment_service import AttachmentService
from ..services.audit_service import AuditLogService
from ..services.settings_service import SettingsMetadata
from ..utils.money import parse_to_cents
from ..utils.docs import generate_doc_number
from ..utils.auth import role_required
from ..models import Quote
from ..extensions import db
from datetime import datetime, timedelta
import time
import zoneinfo

bp = Blueprint('quotes', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['quotes_last_url'] = request.full_path

    # 1. Extract Sorting Parameters
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = QuoteService.get_all_with_search(
        search_term=search_term, 
        page=page, 
        per_page=10,
        sort_by=sort_by,
        direction=direction
    )
    
    if request.headers.get('HX-Request'):
        return render_template('quotes/partials/list.html', pagination=pagination)
    
    return render_template('quotes/quotes.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
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

            # 3. Parse Attachments
            new_files = request.files.getlist('attachments')

            # 4. Call Service
            new_quote = QuoteService.add_quote(header_data, items, new_files=new_files)
            
            # 5. Success Flow
            flash(f"Quote {new_quote.quote_number} added successfully!", "success")
            
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('quotes.view', id=new_quote.id)
            return response

        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
    # GET: Prepare form data from Client
    referrer = request.referrer
    # Only use referrer if it's not the 'add' page itself
    cancel_url = url_for('quotes.index')
    if referrer and url_for('quotes.add') not in referrer:
        cancel_url = referrer

    client_id = request.args.get('client_id', type=int)

    if client_id: # generate PO from client
        client = ClientService.get_by_id(client_id)
        if not client:
            flash("Client not found", "error")
            return redirect(url_for('purchase_orders.index'))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
    suggested_number = generate_doc_number(prefix='QTE', model=Quote, column_name='quote_number')
    initial_row_id = str(int(time.time() * 1000))
    metadata = db.session.get(SettingsMetadata, 1)
    tz_name = metadata.timezone if metadata else 'America/Chicago'
    today = datetime.now(zoneinfo.ZoneInfo(tz_name)).date()
    expiry_days = metadata.default_quote_expiry_days if metadata else 30
    suggested_expiry = today + timedelta(days=expiry_days)

    return render_template('quotes/form.html', 
                           mode='add', 
                           quote=None, 
                           clients=clients, 
                           products=products,
                           suggested_number=suggested_number,
                           client_id=client_id,
                           today=today.strftime('%Y-%m-%d'),
                           expiration_date=suggested_expiry.strftime('%Y-%m-%d'),
                           timestamp=initial_row_id,
                           cancel_url=cancel_url)

@bp.route('/view/<int:id>')
def view(id):
    try:
        quote = QuoteService.get_quote_by_id(id)
        if not quote:
            flash("Quote not found.", "error")
            return redirect(url_for('quotes.index'))
        
        tree = OrderService.get_deal_tree(quote.order_id)
        history = AuditLogService.get_for_entity('Quote', id)

        return render_template('quotes/form.html', mode='view', quote=quote, tree=tree, history=history)

    except Exception as e:
        flash(f"Error loading quote: {str(e)}", "error")
        return redirect(url_for('quotes.index'))


@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
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

            # 3. Parse Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]

            # 4. Call Service
            QuoteService.edit_quote(id, header_data, items, new_files=new_files, delete_ids=delete_ids)

            flash(f"Quote {quote.quote_number} updated successfully!", "success")
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('quotes.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
    return render_template('quotes/form.html', 
                           mode='edit', 
                           quote=quote, 
                           clients=clients, 
                           products=products)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    """Soft delete the quote."""
    quote = QuoteService.archive(id)
    if quote:
        flash(f'Quote {quote.quote_number} has been moved to archives.', 'warning')
    else:
        flash('Quote not found.', 'error')
    return redirect(url_for('quotes.index'))

# --- PRINT ---

@bp.route('/print/<int:id>')
@login_required
def print_view(id):
    """
    Messenger: Fetches hydrated Quote data for the printable layout.
    Metadata is already injected via global context processor.
    """
    # 1. Promote status if it is currently a draft
    quote, status = QuoteService.issue_quote(id)
    if not quote:
        flash("Quote not found.", "error")
        return redirect(url_for('quotes.index'))

    # 2. Feedback: Notify the user of the deal's progression
    if status and status['before'] != status['after']:
        flash(f"Quote issued. Status updated: {status['before'].upper()} → {status['after'].upper()}", "success")

    # 3. Initialize buckets
    line_display_items = []
    subtotal = 0
    tax_total = 0
    shipping_total = 0

    # 4. Sort items into buckets based on document_placement
    for item in quote.items:
        # Standardize value calculation in the "Brain"
        item_value = item.quantity * item.quoted_unit_price
        placement = item.product.document_placement

        if placement == 'Tax':
            tax_total += item_value
        elif placement == 'Shipping':
            shipping_total += item_value
        else:
            # if it's not 'Tax' or 'Shipping', it's a Lineitem
            line_display_items.append(item)
            subtotal += item_value

    # 5. Pass pre-calculated values to the template
    return render_template('quotes/print.html', 
                           quote=quote,
                           line_display_items=line_display_items,
                           subtotal=subtotal,
                           tax_total=tax_total,
                           shipping_total=shipping_total)

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
    try:
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

        # Success: Return the calculation fragment
        return render_template('quotes/partials/calculation_result.html', 
                            row_id=row_id,
                            line_total=line_total, 
                            grand_total=grand_total)
    
    except ValueError as e:
        # Failure: Rollback (Safety first) and OOB Error
        db.session.rollback()
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        # Tell HTMX not to clear the total or the input that caused the error
        resp.headers['HX-Reswap'] = 'none'
        return resp
    
# --- HTMX Quote Date Cascade Routes ---
@bp.route('/calculate-expiry')
@login_required
def calculate_expiry():
    quote_date_raw = request.args.get('quote_date')
    
    # 1. Fetch the business rule from Metadata
    metadata = db.session.get(SettingsMetadata, 1)
    expiry_days = metadata.default_quote_expiry_days if metadata else 30
    
    # 2. Perform the math
    try:
        if quote_date_raw:
            quote_date = datetime.strptime(quote_date_raw, '%Y-%m-%d').date()
            expiration_date = quote_date + timedelta(days=expiry_days)
        expiry_str = expiration_date.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        expiry_str = "" # Fallback if date is invalid

    # 3. Return the partial input
    return render_template('quotes/partials/expiration_input.html', expiration_date=expiry_str)

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
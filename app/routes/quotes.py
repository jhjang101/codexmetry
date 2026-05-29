from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response, g
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
from ..utils.errors import handle_post_error
from ..models import Quote
from ..extensions import db
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo

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
    
    # if searches, HTMX only replace list template.
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
                'note': request.form.get('note'),
                'quote_address': request.form.get('quote_address')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Parse Attachments
            new_files = request.files.getlist('attachments')

            # 4. Call Service
            new_quote = QuoteService.add_quote(header_data, items, new_files=new_files)
            
            # 5. Success Flow
            flash(f"Quote {new_quote.quote_number} created successfully!", "success")
            
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('quotes.view', id=new_quote.id)
            return response

        except Exception as e:
            return handle_post_error(e, "quotes.add")
        
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
    suggested_number = generate_doc_number(prefix='Q', model=Quote, column_name='quote_number')
    initial_row_id = str(int(time.time() * 1000))
    metadata = g.metadata
    today = datetime.now(ZoneInfo(g.office_tz)).date()
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
    quote = QuoteService.get_quote_by_id(id)
    if not quote:
        flash("Quote not found.", "error")
        return redirect(url_for('quotes.index'))
    
    tree = OrderService.get_deal_tree(quote.order_id)
    history = AuditLogService.get_for_entity('Quote', id)

    return render_template('quotes/form.html', mode='view', quote=quote, tree=tree, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    quote = QuoteService.get_quote_by_id(id)
    if not quote:
        flash("Quote not found.", "error")
        return redirect(url_for('quotes.index'))\
    
    # --- PO Link Lock ---
    if quote.order_id:
        flash("Access Denied: This Quote is locked because it is linked to a Purchase Order. Please unlink PO and try again.", "warning")
        return redirect(url_for('quotes.view', id=id))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data
            header_data = {
                'client_id': request.form.get('client_id'),
                'quote_number': request.form.get('quote_number'),
                'quote_date': request.form.get('quote_date'),
                'expiration_date': request.form.get('expiration_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note'),
                'quote_address': request.form.get('quote_address')
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
        
        except Exception as e:
            return handle_post_error(e, "quotes.edit")
        
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
    try:
        quote = QuoteService.archive(id)
        if not quote:
            raise ValueError("Quote not found.")

        flash(f'Quote {quote.quote_number} archived.', 'success')
        return redirect(url_for('quotes.index'))

    except Exception as e:
        return handle_post_error(e, "quotes.archive")

# --- PRINT ---

@bp.route('/print/<int:id>')
def print_view(id):
    """
    Messenger: Fetches hydrated Quote data for the printable layout.
    Metadata is already injected via global context processor.
    """
    # 1. Fetch hydrated object (Passively)
    quote = QuoteService.get_quote_by_id(id)
    if not quote:
            flash("Quote not found.", "error")
            return redirect(url_for('quotes.index'))
    
    # 2. Initialize buckets
    line_display_items = []
    subtotal = 0
    tax_total = 0
    shipping_total = 0

    # 3. Sort items into buckets based on document_placement
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
    
    # 4. Render the preview template with pre-calculated values
    return render_template('quotes/print.html', 
                           quote=quote,
                           line_display_items=line_display_items,
                           subtotal=subtotal,
                           tax_total=tax_total,
                           shipping_total=shipping_total)

@bp.route('/issue/<int:id>', methods=['POST'])
def issue(id):
    """
    Messenger: Commits the document to the legal record.
    Action: Flips status, persists terms, and archives the PDF.
    """
    try:
        # 1. Capture user-typed terms from the Preview form
        transient_terms = request.form.get('transient_terms', '')

        # 2. Call the Atomic Brain Logic
        # (This will handle status, snapshot, PDF generation, and Audit)
        quote, status, filename = QuoteService.issue_quote(id, transient_terms)
        
        if not quote:
            flash("Quote record not found.", "error")
            return redirect(url_for('quotes.index'))

        # 3. Success Feedback
        flash(f"Quote {quote.quote_number} has been issued and attached as PDF: {filename}", "success")
        if status and status['before'] != status['after']:
            flash(f"Status updated: {status['before'].upper()} → {status['after'].upper()}", "info")

        # 4. Final Redirect to the View page
        return redirect(url_for('quotes.view', id=id, issued=filename))

    except Exception as e:
        # Rollback and show OOB error if the PDF generation or commit fails
        return handle_post_error(e, "quotes.issue")

# --- HTMX PARTIALS & LIVE MATH ---
@bp.route('/get-client-address')
def get_client_address():
    """Returns the primary_address for the selected client to prefill the snapshot."""
    client_id = request.args.get('client_id', type=int)
    if not client_id:
        return render_template('quotes/partials/address_input.html', address="")
    
    client = ClientService.get_by_id(client_id)
    address = client.primary_address if client else ""
    return render_template('quotes/partials/address_input.html', address=address)

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
    raw_pid = request.args.get('product_ids[]')
    row_id = request.args.get('row_id')

    product_id = int(raw_pid) if raw_pid and raw_pid.strip() else None

    # IF ID IS EMPTY: Return a blank price input instead of crashing
    if not product_id:
        return render_template('quotes/partials/unit_price_input.html',
                               row_id=row_id, price=0)

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
    
    except Exception as e:
        # Rollback, Log, and return OOB Error.
        # HX-Reswap: none ensures the Total cell doesn't get overwritten with error text.
        return handle_post_error(e, "quotes.calculate")
    
# --- HTMX Quote Date Cascade Routes ---
@bp.route('/calculate-expiry')
@login_required
def calculate_expiry():
    quote_date_raw = request.args.get('quote_date')
    
    # 1. Fetch the business rule from Metadata
    metadata = g.metadata
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
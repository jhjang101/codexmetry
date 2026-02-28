from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.orders_service import OrderService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.quotes_service import QuoteService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..services.settings_service import PoTypeService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..utils.auth import role_required
from ..extensions import db
from datetime import datetime
import time 

bp = Blueprint('purchase_orders', __name__)

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
    session['purchase_orders_last_url'] = request.full_path

    # 1. Extract Sorting Parameters
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = PurchaseOrderService.get_all_with_search(
        search_term=search_term, 
        page=page, 
        per_page=10, 
        sort_by=sort_by, 
        direction=direction
        )
    
    if request.headers.get('HX-Request'):
        return render_template('purchase_orders/partials/list.html', pagination=pagination)
    
    return render_template('purchase_orders/purchase_orders.html', pagination=pagination, search=search_term)

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
                'bill_to_id': request.form.get('bill_to_id'),
                'po_number': request.form.get('po_number'), # Client reference
                'po_date': request.form.get('po_date'),
                'quote_id': request.form.get('quote_id'),
                'po_type_id': request.form.get('po_type_id'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Call Atomic Service (Handles Registry birth and Quote linking)
            new_po = PurchaseOrderService.add_po(header_data, items)

            # 4. Handle Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('PurchaseOrder', new_po.id, new_files=new_files)

            # 5. Success Flow
            flash(f'PO {new_po.order.order_number} created successfully!', 'success')

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('purchase_orders.view', id=new_po.id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp


    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
    po_types = PoTypeService.get_all()
    initial_row_id = str(int(time.time() * 1000))   
    return render_template('purchase_orders/form.html', 
                           mode='add', 
                           po=None, 
                           clients=clients, 
                           products=products,
                           po_types=po_types,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    # Use augmented fetcher to get calculated financial attributes
    try:
        po = PurchaseOrderService.get_po_by_id(id)
        if not po:
            flash("Purchase Order not found.", "error")
            return redirect(url_for('purchase_orders.index'))

        print('po.total_amount:', po.total_amount)
        print('po.balance:', po.balance)
        print('po.po_total_deposit:', po.total_prepayment)
        print('po.remaining_deposit:', po.remaining_credit)

        tree = OrderService.get_deal_tree(po.order_id)

        return render_template('purchase_orders/form.html', mode='view', po=po, tree=tree)

    except Exception as e:
        db.session.rollback()
        flash(f"Error loading purchase order: {str(e)}", "error")
        return redirect(url_for('purchase_orders.index'))


@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    po = PurchaseOrderService.get_po_by_id(id)
    if not po:
        flash("Purchase Order not found.", "error")
        return redirect(url_for('purchase_orders.index'))

    if request.method == 'POST':
        # 1. Extract and Transform
        try:
            # 1. Prepare Data
            header_data = {
                'client_id': request.form.get('client_id'),
                'bill_to_id': request.form.get('bill_to_id'),
                'po_number': request.form.get('po_number'),
                'po_date': request.form.get('po_date'),
                'quote_id': request.form.get('quote_id'),
                'po_type_id': request.form.get('po_type_id'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }

            # 2. Parse Line Items
            items = _parse_items_form(request.form)

            # 3. Call Service (Handles Quote Release/Re-link)
            PurchaseOrderService.edit_po(id, header_data, items)

            # 4. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]')
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('PurchaseOrder', id, new_files=new_files, delete_ids=delete_ids)

            flash(f'PO {po.order.order_number} updated successfully!', 'success')
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('purchase_orders.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all_products()
    po_types = PoTypeService.get_all()
    quotes = QuoteService.get_quotes_by_client(po.client_id, include_id=po.quote_id)

    return render_template('purchase_orders/form.html', 
                           mode='edit', 
                           po=po, 
                           clients=clients, 
                           payers=clients,
                           products=products,
                           po_types=po_types,
                           quotes=quotes)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    """Specialized archive for PO with dependency ripples."""
    po, has_payments = PurchaseOrderService.archive_po(id)

    if po:
        # Use the CDX fallback for the flash message
        po_name = po.po_number or po.order.order_number
        flash(f'PO {po_name}, its Order Ref, and all linked Invoices have been archived.', 'warning')

        # Free the Quote? Notify the user.
        if po.quote_id:
            flash(f'Quote {po.quote.quote_number} has been reverted to "Sent" status.', 'success')

        # MONEY SAFETY WARNING
        if has_payments:
            flash(f'ATTENTION: Active payments exist for this PO. The pyayment records were NOT archived. Please manage them manually.', 'error')

    else:
        flash('PO not found.', 'error')
    return redirect(url_for('purchase_orders.index'))

# --- HTMX Item-row and Calculation Routes ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all_products()
    # Generate a unique row_id based on a timestamp
    row_id = str(int(time.time() * 1000))
    return render_template('purchase_orders/partials/item_row.html',
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

    # Query product for its default price
    product = ProductService.get_by_id(product_id)
    price = product.default_unit_price if product else 0

    return render_template('purchase_orders/partials/unit_price_input.html',
                           row_id=row_id,
                           price=price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates the specific Line Total and the global Grand Total."""
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

        return render_template('purchase_orders/partials/calculation_result.html', 
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

# --- HTMX Client Cascade Routes ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """Unified route to Updates Bill-To and Quotes when Client changes via OOB."""
    # Extract IDs from the HTMX request
    po_id = request.args.get('po_id', type=int)
    client_id = request.args.get('client_id', type=int)

    quote_id = None # add
    if po_id: # edit
        po = PurchaseOrderService.get_by_id(po_id)
        quote_id = po.quote_id if po else None

    # Fetch Quotes for the selected client
    quotes = QuoteService.get_quotes_by_client(
        client_id, 
        include_id=quote_id # includes current quote in edit
        ) if client_id else []
    
    # Populate payers for Bill_To dropdown
    payers = ClientService.get_all()
    
    # Prefill Bill_To from selected client
    payer_prefill_id = client_id if client_id else None

    # 3. Return a single partial containing both components
    return render_template('purchase_orders/partials/client_cascades.html', 
                           po_id=po_id, # Add if none else Edit
                           client_id=client_id,   # need for enable/disable dropdown
                           quotes=quotes,
                           payers=payers,
                           payer_prefill_id=payer_prefill_id)

# --- HTMX Quote-Itmes Cascade Routes ---

@bp.route('/load-quote-items')
def load_quote_items():
    """Returns multiple item_row partials based on a selected Quote."""
    quote_id = request.args.get('quote_id', type=int)
    quote = QuoteService.get_quote_by_id(quote_id) if quote_id else None
    if not quote:
        return "" # If 'No Quote' selected, do nothing or return a blank row

    products = ProductService.get_all()
    html_rows = ""
    
    # We iterate through Quote items and render them as PO rows
    for idx, q_item in enumerate(quote.items):
        # Generate a unique row_id for each row (timestamp + index)
        row_id = f"{int(time.time() * 1000)}{idx}"
        
        # Format data to match what item_row.html expects
        item_data = {
            'product_id': q_item.product_id,
            'product': q_item.product,
            'quantity': q_item.quantity,
            'agreed_unit_price': q_item.quoted_unit_price,
            'description': q_item.description
        }
        
        html_rows += render_template('purchase_orders/partials/item_row.html',
                                   item=item_data, 
                                   products=products, 
                                   row_id=row_id, 
                                   mode='add')

    # Trigger 'recalculate' on the body so the Grand Total updates immediately
    resp = make_response(html_rows)
    resp.headers['HX-Trigger-After-Swap'] = 'recalculate'
    return resp

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
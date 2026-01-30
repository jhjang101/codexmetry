from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..utils.money import parse_to_cents, format_usd
from ..extensions import db
from datetime import datetime
import time

bp = Blueprint('invoices', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['invoices_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = InvoiceService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('invoices/partials/list.html', pagination=pagination)
    
    return render_template('invoices/invoices.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        try:
            # Pass the whole request.form to the service for validation/transform
            new_invoice = InvoiceService.create_invoice(request.form)
            
            # Save items using the shared parser
            items = _parse_items_form(request.form)
            InvoiceService.update_items(new_invoice.id, items)
            
            flash(f"Invoice {new_invoice.invoice_number} created!", "success")
            return redirect(url_for('invoices.index'))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('invoices.add'))
        
    clients=ClientService.get_all()
    products=ProductService.get_all()
    initial_row_id = str(int(time.time() * 1000))
    return render_template('invoices/form.html', mode='add', invoice=None, 
                           clients=clients, 
                           products=products,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    invoice = InvoiceService.get_by_id(id)
    return render_template('invoices/form.html', mode='view', invoice=invoice)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit mode: handles header updates and item list synchronization."""
    invoice = InvoiceService.get_by_id(id)
    
    if request.method == 'POST':
        try:
            raw_date = request.form.get('invoice_date')
            
            invoice_data = {
                'invoice_number': request.form.get('invoice_number', '').strip(),
                'invoice_date': datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else None,
                'tracking_number': request.form.get('tracking_number'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }
            
            # Note: For data integrity, we usually don't change client_id or po_id 
            # after an invoice is created. If they picked the wrong PO, they should archive and recreate.
            InvoiceService.update(id, **invoice_data)

            # Update items using the shared parser
            items = _parse_items_form(request.form)
            InvoiceService.update_items(id, items)

            flash(f"Invoice {invoice.invoice_number} updated successfully!", "success")
            return redirect(url_for('invoices.view', id=id))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('invoices.edit', id=id))

    # GET hydration: Populate dropdowns for the edit form
    clients = ClientService.get_all()
    products = ProductService.get_all()
    # Fetch all POs for this specific client so the dropdown is populated on load
    pos = PurchaseOrderService.get_eligible_for_invoice(invoice.client_id) 
    
    return render_template('invoices/form.html', 
                           mode='edit', 
                           invoice=invoice, 
                           clients=clients, 
                           products=products, 
                           pos=pos)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    """Soft delete the invoice."""
    invoice = InvoiceService.archive(id)
    if invoice:
        flash(f'Invoice {invoice.invoice_number} moved to archives.', 'warning')
    return redirect(url_for('invoices.index'))

# --- HTMX Item-row and Calculation Routes ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all()
    # Generate a unique row_id based on a timestamp
    row_id = str(int(time.time() * 1000))
    return render_template('invoices/partials/item_row.html',
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
    default_unit_price = product.default_unit_price if product else 0

    return render_template('invoices/partials/unit_price_input.html',
                           row_id=row_id,
                           price=default_unit_price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates the specific Line Total and the global Grand Total."""
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    print(row_id)

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

    return render_template('invoices/partials/calculation_result.html', 
                           row_id=row_id,
                           line_total=line_total, 
                           grand_total=grand_total)

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """Triggered by Client change: updates Bill-To and PO dropdowns."""
    client_id = request.args.get('client_id', type=int)
    clients = ClientService.get_all()
    # Only show 'open' POs for this client
    pos = PurchaseOrderService.get_eligible_for_invoice(client_id) if client_id else []
    
    return render_template('invoices/partials/client_cascades.html', 
                           clients=clients, pos=pos, selected_id=client_id)

@bp.route('/load-po-details')
def load_po_details():
    """Triggered by PO selection: updates Order ID and pre-fills remaining items."""
    po_id = request.args.get('po_id', type=int)
    po = PurchaseOrderService.get_by_id(po_id)
    if not po: return ""

    # 1. Get remaining items from the Invoice Service (Partial Billing Logic)
    if po_id:
        remaining_items = InvoiceService.get_remaining_items(po_id)
    
    products = ProductService.get_all()
    html_rows = ""
    for idx, item in enumerate(remaining_items):
        row_id = f"{int(time.time() * 1000)}{idx}"
        html_rows += render_template('invoices/partials/item_row.html',
                                   item=item, products=products, row_id=row_id, mode='add')

    # 2. Prepare OOB response to update the Order ID and Bill-To
    resp = make_response(html_rows)
    resp.headers['HX-Trigger-After-Swap'] = 'recalculate' # Trigger grand total
    return resp

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
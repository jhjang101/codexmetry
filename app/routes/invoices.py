from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..utils.docs import generate_doc_number
from ..utils.sync import sync_invoice_status, sync_po_status
from ..models import Invoice
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
            # 1. Save Invoice Header
            invoice_data = {
                'client_id': request.form.get('client_id'),
                'invoice_number': request.form.get('invoice_number'),
                'po_id': request.form.get('po_id'),
                'bill_to_id': request.form.get('bill_to_id'),
                'invoice_date': request.form.get('invoice_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }
            new_invoice = InvoiceService.create_invoice(invoice_data)

            # 2. Save Invoice Line Items
            items = _parse_items_form(request.form)
            InvoiceService.update_items(new_invoice.id, items)

            # 2.1. Sync po status
            po_status_updated = False
            if new_invoice.po_id:
                po_status_updated = sync_po_status(new_invoice.po_id)

            # 3. Save Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Invoice', new_invoice.id, new_files=new_files)
            
            flash(f"Invoice {new_invoice.invoice_number} created!", "success")
            if new_invoice.po_id and po_status_updated:
                flash(f"Status of PO {new_invoice.purchase_order.po_number} updated successfully!", "success")

            return redirect(url_for('invoices.index'))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('invoices.add'))
        
    # GET: Prepare form data    
    clients=ClientService.get_all()
    products=ProductService.get_all_products()
    suggested_number = generate_doc_number(prefix='INV', model=Invoice, column_name='invoice_number')
    initial_row_id = str(int(time.time() * 1000))
    return render_template('invoices/form.html', 
                           mode='add', 
                           invoice=None, 
                           clients=clients, 
                           products=products,
                           suggested_number=suggested_number,
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
            # 1. Update Invoice Header
            invoice_data = {
                'client_id': request.form.get('client_id'),
                'invoice_number': request.form.get('invoice_number'),
                'po_id': request.form.get('po_id'),
                'status': request.form.get('status'),
                'bill_to_id': request.form.get('bill_to_id'),
                'invoice_date': request.form.get('invoice_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }
            old_po_id = invoice.po_id if invoice else None
            old_po_number = invoice.purchase_order.po_number or invoice.order.order_number
            InvoiceService.update_invoice(id, invoice_data)
            po_id = invoice.po_id if invoice else None
            po_number = invoice.purchase_order.po_number or invoice.order.order_number
            
            print(old_po_number)
            print(po_number)

            # 2. Update Invoice Line Items
            items = _parse_items_form(request.form)
            InvoiceService.update_items(id, items)

            # Sync invoice status
            sync_invoice_status(invoice.id)

            # 2.1. Sync po status
            po_status_updated = False
            old_po_status_updated = False

            if old_po_id != po_id:
                old_po_status_updated = sync_po_status(old_po_id)
            po_status_updated = sync_po_status(po_id)
            
            # 3. Update Attachments (Handle new and marked for delete)
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Invoice', id, new_files=new_files, delete_ids=delete_ids)

            flash(f"Invoice {invoice.invoice_number} updated successfully!", "success")
            if po_id and po_status_updated:
                flash(f"Status of PO {po_number} updated successfully!", "success")
            if old_po_id and old_po_status_updated:
                flash(f"Status of PO {old_po_number} updated successfully!", "success")


            return redirect(url_for('invoices.view', id=id))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('invoices.edit', id=id))

    # GET: Populate dropdowns for the edit form
    clients = ClientService.get_all()
    products = ProductService.get_all()
    # Fetch eligible POs for this specific client so the dropdown is populated on load
    pos = PurchaseOrderService.get_eligible_by_client(invoice.client_id) 
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

    # Sync po status
    po_status_updated = False
    if invoice.po_id:
        po_status_updated = sync_po_status(invoice.po_id)

    if invoice:
        flash(f'Invoice {invoice.invoice_number} moved to archives.', 'warning')
        if invoice.po_id and po_status_updated:
            flash(f'Status of PO {invoice.purchase_order.po_number} updated successfully!', 'success')
    else:
        flash(f'Invoice {invoice.invoice_number} not found.', 'error')
    return redirect(url_for('invoices.index'))

# --- HTMX Item-row and Calculation Routes ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all_products()
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
    """
    Dynamically calculates Line Total, Grand Total, Total Due and Remaining Deposit logic.
    Returns targeted swaps for the row and OOB swaps for the footer.
    """
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    line_total_cents = 0
    grand_total_cents = 0

    # 1. Iterate through all rows to calculate the Grand Total
    for r_id, qty, price_str in zip(row_ids, quantities, unit_prices):
        q = int(qty) if qty else 0
        # parse_to_cents handles the negative sign from the Applied Deposit row
        p = parse_to_cents(price_str)
        
        row_total = q * p
        grand_total_cents += row_total

        # 2. Capture the Line Total for the specific row being edited
        if r_id == row_id:
            line_total_cents = row_total

    # 3. Derive UI-only properties
    # Total Due is the amount the client must pay (never less than 0)
    total_due = max(0, grand_total_cents)
    # Remaining Credit is the excess deposit (absolute value of negative total)
    remaining_credit = abs(min(0, grand_total_cents))

    return render_template(
        'invoices/partials/calculation_result.html',
        row_id=row_id,
        line_total=line_total_cents,
        grand_total=grand_total_cents,
        total_due=total_due,
        remaining_credit=remaining_credit
    )

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """Triggered by Client change: updates Bill-To and PO dropdowns."""
    client_id = request.args.get('client_id', type=int)
    # Prefill Bill_to with this client
    clients = ClientService.get_all()
    # Populate eligible POs for this client
    pos = PurchaseOrderService.get_eligible_by_client(client_id) if client_id else []
    
    return render_template('invoices/partials/client_cascades.html', 
                           clients=clients, pos=pos, selected_id=client_id)

@bp.route('/load-po-details')
def load_po_details():
    """Triggered by PO selection: updates Bill-To and pre-fills remaining items."""
    po_id = request.args.get('po_id', type=int)
    po = PurchaseOrderService.get_po_by_id(po_id) if po_id else None
    if not po: 
        return ""

    # 1. Get remaining items from the Invoice Service (Partial Billing Logic)
    if po and po.remaining_items: # type: ignore
        remaining_items = po.remaining_items # type: ignore
    else:
        remaining_items = []

    # Changed agreed_unit_price to billed_unit_price in the remaining_items key
    for idx, item in enumerate(remaining_items):
        item['billed_unit_price'] = item.pop('agreed_unit_price')
        item['row_id'] = f"{int(time.time() * 1000)}{idx}"


    # 2. Populate clients and products list for bill_to and item_row
    clients = ClientService.get_all()
    products = ProductService.get_all()
    
    # 3. Return the single unified OOB template
    resp = make_response(render_template(
        'invoices/partials/po_selection_oob.html',
        po=po,
        items=remaining_items,
        clients=clients,
        products=products
    ))

    # 4. Trigger math recalculation
    resp.headers['HX-Trigger-After-Swap'] = 'recalculate' # Trigger grand total
    return resp

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists from form into a list of dictionaries."""
    product_ids = form_data.getlist('product_ids[]')
    quantities = form_data.getlist('quantities[]')
    unit_prices = form_data.getlist('unit_prices[]')
    
    items = []
    for product_id, qty, price in zip(product_ids, quantities, unit_prices):
        if product_id:
            items.append({
                'product_id': product_id,
                'quantity': qty,
                'unit_price': price
            })
    return items
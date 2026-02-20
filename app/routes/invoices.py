from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
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

@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main directory for Invoices module."""
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
            header_data = {
                'client_id': request.form.get('client_id'),
                'invoice_number': request.form.get('invoice_number'),
                'po_id': request.form.get('po_id'),
                'bill_to_id': request.form.get('bill_to_id'),
                'invoice_date': request.form.get('invoice_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Save Invoice and Line Items
            new_invoice = InvoiceService.add_invoice(header_data, items)

            # 4. Sync po status
            po_status_updated = sync_po_status(new_invoice.po_id)

            # 5. Save Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Invoice', new_invoice.id, new_files=new_files)
            
            flash(f"Invoice {new_invoice.invoice_number} created!", "success")
            if po_status_updated:
                po_name = new_invoice.purchase_order.po_number or new_invoice.order.order_number
                flash(f"Status of PO {po_name} updated successfully!", "success")

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
    invoice = InvoiceService.get_invoice_by_id(id)
    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('invoices.index'))


    print('invoice.total_amount:', invoice.total_amount)
    print('invoice.total_due:', invoice.total_due)
    print('invoice.remaining_credit:', invoice.remaining_credit)
    print('invoice.balance:', invoice.balance)
    print('invoice.po_total_deposit:', invoice.po_total_prepayment)


    return render_template('invoices/form.html', mode='view', invoice=invoice)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit mode: handles header updates and item list synchronization."""
    invoice = InvoiceService.get_invoice_by_id(id)
    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('invoices.index'))
    
    if request.method == 'POST':
        try:
            # 1. Capture State for Sync ripples
            old_po_id = invoice.po_id
            old_po_name = invoice.purchase_order.po_number or invoice.order.order_number

            # 2. Prepare Header Data
            header_data = {
                'client_id': request.form.get('client_id'),
                'invoice_number': request.form.get('invoice_number'),
                'po_id': request.form.get('po_id'),
                'status': request.form.get('status'),
                'bill_to_id': request.form.get('bill_to_id'),
                'invoice_date': request.form.get('invoice_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }

            # 3. Parse Items
            items = _parse_items_form(request.form)

            # 4. Update Invoice and Line Items
            InvoiceService.edit_invoice(id, header_data, items)

            # 5. Sync logic (Invoice and PO status ripples)
            sync_invoice_status(invoice.id)

            new_po_id = invoice.po_id
            po_status_updated = sync_po_status(new_po_id)
            old_po_status_updated = False
            if old_po_id != new_po_id:
                old_po_status_updated = sync_po_status(old_po_id)
            
            # 6. Update Attachments (Handle new and marked for delete)
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Invoice', id, new_files=new_files, delete_ids=delete_ids)

            # 7. Flash Messages
            flash(f"Invoice {invoice.invoice_number} updated successfully!", "success")
            if po_status_updated:
                new_po_name = invoice.purchase_order.po_number or invoice.order.order_number
                flash(f"Status of PO {new_po_name} updated successfully!", "success")
            if old_po_id and old_po_status_updated:
                flash(f"Status of PO {old_po_name} updated successfully!", "success")

            return redirect(url_for('invoices.view', id=id))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('invoices.edit', id=id))

    # GET: Populate dropdowns for the edit form
    clients = ClientService.get_all()
    products = ProductService.get_all()
    # Fetch eligible POs for this specific client so the dropdown is populated on load
    pos = PurchaseOrderService.get_pos_by_client(invoice.client_id, 
                                                 include_id=invoice.po_id)
    return render_template('invoices/form.html', 
                           mode='edit', 
                           invoice=invoice, 
                           clients=clients, 
                           products=products, 
                           pos=pos)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    """Specialized archive for invoices with payment protection."""
    # 1. Perform specialized archive
    invoice, has_payments = InvoiceService.archive_invoice(id)

    if not invoice:
        flash(f'Invoice not found.', 'error')
        return redirect(url_for('invoices.index'))

    # 2. Sync parent PO status (since an invoice just disappeared)
    po_status_updated = sync_po_status(invoice.po_id)

    # 3. Flash Messages
    flash(f'Invoice {invoice.invoice_number} moved to archives.', 'warning')

    # MONEY SAFETY WARNING: Tell the user exactly where the money went
    if has_payments:
        po_name = invoice.purchase_order.po_number or invoice.order.order_number
        flash(f'ATTENTION: This invoice had active payments. These funds are now sitting as a credit on PO {po_name}.', 'error')

    # PO SYNC FEEDBACK
    if po_status_updated:
        po_name = invoice.purchase_order.po_number or invoice.order.order_number
        flash(f'Status of PO {po_name} updated successfully!', 'success')
        
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
    price = product.default_unit_price if product else 0

    return render_template('invoices/partials/unit_price_input.html',
                           row_id=row_id,
                           price=price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """
    Dynamically calculates Line Total, Grand Total, Total Due and Remaining Credit logic.
    Returns targeted swaps for the row and OOB swaps for the footer.
    """
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    # Extract the hidden deposit pool value (it is stored in cents)
    try:
        po_total_prepayment = int(request.form.get('po_total_prepayment', 0))
    except (ValueError, TypeError):
        po_total_prepayment = 0

    # Initialize variables
    line_total = 0
    grand_total = 0

    # 1. Iterate through all rows to calculate the Grand Total
    for r_id, qty, price_str in zip(row_ids, quantities, unit_prices):
        q = int(qty) if qty else 0
        # parse_to_cents handles the negative sign from the Applied Deposit row
        p = parse_to_cents(price_str)
        
        total = q * p
        grand_total += total

        # 2. Capture the Line Total for the specific row being edited
        if r_id == row_id:
            line_total = total

    # 3. Derive UI-only properties
    # Total Due is the amount the client must pay (never less than 0)
    total_due = max(0, grand_total)
    # Remaining Deposit is the excess deposit (absolute value of negative total)
    remaining_credit = abs(min(0, grand_total))

    print('po_total_prepayment:', po_total_prepayment)
    print('total_due:', total_due)

    return render_template(
        'invoices/partials/calculation_result.html',
        row_id=row_id,
        line_total=line_total,
        grand_total=grand_total,
        total_due=total_due,
        remaining_credit=remaining_credit,
        po_total_prepayment=po_total_prepayment
    )

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """Triggered by Client change: updates Bill-To and PO dropdowns."""
    client_id = request.args.get('client_id', type=int)
    invoice_id = request.args.get('invoice_id', type=int)

    # Fetch context for Smart Selection
    invoice = InvoiceService.get_invoice_by_id(invoice_id) if invoice_id else None

    # Prefill Bill_to with this client
    clients = ClientService.get_all()
    # Populate eligible POs for this client including current po
    po_id = invoice.po_id if invoice else None
    pos = PurchaseOrderService.get_pos_by_client(client_id, include_id=po_id) if client_id else []
    
    return render_template('invoices/partials/client_cascades.html', 
                           clients=clients, 
                           pos=pos, 
                           selected_id=client_id,
                           invoice=invoice)

@bp.route('/load-po-details')
def load_po_details():
    """OOB Teleportation: Prefills Bill-To, Pool Value, and Remaining Items when PO changes."""
    # 1. Extract IDs from the HTMX request
    po_id = request.args.get('po_id', type=int)
    invoice_id = request.args.get('invoice_id', type=int)

    # 2. Fetch context for the Brain and the Template
    po = PurchaseOrderService.get_po_by_id(po_id) if po_id else None
    invoice = InvoiceService.get_invoice_by_id(invoice_id) if invoice_id else None
    
    if not po: 
        return ""

    # 3. Get remaining items from PO
    remaining_items = po.remaining_items # type: ignore

    for idx, item in enumerate(remaining_items):
        # Changed agreed_unit_price to billed_unit_price in the remaining_items key
        item['billed_unit_price'] = item.pop('agreed_unit_price')
        item['row_id'] = f"{int(time.time() * 1000)}{idx}"

    # 4. Populate clients and products list for bill_to and item_row
    clients = ClientService.get_all()
    products = ProductService.get_all()

    print('po.total_prepayment:', po.total_prepayment)
    print('po.remaining_credit:', po.remaining_credit)

    # 5. Return the single unified OOB template
    resp = make_response(render_template(
        'invoices/partials/po_selection_oob.html',
        po=po,
        invoice=invoice,           # Context for Smart Return logic
        selected_po_id=po_id,      # Context to unlock the Bill-To field
        mode='edit' if invoice else 'add',
        items=remaining_items,
        clients=clients,
        products=products
    ))

    # 6. Trigger math recalculation
    resp.headers['HX-Trigger-After-Swap'] = 'recalculate' # Trigger grand total
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
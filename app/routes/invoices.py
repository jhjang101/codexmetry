from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.orders_service import OrderService
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..services.settings_service import CarrierService
from ..services.attachment_service import AttachmentService
from ..services.audit_service import AuditLogService
from ..services.settings_service import SettingsMetadata
from ..utils.money import parse_to_cents
from ..utils.docs import generate_doc_number
from ..utils.sync import sync_invoice_status, sync_po_status
from ..utils.auth import role_required
from ..models import Invoice, Product, SettingsMetadata
from ..extensions import db
from datetime import datetime, timedelta
import time

bp = Blueprint('invoices', __name__)

@bp.before_request
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

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = InvoiceService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)
    # Standard HTMX response check
    if request.headers.get('HX-Request'):
        return render_template('invoices/partials/list.html', pagination=pagination)
    
    return render_template('invoices/invoices.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
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
                'carrier_id': request.form.get('carrier_id'),
                'ship_date': request.form.get('ship_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Parse Attachments
            new_files = request.files.getlist('attachments')

            # 4. Save Invoice and Line Items
            new_invoice, po_status = InvoiceService.add_invoice(header_data, items, new_files=new_files)

            # 5. Flash Messages
            flash(f"Invoice {new_invoice.invoice_number} created!", "success")
            # New/Current PO Ripple Feedback
            if po_status and po_status['before'] != po_status['after']:
                po_name = new_invoice.purchase_order.po_number or new_invoice.order.order_number
                flash(f"Associated PO {po_name} status updated: {po_status['before'].upper()} → {po_status['after'].upper()}", "success")

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('invoices.view', id=new_invoice.id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
    
    # GET: Prepare form data from Client or PO
    referrer = request.referrer
    # Only use referrer if it's not the 'add' page itself
    cancel_url = url_for('invoices.index')
    if referrer and url_for('invoices.add') not in referrer:
        cancel_url = referrer

    client_id = request.args.get('client_id', type=int) # from Client
    po_id = request.args.get('po_id', type=int) # from PO

    payer_prefill_id = None
    po_total_prepayment = 0
    pos = []
    payers = []
    items = []

    # generate invoice from client
    if client_id and not po_id:
        client = ClientService.get_by_id(client_id)
        if not client:
            flash("Client not found", "error")
            return redirect(url_for('invoices.index'))
        
        # Gatekeeper: Prevent landing on an invoice form with nothing to bill
        if not client.has_open_pos:
            flash(f"Client {client.company_name} has no open Purchase Orders to invoice.", "warning")
            return redirect(url_for('clients.view', id=client_id))
        pos = PurchaseOrderService.get_pos_by_client(client_id, statuses=['open'])

    # generate invoice from PO
    if po_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        if not po:
            flash("Purchase Order not found.", "error")
            return redirect(url_for('invoices.index'))
        
        if po.status != 'open':
            flash(f"PO {po.po_number or po.order.order_number} has already been fully invoiced.", "warning")
            return redirect(url_for('purchase_orders.view', id=po.id))
        
        client_id = po.client_id if po else None
        payer_prefill_id = po.bill_to_id if po else None
        po_total_prepayment = po.total_prepayment if po else 0 # type: ignore
        pos = PurchaseOrderService.get_pos_by_client(client_id, 
                                                     include_id=po_id,
                                                     statuses=['open']) if client_id else []
        payers = ClientService.get_all()

        print('po.remaining_items:', po.remaining_items) 

        # Prefill remaining items from this PO
        remaining = po.remaining_items # type: ignore
        for idx, item in enumerate(remaining):
            item['billed_unit_price'] = item.pop('agreed_unit_price')
            item['row_id'] = f"{int(time.time() * 1000)}{idx}"
        items = remaining

        
    # GET: Prepare form data    
    clients=ClientService.get_all()
    products=ProductService.get_all_products(include_prepayment=True)
    suggested_number = generate_doc_number(prefix='I', model=Invoice, column_name='invoice_number')
    carriers = CarrierService.get_all()
    initial_row_id = str(int(time.time() * 1000))
    return render_template('invoices/form.html', 
                           mode='add', 
                           invoice=None, 
                           clients=clients, 
                           pos=pos,
                           payers=payers,
                           products=products,
                           suggested_number=suggested_number,
                           carriers=carriers,
                           client_id=client_id,
                           po_id=po_id,
                           payer_prefill_id=payer_prefill_id,
                           po_total_prepayment=po_total_prepayment, # need to display remaining credit if po reveiced prepayment
                           items=items,
                           timestamp=initial_row_id,
                           cancel_url=cancel_url)

@bp.route('/view/<int:id>')
def view(id):
    try:
        # 1. Fetch the primary Invoice record (Calculates specific balance/pool)
        invoice = InvoiceService.get_invoice_by_id(id)
        if not invoice:
            flash("Invoice not found.", "error")
            return redirect(url_for('invoices.index'))


        print('invoice.total_amount:', invoice.total_amount)
        print('invoice.total_due:', invoice.total_due)
        print('invoice.remaining_credit:', invoice.remaining_credit)
        print('invoice.balance:', invoice.balance)
        print('invoice.po_total_deposit:', invoice.po_total_prepayment)

        # 2. Fetch the Order History (The Tree)
        # We only fetch this in 'view' mode to keep 'edit' and 'add' modes fast.
        tree = OrderService.get_deal_tree(invoice.order_id)
        history = AuditLogService.get_for_entity('Invoice', id)


        return render_template('invoices/form.html', 
                               mode='view', 
                               invoice=invoice, 
                               tree=tree,
                               history=history)

    except Exception as e:
        flash(f"Error loading invoice: {str(e)}", "error")
        return redirect(url_for('invoices.index'))

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    """Edit mode: handles header updates and item list synchronization."""
    invoice = InvoiceService.get_invoice_by_id(id)

    print('invoice.po_total_prepayment:', invoice.po_total_prepayment)


    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('invoices.index'))
    
    if request.method == 'POST':
        try:
            # 1. Capture State for Sync ripples
            old_status = invoice.status
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
                'carrier_id': request.form.get('carrier_id'),
                'ship_date': request.form.get('ship_date'),
                'tracking_number': request.form.get('tracking_number'),
                'note': request.form.get('note')
            }

            # 3. Parse Items
            items = _parse_items_form(request.form)
            
            # 4. Update Attachments (Handle new and marked for delete)
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]

            # 5. Update Invoice and Line Items
            invoice, invoice_status, old_po_status, new_po_status = InvoiceService.edit_invoice(id, 
                                                                                   header_data, 
                                                                                   items, 
                                                                                   new_files=new_files, 
                                                                                   delete_ids=delete_ids)

            # 6. Flash Messages
            flash(f"Invoice {invoice.invoice_number} updated successfully!", "success")
            # New/Current PO Ripple Feedback
            if new_po_status and new_po_status['before'] != new_po_status['after']:
                po_name = invoice.purchase_order.po_number or invoice.order.order_number
                flash(f"Associated PO {po_name} status updated: {new_po_status['before'].upper()} → {new_po_status['after'].upper()}", "success")
            # Old PO Ripple Feedback (Only fires if a PO swap occurred)
            if old_po_status and old_po_status['before'] != old_po_status['after']:
                # Fetch old name for forensic clarity in the UI
                flash(f"Previous PO {old_po_name} status reverted: {old_po_status['before'].upper()} → {old_po_status['after'].upper()}", "info")

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('invoices.view', id=id)
            return response
            
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Populate dropdowns for the edit form
    clients = ClientService.get_all()
    products = ProductService.get_all()
    # Fetch eligible POs for this specific client so the dropdown is populated on load
    pos = PurchaseOrderService.get_pos_by_client(invoice.client_id, 
                                                 include_id=invoice.po_id,
                                                 statuses=['open'])
    carriers = CarrierService.get_all()
    return render_template('invoices/form.html', 
                           mode='edit', 
                           invoice=invoice, 
                           clients=clients, 
                           payers=clients,
                           products=products, 
                           carriers=carriers,
                           pos=pos)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    """Specialized archive for invoices with payment protection."""
    # 1. Perform specialized archive
    invoice, has_payments, po_status = InvoiceService.archive_invoice(id)

    if not invoice:
        flash(f'Invoice not found.', 'error')
        return redirect(url_for('invoices.index'))

    # 3. Flash Messages
    flash(f'Invoice {invoice.invoice_number} moved to archives.', 'warning')

    # MONEY SAFETY WARNING: Tell the user exactly where the money went
    if has_payments:
        po_name = invoice.purchase_order.po_number or invoice.order.order_number
        flash(f'ATTENTION: This invoice had active payments. These funds are now sitting as a credit on PO {po_name}.', 'error')

    # PO SYNC FEEDBACK
    if po_status and po_status['before'] != po_status['after']:
        po_name = invoice.purchase_order.po_number or invoice.order.order_number
        flash(f"Previous PO {po_name} status reverted: {po_status['before'].upper()} → {po_status['after'].upper()}", "info")
        
    return redirect(url_for('invoices.index'))

# --- PRINT ---

@bp.route('/print/<int:id>')
@login_required
def print_view(id):
    """
    Messenger: Fetches hydrated Invoice data for the printable layout.
    Metadata is already injected via global context processor.
    """
    # 1. Promote status and fetch hydrated object
    invoice, invoice_status, po_status = InvoiceService.issue_invoice(id)
    if not invoice_status:
        flash("Invoice not found.", "error")
        return redirect(url_for('invoices.index'))

    # 2. Feedback
    if invoice_status and invoice_status['before'] != invoice_status['after']:
        flash(f"Invoice issued. Status updated from {invoice_status['before'].upper()} to {invoice_status['after'].upper()}.", "success")
    if po_status and po_status['before'] != po_status['after']:
        # Fetch old name for forensic clarity in the UI
        po_name = invoice.purchase_order.po_number or invoice.order.order_number # type: ignore
        flash(f"Associated PO {po_name} status updated from {po_status['before'].upper()} to {po_status['after'].upper()}.", "success")

    # 2. Initialize buckets
    line_display_items = []
    subtotal = 0
    tax_total = 0
    shipping_total = 0
    
    # 3. Sort items based on document_placement
    for item in invoice.items:
        item_value = item.quantity * item.billed_unit_price
        placement = item.product.document_placement

        if placement == 'Tax':
            tax_total += item_value
        elif placement == 'Shipping':
            shipping_total += item_value
        else:
            line_display_items.append(item)
            subtotal += item_value

    # 4. Calculate Payment Due Date
    metadata = db.session.get(SettingsMetadata, 1)
    net_days = metadata.default_net_days if metadata else 30
    due_date = invoice.invoice_date + timedelta(days=net_days)

    # 5. Change invoice status to open


    # 6. Pass pre-calculated values to the template
    return render_template('invoices/print.html', 
                           invoice=invoice, 
                           line_display_items=line_display_items,
                           subtotal=subtotal,
                           tax_total=tax_total,
                           shipping_total=shipping_total,
                           due_date=due_date)

# --- HTMX Item-row and Calculation Routes ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all_products(include_prepayment=True)
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
    try:
        # 1. Capture State
        raw_pids = request.form.getlist('product_ids[]')
        row_id = request.form.get('row_id')
        row_ids = request.form.getlist('row_ids[]')
        quantities = request.form.getlist('quantities[]')
        unit_prices = request.form.getlist('unit_prices[]')

        # Extract the hidden deposit pool value (it is stored in cents)
        try:
            po_total_prepayment = int(request.form.get('po_total_prepayment', 0))
        except (ValueError, TypeError):
            po_total_prepayment = 0

        # 2. Guard: Detect if 'PRE-PMT' is present in the current rows
        # We need to look up the catalog numbers of the submitted product_ids
        raw_pids = request.form.getlist('product_ids[]')
        product_ids = [int(pid) for pid in raw_pids if pid.strip()]
        
        has_prepayment = False
        for pid in product_ids:
            if not pid: continue
            product = db.session.get(Product, int(pid))
            # If Prepayment Invoice flag has_prepayment True
            if product and product.catalog_number == 'PRE-PMT':
                has_prepayment = True
                break
        
        # 3. Calculation
        # Initialize variables
        line_total = 0
        grand_total = 0

        # Iterate through all rows to calculate the Grand Total
        for r_id, qty, price_str in zip(row_ids, quantities, unit_prices):
            q = int(qty) if qty else 0
            # parse_to_cents handles the negative sign from the Applied Deposit row
            p = parse_to_cents(price_str)
            
            total = q * p
            grand_total += total

            # 2. Capture the Line Total for the specific row being edited
            if r_id == row_id:
                line_total = total

        # 4. Derive UI-only properties
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
            po_total_prepayment=po_total_prepayment,
            has_prepayment=has_prepayment # OOB swap that hides the "Add Item" button if a prepayment is detected.
        )
    
    except ValueError as e:
        # Failure: Rollback (Safety first) and OOB Error
        db.session.rollback()
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        # Tell HTMX not to clear the total or the input that caused the error
        resp.headers['HX-Reswap'] = 'none'
        return resp

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """Triggered by Client change: updates Bill-To and PO dropdowns."""
    # Read Data
    invoice_id = request.args.get('invoice_id', type=int)
    client_id = request.args.get('client_id', type=int)

    print('invoice_id:', invoice_id)

    po_id = None # add
    if invoice_id: # edit
        invoice = InvoiceService.get_by_id(invoice_id)
        po_id = invoice.po_id if invoice else None

    # Fetch POs for the selected client
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id # includes current po in edit
        ) if client_id else []
    
    return render_template('invoices/partials/client_cascades.html', 
                           invoice_id=invoice_id, # Add if none else Edit
                           client_id=client_id,   # need for enable/disable dropdown
                           pos=pos)

@bp.route('/load-po-details')
def load_po_details():
    """OOB Teleportation: Prefills Bill-To, Pool Value, and Remaining Items when PO changes."""
    # 1. Extract IDs from the HTMX request
    invoice_id = request.args.get('invoice_id', type=int)
    po_id = request.args.get('po_id', type=int)

    print('po_id:', po_id)
    print('invoice_id:', invoice_id)

    # 2. Prefill Bill_To and remaining items from this PO
    payer_prefill_id = None 
    po_total_prepayment = 0
    items = []
    if po_id:
        po = PurchaseOrderService.get_po_by_id(po_id, exclude_invoice_id=invoice_id)
        payer_prefill_id = po.bill_to_id if po else None
        remaining = po.remaining_items # type: ignore
        for idx, item in enumerate(remaining):
            item['billed_unit_price'] = item.pop('agreed_unit_price')
            item['row_id'] = f"{int(time.time() * 1000)}{idx}"
        items = remaining
        po_total_prepayment = po.total_prepayment if po else 0 # type: ignore


        print('po.total_prepayment:', po.total_prepayment)
        print('po.remaining_credit:', po.remaining_credit)


    # 3. Populate payers from Clients for the Bill_To 
    # and products list for item_row
    payers = ClientService.get_all()
    products = ProductService.get_all()

    for item in items:
        print('item:', item)


    # 5. Return the single unified OOB template
    resp = make_response(render_template(
        'invoices/partials/po_selection_oob.html',
        invoice_id=invoice_id,
        po_id=po_id,      # need for enable/disable dropdown
        payers=payers,
        products=products,
        payer_prefill_id=payer_prefill_id,
        po_total_prepayment=po_total_prepayment, # need to display remaining credit if po reveiced prepayment
        items=items))

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
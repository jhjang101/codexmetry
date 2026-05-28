from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..models import Payment
from ..services.orders_service import OrderService
from ..services.payments_service import PaymentService
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.clients_service import ClientService
from ..services.settings_service import PaymentTypeService
from ..services.attachment_service import AttachmentService
from ..services.audit_service import AuditLogService
from ..utils.docs import generate_doc_number
from ..utils.sync import sync_invoice_status, sync_po_status
from ..utils.auth import role_required
from ..utils.errors import handle_post_error
from ..utils.money import format_usd
from ..models import Payment
from ..extensions import db
from datetime import datetime
import time

bp = Blueprint('payments', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---
# view, add, and edit route is now htmx

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['payments_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = PaymentService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)
    
    if request.headers.get('HX-Request'):
        return render_template('payments/partials/list.html', pagination=pagination)
    
    return render_template('payments/payments.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare Data
            payment_data = {
                'client_id': request.form.get('client_id'),
                'payment_number': request.form.get('payment_number'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'paid_from_id': request.form.get('paid_from_id'),
                'payment_type_id': request.form.get('payment_type_id'),
                'amount': request.form.get('amount'),
                'payment_date': request.form.get('payment_date'),
                'note': request.form.get('note'),
                'paid_from_address': request.form.get('paid_from_address')
            }

            # 2. Parse Attachments
            new_files = request.files.getlist('attachments')

            # 3. Call Atomic Service
            new_payment, invoice_status, po_status = PaymentService.add_payment(payment_data, new_files=new_files)
            
            # 5. Flash message
            flash(f"Payment for {new_payment.payment_number} recorded successfully!", "success")

            if invoice_status and invoice_status['before'] != invoice_status['after']:
                invoice_name = new_payment.invoice.invoice_number
                flash(f"Associated Invoice {invoice_name} status updated: {invoice_status['before'].upper()} → {invoice_status['after'].upper()}", "info")

            if po_status and po_status['before'] != po_status['after']:
                po_name = new_payment.purchase_order.po_number or new_payment.order.order_number
                flash(f"Associated PO {po_name} status updated: {po_status['before'].upper()} → {po_status['after'].upper()}", "info")
            
            # Adjustment Ripple Flash
            # We look specifically inside the invoice_status for the adjustment packet
            if invoice_status:
                adjustment_status = invoice_status.get('adjustment')
                if isinstance(adjustment_status, dict):
                    action = adjustment_status.get('action')
                    adjustment_number = adjustment_status.get('number')
                    raw_amount = adjustment_status.get('amount', 0)
                    amount = int(raw_amount) if raw_amount is not None else 0
                    amount_str = format_usd(amount)
                    
                    if action == 'CREATE':
                        flash(f"Threshold gap of {amount_str} auto-recorded as a Write-off Adjustment {adjustment_number}.", "info")
                    elif action == 'UPDATE':
                        flash(f"System Write-off Adjustment {adjustment_number} updated to match new {amount_str} gap.", "info")
                    elif action == 'DELETE':
                        flash("System Write-off Adjustment {adjustment_number} has been removed (Invoice settled or re-opened).", "info")

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('payments.view', id=new_payment.id)
            return response
        
        
        except Exception as e:
            return handle_post_error(e, "payments.add")
        
    # GET: Prepare form data from PO or Invoice
    referrer = request.referrer
    # Only use referrer if it's not the 'add' page itself
    cancel_url = url_for('payments.index')
    if referrer and url_for('payments.add') not in referrer:
        cancel_url = referrer

    client_id = request.args.get('client_id', type=int)
    po_id = request.args.get('po_id', type=int)
    invoice_id = request.args.get('invoice_id', type=int)

    payer_prefill_id = None
    amount_prefill = None
    pos = []
    invoices = []
    is_po_open = True

    # 1. generate payment from Invoice Shortcut
    if invoice_id:
        invoice = InvoiceService.get_invoice_by_id(invoice_id)
        # GUARD: Existence and Activity
        if not invoice or not invoice.is_active:
            flash("Invoice not found or archived.", "error")
            return redirect(url_for('payments.index'))
        
        # GUARD: Already Paid
        if invoice.status == 'completed':
            flash(f"Invoice {invoice.invoice_number} is already fully paid.", "warning")
            return redirect(url_for('invoices.view', id=invoice_id))
        
        client_id = invoice.client_id
        po_id = invoice.po_id
        # Set is_po_open based on the parent PO status
        is_po_open = (invoice.purchase_order.status == 'open')
        payer_prefill_id = invoice.bill_to_id
        amount_prefill = invoice.balance # type: ignore

    # 2. generate payment from PO Shortcut
    elif po_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        # GUARD: Existence and Activity
        if not po or not po.is_active:
            flash("Purchase Order not found or archived.", "error")
            return redirect(url_for('payments.index'))
        
        # GUARD: Fully Settled deal (Optional but recommended)
        if po.status == 'completed':
            flash(f"This order is already completed.", "warning")
            return redirect(url_for('purchase_orders.view', id=po_id))

        client_id = po.client_id
        payer_prefill_id = po.bill_to_id
        amount_prefill = 0
        is_po_open = (po.status == 'open')

    # 3. generate payment from Client Shortcut
    elif client_id:
        client = ClientService.get_client_by_id(client_id)
        if not client or not client.is_active:
            flash("Client not found or archived.", "error")
            return redirect(url_for('clients.index'))
        
        # Guard: Ensure there's actually something to pay (optional, but good UX)
        if not client.has_open_pos and not client.has_open_invoices:
            flash(f"Client {client.company_name} has no active POs or Invoices to record payments.", "warning")
            return redirect(url_for('clients.view', id=client_id))

        payer_prefill_id = client_id
        amount_prefill = 0
        is_po_open = True # Default to True so Prepayment option is visible initially

    # Populate Dropdown options
    if client_id:
        pos = PurchaseOrderService.get_pos_by_client(client_id, 
                                                     include_id=po_id, 
                                                     statuses=['open', 'invoiced'])
    if po_id:
        invoices = InvoiceService.get_invoices_by_po(po_id, 
                                                     include_id=invoice_id, 
                                                     statuses=['draft', 'open'])
        
    # GET: Standar add Prepare form data    
    clients=ClientService.get_all()
    suggested_number = generate_doc_number(prefix='P', model=Payment, column_name='payment_number')
    payment_types = PaymentTypeService.get_all()
    return render_template('payments/form.html', 
                           mode='add', 
                           payment=None, 
                           clients=clients,
                           payers=clients,
                           pos=pos,
                           invoices=invoices,
                           payment_types=payment_types,
                           suggested_number=suggested_number,
                           client_id=client_id,
                           po_id=po_id,
                           invoice_id=invoice_id,
                           is_po_open=is_po_open,
                           payer_prefill_id=payer_prefill_id,
                           amount_prefill=amount_prefill,
                           cancel_url=cancel_url)

@bp.route('/view/<int:id>')
def view(id):
    payment = PaymentService.get_payment_by_id(id)
    if not payment:
        flash("Payment not found.", "error")
        return redirect(url_for('payments.index'))

    # # Identifiers for title display
    # if payment.invoice:
    #     payment_number = f'{payment.invoice.invoice_number}'
    # elif payment.purchase_order.po_number:
    #     payment_number = f'{payment.purchase_order.po_number}'
    # else:
    #     payment_number = f'{payment.order.order_number}'

    tree = OrderService.get_deal_tree(payment.order_id)
    history = AuditLogService.get_for_entity('Payment', id)

    return render_template('payments/form.html', 
                        mode='view', 
                        payment=payment,
                        # payment_number=payment_number,
                        tree=tree,
                        history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    """Edit mode: handles header updates."""
    payment = PaymentService.get_payment_by_id(id)
    if not payment:
        flash("Payment not found.", "error")
        return redirect(url_for('payments.index'))
    
    if request.method == 'POST':
        try:
            old_invoice_name = payment.invoice.invoice_number if payment.invoice else None
            old_po_name = payment.purchase_order.po_number or payment.order.order_number

            # 1. Prepare Data
            payment_data = {
                'client_id': request.form.get('client_id'),
                'payment_number': request.form.get('payment_number'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'paid_from_id': request.form.get('paid_from_id'),
                'payment_type_id': request.form.get('payment_type_id'),
                'amount': request.form.get('amount'),
                'payment_date': request.form.get('payment_date'),
                'note': request.form.get('note'),
                'paid_from_address': request.form.get('paid_from_address')
            }

            # 2. Parse Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]

            # 3. Call Atomic Service (Guard handles "Snapshot Lock")
            payment, old_invoice_status, new_invoice_status, old_po_status, new_po_status = PaymentService.edit_payment(id, payment_data, new_files=new_files, delete_ids=delete_ids)
            
            # 4. Flash Messages
            flash(f"Payment {payment.payment_number} updated successfully!", "success")
            # New Invoice Flash
            if new_invoice_status and new_invoice_status['before'] != new_invoice_status['after']:
                invoice_name = payment.invoice.invoice_number if payment.invoice else None
                flash(f"Associated Invoice {invoice_name} status pdated: {new_invoice_status['before'].upper()} → {new_invoice_status['after'].upper()}", "info")
            # Old Invoice Flash (The Reversion)
            if old_invoice_status and old_invoice_status['before'] != old_invoice_status['after']:
                flash(f"Previous Invoice {old_invoice_name} status reverted: {old_invoice_status['before'].upper()} → {old_invoice_status['after'].upper()}", "info")
            # New PO Flash
            if new_po_status and new_po_status['before'] != new_po_status['after']:
                po_name = payment.purchase_order.po_number or payment.order.order_number
                flash(f"Associated PO {po_name} updated: {new_po_status['before'].upper()} → {new_po_status['after'].upper()}", "info")
            # Old PO Flash
            if old_po_status and old_po_status['before'] != old_po_status['after']:
                flash(f"Previous PO {old_invoice_name} reverted: {old_po_status['before'].upper()} → {old_po_status['after'].upper()}", "info")
            # The Dual Adjustment Ripple Flash
            # We loop through both old and new invoice results
            for status in [old_invoice_status, new_invoice_status]:
                if not status: continue
                
                adjustment_status = status.get('adjustment')
                if isinstance(adjustment_status, dict):
                    action = adjustment_status.get('action')
                    adjustment_number = adjustment_status.get('number')
                    raw_amt = adjustment_status.get('amount', 0)
                    amount = int(raw_amt) if raw_amt is not None else 0
                    amt_str = format_usd(amount)

                    # Note: We keep the message generic because the user just 
                    # performed the action and knows which invoices are involved.
                    if action == 'CREATE':
                        flash(f"Threshold gap of {amt_str} auto-recorded as a Write-off Adjustment {adjustment_number}.", "info")
                    elif action == 'UPDATE':
                        flash(f"System Write-off Adjustment {adjustment_number} updated to match new {amt_str} gap.", "info")
                    elif action == 'DELETE':
                        flash("System Write-off Adjustment {adjustment_number} has been removed (Invoice re-opened or settled).", "info")

            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('payments.view', id=id)
            return response
        
        except Exception as e:
            return handle_post_error(e, "payments.edit")
    
    # GET: Prepare Context
    clients = ClientService.get_all()
    payment_types = PaymentTypeService.get_all()
    
    # Fetch lists using include_id to ensure saved records stay visible
    pos = PurchaseOrderService.get_pos_by_client(payment.client_id, include_id=payment.po_id, statuses=['open', 'invoiced'])
    invoices = InvoiceService.get_invoices_by_po(payment.po_id, include_id=payment.invoice_id)

    # payment_number represents the initial identity for the page title/header
    if payment.invoice:
        payment_number = f'{payment.invoice.invoice_number}'
    elif payment.purchase_order.po_number:
        payment_number = f'{payment.purchase_order.po_number}'
    else:
        payment_number = f'{payment.order.order_number}'
        
    return render_template('payments/form.html', 
                           mode='edit', 
                           payment=payment, 
                           clients=clients,
                           pos=pos,
                           invoices=invoices,
                           payers=clients,
                           payment_number=payment_number,
                           payment_types=payment_types,
                           amount_prefill = None)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    """Soft delete the payment with credit pool validation."""
    try:
        # 1. Attempt specialized archive
        payment, invoice_status, po_status = PaymentService.archive_payment(id)
        
        if not payment:
            raise ValueError("Payment not found.")
        
        # 2. Success Flashes
        flash(f'Payment for {payment.payment_number} archived.', 'success')
        if invoice_status and invoice_status['before'] != invoice_status['after']:
            invoice_name = payment.invoice.invoice_number if payment.invoice else None
            flash(f"Associated Invoice {invoice_name} status updated: {invoice_status['before'].upper()} → {invoice_status['after'].upper()}", "info")
        if po_status and po_status['before'] != po_status['after']:
            po_name = payment.purchase_order.po_number or payment.order.order_number
            flash(f"Associated PO {po_name} status updated: {po_status['before'].upper()} → {po_status['after'].upper()}", "info")
        # Adjustment Ripple Flash
        # We look specifically inside the invoice_status for the adjustment packet
        if invoice_status:
            adjustment_status = invoice_status.get('adjustment')
            if isinstance(adjustment_status, dict):
                action = adjustment_status.get('action')
                adjustment_number = adjustment_status.get('number')
                raw_amount = adjustment_status.get('amount', 0)
                amount = int(raw_amount) if raw_amount is not None else 0
                amount_str = format_usd(amount)
                
                if action == 'CREATE':
                    flash(f"Threshold gap of {amount_str} auto-recorded as a Write-off Adjustment {adjustment_number}.", "info")
                elif action == 'UPDATE':
                    flash(f"System Write-off Adjustment {adjustment_number} updated to match new {amount_str} gap.", "info")
                elif action == 'DELETE':
                    flash(f"System Write-off Adjustment {adjustment_number} has been removed (Invoice settled or re-opened).", "info")
                    
        return redirect(url_for('payments.index'))
    
    except Exception as e:
        return handle_post_error(e, "payments.archive")

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """
    Triggered by Client select. 
    Updates: PO List, Paid-From (matches client), resets Invoice, resets Amount.
    """
    # Read data
    payment_id = request.args.get('payment_id', type=int) # None if add 
    client_id = request.args.get('client_id', type=int)

    po_id = None # add
    if payment_id: # edit
        payment = PaymentService.get_payment_by_id(payment_id)
        po_id = payment.po_id if payment else None

    # Fetch POs for the selected client (Standard)
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id,   # includes current po in edit
        statuses=['open', 'invoiced'],  # includes 'open' POs and POs that have 'open' invoices.
        ) if client_id else []

    # Populate payers from Clients for the Paid-from
    # payers = ClientService.get_all() # For the Paid-From list

    return render_template('payments/partials/client_cascades.html', 
                           payment_id=payment_id,   # Add if none else Edit
                           client_id=client_id,     # need for enable/disable dropdown
                           pos=pos,
                           amount_prefill=0)

@bp.route('/update-po-cascades')
def update_po_cascades():
    """
    Triggered by PO slelct.
    Updates: Invoice List, Paid-From (matches po.bill_to), Amount (matches po.balance) 
    """
    # Read data
    payment_id = request.args.get('payment_id', type=int)
    po_id = request.args.get('po_id', type=int)
    
    # Get current invoice_id and payer_id
    invoice_id = None # add
    payer_id = None # add
    if payment_id: # edit
        payment = PaymentService.get_by_id(payment_id)
        invoice_id = payment.invoice_id if payment.invoice else None
        payer_id = payment.paid_from_id if payment.paid_from else None

    # Populate eligible Invoices for this PO
    invoices = InvoiceService.get_invoices_by_po(po_id, include_id=invoice_id) if po_id else []

    # Prefill payer from selected PO
    payer_prefill_id = None
    is_po_open = True
    if po_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        payer_prefill_id = po.bill_to.id if po else None
        is_po_open = False if po.status != 'open' else True # type: ignore

    # Populate payers from Clients for the Paid-from
    payers = ClientService.get_all()

    return render_template('payments/partials/po_cascades.html', 
                           payment_id=payment_id,   # Add if none else Edit
                           po_id=po_id,             # need for enable/disable dropdown
                           invoices=invoices,
                           is_po_open=is_po_open,
                           payers=payers,
                           payer_prefill_id=payer_prefill_id)

@bp.route('/update-invoice-cascades')
def update_invoice_cascades():
    """
    Triggered by Invoice select.
    Updates: Paid-From (matches invoice.bill_to) Amount (matches invoice.balance)
    """
    # Read data
    payment_id = request.args.get('payment_id', type=int)
    po_id = request.args.get('po_id', type=int)
    invoice_id = request.args.get('invoice_id', type=int)

    # Get current payer_id and amount -------------------------No need but need to decide if you want to pass payer and amount from db or selected po when switch back to original invoice in edit.
    po = PurchaseOrderService.get_by_id(po_id) if po_id else None
    payer_id = po.bill_to.id if po else None # add
    amount = None # add
    if payment_id: # edit
        payment = PaymentService.get_by_id(payment_id)
        payer_id = payment.paid_from_id if payment.paid_from else None
        amount = payment.amount if payment else None

    # Prefill Paid_from and Amount with this invoice
    payer_prefill_id = None
    amount_prefill = None
    if invoice_id:
        invoice = InvoiceService.get_invoice_by_id(invoice_id)
        payer_prefill_id = invoice.bill_to.id # type: ignore
        amount_prefill = invoice.balance # type: ignore
    elif po_id:
        po = PurchaseOrderService.get_by_id(po_id) if po_id else None
        payer_prefill_id = po.bill_to.id if po else None 
        amount_prefill = 0



    # Populate payers from Clients for the Paid-from
    payers = ClientService.get_all()

    print('payment_id', payment_id)
    print('po_id:', po_id)
    print('invoice_id:', invoice_id)
    # print('payer_id:', payer_id)
    print('payer_prefill_id:', payer_prefill_id) 
    print('amount_prefill:', amount_prefill)


    return render_template('payments/partials/invoice_cascades.html',
                           payment_id=payment_id,   # Add if none else Edit
                           po_id=po_id,             # need for enable/disable dropdown
                           payers=payers,
                           payer_prefill_id=payer_prefill_id,
                           amount_prefill=amount_prefill)

    





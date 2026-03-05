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
from ..utils.money import parse_to_cents
from ..utils.docs import generate_doc_number
from ..utils.sync import sync_invoice_status, sync_po_status
from ..utils.auth import role_required
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
                'note': request.form.get('note')
            }

            # 2. Call Atomic Service
            new_payment = PaymentService.add_payment(payment_data)

            # 3. Sync status
            invoice_status_updated = False
            po_status_updated = False
            if new_payment.invoice_id:
                invoice_status_updated = sync_invoice_status(new_payment.invoice_id)
                po_status_updated = sync_po_status(new_payment.po_id)

            # 4. Save Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Payment', new_payment.id, new_files=new_files)
            
            # 4. Flash message
            if new_payment.invoice:
                payment_number = f'invoice {new_payment.invoice.invoice_number}'
            elif new_payment.purchase_order.po_number:
                payment_number = f'PO {new_payment.purchase_order.po_number}'
            else:
                payment_number = f'order {new_payment.order.order_number}'
            flash(f"Payment for {payment_number} created successfully!", "success")

            if invoice_status_updated:
                invoice_name = new_payment.invoice.invoice_number if new_payment.invoice else None
                flash(f"Status of invoice {invoice_name} updated successfully!", "success")
            if po_status_updated:
                po_name = new_payment.purchase_order.po_number or new_payment.order.order_number
                flash(f"Status of PO {po_name} updated successfully!", "success")

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('payments.view', id=new_payment.id)
            return response
        
        
        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
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

    # generate payment from client
    if client_id and not po_id and not invoice_id:
        client = ClientService.get_by_id(client_id)
        if not client:
            flash("Client not found", "error")
            return redirect(url_for('payments.index'))
        
        # Gatekeeper: Must have an active deal context
        if not client.has_open_pos and not client.has_open_invoices:
            flash(f"Client {client.company_name} has outstanding open po or invoices.", "warning")
            return redirect(url_for('clients.view', id=client_id))
        
        pos = PurchaseOrderService.get_pos_by_client(client_id, statuses=['open', 'invoiced'])

    # generate payment from PO
    if po_id and not invoice_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        if not po:
            flash("Purchase Order not found.", "error")
            return redirect(url_for('payments.index'))
        
        client_id = po.client_id
        payer_prefill_id = po.bill_to_id
        amount_prefill = 0 # Force manual entry for deposits
        is_po_open = False if po.status != 'open' else True

    # generate payment from Invoice
    if invoice_id:
        invoice = InvoiceService.get_invoice_by_id(invoice_id)
        if not invoice:
            flash("Invoice not found.", "error")
            return redirect(url_for('payments.index'))
        
        client_id = invoice.client_id
        po_id = invoice.po_id
        po = PurchaseOrderService.get_by_id(po_id)
        if po:
            is_po_open = False if po.status != 'open' else True
        payer_prefill_id = invoice.bill_to_id
        amount_prefill = invoice.balance # type: ignore Suggest full settlement 

    # Populate Dropdown options
    if client_id:
        pos = PurchaseOrderService.get_pos_by_client(client_id, 
                                                     include_id=po_id, 
                                                     statuses=['open', 'invoiced'])
    if po_id:
        invoices = InvoiceService.get_invoices_by_po(po_id, 
                                                     include_id=invoice_id, 
                                                     statuses=['open'])
        
    # GET: Standar add Prepare form data    
    clients=ClientService.get_all()
    suggested_number = generate_doc_number(prefix='PMT', model=Payment, column_name='payment_number')
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
    try:
        payment = PaymentService.get_payment_by_id(id)
        if not payment:
            flash("Payment not found.", "error")
            return redirect(url_for('payments.index'))

        # Identifiers for title display
        if payment.invoice:
            payment_number = f'{payment.invoice.invoice_number}'
        elif payment.purchase_order.po_number:
            payment_number = f'{payment.purchase_order.po_number}'
        else:
            payment_number = f'{payment.order.order_number}'

        tree = OrderService.get_deal_tree(payment.order_id)

        return render_template('payments/form.html', 
                            mode='view', 
                            payment=payment,
                            payment_number=payment_number,
                            tree=tree)

    except Exception as e:
        flash(f"Error loading payment: {str(e)}", "error")
        return redirect(url_for('payments.index'))


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
            # 1. Capture State before update for Sync ripples
            old_invoice_id = payment.invoice_id
            old_invoice_name = payment.invoice.invoice_number if payment.invoice else None
            old_po_id = payment.po_id
            old_po_name = payment.purchase_order.po_number or payment.order.order_number 
            old_invoice_status_updated = False
            old_po_status_updated = False
            invoice_status_updated = False
            po_status_updated = False 

            # 2. Prepare Data
            payment_data = {
                'client_id': request.form.get('client_id'),
                'payment_number': request.form.get('payment_number'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'paid_from_id': request.form.get('paid_from_id'),
                'payment_type_id': request.form.get('payment_type_id'),
                'amount': request.form.get('amount'),
                'payment_date': request.form.get('payment_date'),
                'note': request.form.get('note')
            }

            # 3. Call Atomic Service (Guard handles "Snapshot Lock")
            PaymentService.edit_payment(id, payment_data)
            
            # 4. Capture State AFTER update
            new_invoice_id = payment.invoice_id
            new_po_id = payment.po_id
            
            # 5. Sync Brain Logic
            # If the invoice link changed, sync the old Invoice and PO first
            if old_invoice_id != new_invoice_id:
                if old_invoice_id:
                    old_invoice_status_updated = sync_invoice_status(old_invoice_id)
                    old_po_status_updated = sync_po_status(old_po_id)

            # Sync the current (new) invoice link
            if new_invoice_id:
                invoice_status_updated = sync_invoice_status(new_invoice_id)
                po_status_updated = sync_po_status(new_po_id)

            # 6. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Payment', id, new_files=new_files, delete_ids=delete_ids)

            # 7. Flash Messages
            flash(f"Payment updated successfully!", "success")
            
            # Flash for the current invoice and PO
            if invoice_status_updated:
                invoice_name = payment.invoice.invoice_number if payment.invoice else None
                flash(f"Status of invoice {invoice_name} updated successfully!", "success")
            if po_status_updated:
                po_name = payment.purchase_order.po_number or payment.order.order_number
                flash(f"Status of PO {po_name} updated successfully!", "success")
            
            # Flash for the old invoice and PO (if it was swapped)
            if old_invoice_status_updated:
                flash(f"Status of invoice {old_invoice_name} updated successfully!", "success")

            if old_po_status_updated:
                flash(f"Status of PO {old_po_name} updated successfully!", "success")
                
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('payments.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp
    
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
        payment = PaymentService.archive_payment(id)
        
        if not payment:
            flash(f'Payment not found.', 'error')
            return redirect(url_for('payments.index'))
        
        # 2. Sync invoice status (if this was a standard invoice payment)
        invoice_id = payment.invoice_id if payment else None
        po_id = payment.po_id if payment else None
        invoice_status_updated = False

        if invoice_id:
            invoice_status_updated = sync_invoice_status(invoice_id)
        po_status_updated = sync_po_status(po_id)

        # 3. Success Flashes
        # Document name logic for the message
        if payment.invoice:
                payment_number = f'invoice {payment.invoice.invoice_number}'
        elif payment.purchase_order.po_number:
            payment_number = f'PO {payment.purchase_order.po_number}'
        else:
            payment_number = f'order {payment.order.order_number}'

        flash(f'Payment for {payment_number} moved to archives.', 'warning')
        
        if invoice_status_updated:
            invoice_name = payment.invoice.invoice_number if payment.invoice else None
            flash(f"Status of invoice {invoice_name} updated successfully!", "success")
        if po_status_updated:
            po_name = payment.purchase_order.po_number or payment.order.order_number
            flash(f"Status of PO {po_name} updated successfully!", "success")

    except ValueError as e:
        db.session.rollback()
        flash(str(e), "error")
        return redirect(url_for('payments.view', id=id))

    return redirect(url_for('payments.index'))

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
        is_po_open = False if po.status != 'open' else True

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
        payer_prefill_id = invoice.bill_to.id
        amount_prefill = invoice.balance
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

    





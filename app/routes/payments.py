from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.payments_service import PaymentService
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.clients_service import ClientService
from ..services.settings_service import PaymentTypeService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..utils.sync import sync_invoice_status
from ..extensions import db
from datetime import datetime
import time

bp = Blueprint('payments', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['payments_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = PaymentService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('payments/partials/list.html', pagination=pagination)
    
    return render_template('payments/payments.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare Data
            payment_data = {
                'client_id': request.form.get('client_id'),
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

            # 3. Sync invoice status
            invoice_status_updated = False
            if new_payment.invoice_id:
                invoice_status_updated = sync_invoice_status(new_payment.invoice_id)

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

            if new_payment.invoice and invoice_status_updated:
                flash(f"Status of invoice {new_payment.invoice.invoice_number} updated successfully!", "success")
                
            return redirect(url_for('payments.index'))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('payments.add'))
        
    # GET: Prepare form data    
    clients=ClientService.get_all()
    payment_types = PaymentTypeService.get_all()
    return render_template('payments/form.html', 
                           mode='add', 
                           invoice=None, 
                           clients=clients,
                           payment_types=payment_types)

@bp.route('/view/<int:id>')
def view(id):
    payment = PaymentService.get_by_id(id)
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

    return render_template('payments/form.html', 
                           mode='view', 
                           payment=payment,
                           payment_number=payment_number)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit mode: handles header updates."""
    payment = PaymentService.get_by_id(id)
    if not payment:
        flash("Payment not found.", "error")
        return redirect(url_for('payments.index'))
    
    if request.method == 'POST':
        try:
            # 1. Capture State before update for Sync ripples
            old_invoice_id = payment.invoice_id
            old_invoice_number = payment.invoice.invoice_number if payment.invoice else None

            # 2. Prepare Data
            payment_data = {
                'client_id': request.form.get('client_id'),
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
            
            # 5. Sync Brain Logic
            invoice_status_updated = False
            old_invoice_status_updated = False
            # If the invoice link changed, sync the old one first
            if old_invoice_id != new_invoice_id:
                if old_invoice_id:
                    old_invoice_status_updated = sync_invoice_status(old_invoice_id)
            # Sync the current (new) invoice link
            if new_invoice_id:
                invoice_status_updated = sync_invoice_status(new_invoice_id)

            # 6. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Payment', id, new_files=new_files, delete_ids=delete_ids)

            # 7. Flash Messages
            flash(f"Payment updated successfully!", "success")
            
            # Flash for the current invoice
            if invoice_status_updated:
                flash(f"Status of invoice {payment.invoice.invoice_number} updated successfully!", "success")
            
            # Flash for the old invoice (if it was swapped)
            if old_invoice_status_updated:
                flash(f"Status of invoice {old_invoice_number} updated successfully!", "success")
                
            return redirect(url_for('payments.view', id=id))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('payments.edit', id=id))
    
    # GET: Prepare Context
    clients = ClientService.get_all()
    payment_types = PaymentTypeService.get_all()
    
    # Fetch lists using include_id to ensure saved records stay visible
    pos = PurchaseOrderService.get_pos_by_client(payment.client_id, include_id=payment.po_id, include_unpaid=True)
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
                           payment_number=payment_number,
                           payment_types=payment_types)

@bp.route('/archive/<int:id>', methods=['POST'])
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
        invoice_status_updated = False
        if invoice_id:
            invoice_status_updated = sync_invoice_status(invoice_id)

        # 3. Success Flashes
        # Document name logic for the message
        if payment.invoice:
                payment_number = f'invoice {payment.invoice.invoice_number}'
        elif payment.purchase_order.po_number:
            payment_number = f'PO {payment.purchase_order.po_number}'
        else:
            payment_number = f'order {payment.order.order_number}'

        flash(f'Payment for {payment_number} moved to archives.', 'warning')
        
        if payment.invoice and invoice_status_updated:
            flash(f"Status of {payment_number} updated successfully!", "success")

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
    client_id = request.args.get('client_id', type=int)
    payment_id = request.args.get('payment_id', type=int)
    payment = PaymentService.get_by_id(payment_id) if payment_id else None

    # 1. Fetch POs for the selected client (Standard)
    po_id = payment.po_id if payment else None
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id, 
        include_unpaid=True
        ) if client_id else []

    # 2. SMART RETURN: If returning to original client, fetch original invoices
    invoices = []
    if payment and client_id == payment.client_id:
        invoices = InvoiceService.get_invoices_by_po(
            payment.po_id, 
            include_id=payment.invoice_id
            )

    # Populate clients for the Paid-from
    clients = ClientService.get_all() # For the Paid-From list

    return render_template('payments/partials/client_cascades.html', 
                           clients=clients, 
                           pos=pos, 
                           invoices=invoices, 
                           selected_id=client_id,
                           payment=payment)

@bp.route('/update-po-cascades')
def update_po_cascades():
    """
    Triggered by PO slelct.
    Updates: Invoice List, Paid-From (matches po.bill_to), Amount (matches po.balance) 
    """
    po_id = request.args.get('po_id', type=int)
    payment_id = request.args.get('payment_id', type=int)
    payment = PaymentService.get_by_id(payment_id) if payment_id else None

    # Prefill Paid_from and Amount with this po
    po = PurchaseOrderService.get_po_by_id(po_id) if po_id else None
    
    # Populate clients for the Paid-from
    clients = ClientService.get_all() # For the Paid-From list

    # Pass client_id from the PO
    po_client_id = po.client_id if po else None

    # Populate eligible Invoices for this PO
    invoice_id = payment.invoice_id if payment else None
    invoices = InvoiceService.get_invoices_by_po(po_id, include_id=invoice_id) if po_id else []

    return render_template('payments/partials/po_cascades.html', 
                           invoices=invoices, 
                           selected_po_id=po_id, 
                           selected_id=po_client_id, 
                           po=po, 
                           payment=payment, 
                           clients=clients)

@bp.route('/update-invoice-cascades')
def update_invoice_cascades():
    """
    Triggered by Invoice select.
    Updates: Paid-From (matches invoice.bill_to) Amount (matches invoice.balance)
    """
    invoice_id = request.args.get('invoice_id', type=int)
    payment_id = request.args.get('payment_id', type=int)
    po_id = request.args.get('po_id', type=int)

    payment = PaymentService.get_by_id(payment_id) if payment_id else None

    # Prefill Paid_from and Amount with this invoice
    invoice = InvoiceService.get_invoice_by_id(invoice_id) if invoice_id else None

    # If invoice is deselected, we MUST have the PO to avoid disabling fields
    if not po_id and invoice:
        po_id = invoice.po_id
    po = PurchaseOrderService.get_po_by_id(po_id) if po_id else None

    # Pass client_id from the PO (PO and Invoice has same client)
    client_id = po.client_id if po else None

    # Populate clients for the Paid-from
    clients = ClientService.get_all() # For the Paid-From list

    return render_template('payments/partials/invoice_cascades.html', 
                           clients=clients, 
                           invoice=invoice, 
                           po=po,                       # Pass parent PO for pre-filling
                           selected_invoice_id=invoice_id,
                           selected_po_id=po_id,        # Context to keep fields enabled
                           selected_id=client_id,       # Client context
                           payment=payment)

    





from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.payments_service import PaymentService
from ..services.invoices_service import InvoiceService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.clients_service import ClientService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..extensions import db

bp = Blueprint('payments', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['invoices_last_url'] = request.full_path

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
            # 1. Save Payment Header
            payment_data = {
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'invoice_number': request.form.get('invoice_number'),
                'paid_from_id': request.form.get('paid_from_id'),
                'payment_type_id': request.form.get('payment_type_id'),
                'amount': request.form.get('amount'),
                'payment_date': request.form.get('payment_date'),
                'note': request.form.get('note')
            }
            new_payment = PaymentService.create_payment(payment_data)

            # 2. Save Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Invoice', new_payment.id, new_files=new_files)
            
            # 3. Flash message
            if new_payment.invoice:
                payment_number = f'invoice {new_payment.invoice.invoice_number}'
            elif new_payment.purchase_order:
                payment_number = f'PO {new_payment.purchase_order.po_number}'
            else:
                payment_number = f'order {new_payment.order.order_number}'
            flash(f"Payment for {payment_number} created successfully!", "success")
            return redirect(url_for('payments.index'))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('payments.add'))
        
    # GET: Prepare form data    
    clients=ClientService.get_all()
    return render_template('invoices/form.html', 
                           mode='add', 
                           invoice=None, 
                           clients=clients)

@bp.route('/view/<int:id>')
def view(id):
    payment = PaymentService.get_by_id(id)
    return render_template('payments/form.html', mode='view', payment=payment)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit mode: handles header updates."""
    payment = PaymentService.get_by_id(id)
    
    if request.method == 'POST':
        try:
            # 1. Update Payment Header
            payment_data = {
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'invoice_number': request.form.get('invoice_number'),
                'paid_from_id': request.form.get('paid_from_id'),
                'payment_type_id': request.form.get('payment_type_id'),
                'amount': request.form.get('amount'),
                'payment_date': request.form.get('payment_date'),
                'note': request.form.get('note')
            }
            PaymentService.update_payment(id, payment_data)

            # 2. Update Attachments (Handle new and marked for delete)
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Payment', id, new_files=new_files, delete_ids=delete_ids)

            # 3. Flash
            if payment.invoice:
                payment_number = f'invoice {payment.invoice.invoice_number}'
            elif payment.purchase_order:
                payment_number = f'PO {payment.purchase_order.po_number}'
            else:
                payment_number = f'order {payment.order.order_number}'
            flash(f"Payment for {payment_number} updated successfully!", "success")
            return redirect(url_for('payments.view', id=id))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('payments.edit', id=id))
    
    # GET: Populate dropdowns for the edit form
    clients = ClientService.get_all()
    return render_template('payments/form.html', 
                           mode='edit', 
                           payment=payment, 
                           clients=clients)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    """Soft delete the payment."""
    payment = PaymentService.archive(id)
    if payment:
        if payment.invoice:
            payment_number = f'invoice {payment.invoice.invoice_number}'
        elif payment.purchase_order:
            payment_number = f'PO {payment.purchase_order.po_number}'
        else:
            payment_number = f'order {payment.order.order_number}'
        flash(f'Payment for {payment_number} moved to archives.', 'warning')
    else:
        flash(f'Payment not found.', 'error')
    return redirect(url_for('payments.index'))

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """
    Triggered by Client select. 
    Updates: PO List, Paid-From (matches client), resets Invoice, resets Amount.
    """
    client_id = request.args.get('client_id', type=int)
    # Prefill Paid_from with this client
    clients = ClientService.get_all()
    # Populate eligible POs for this client
    pos = PurchaseOrderService.get_eligible_by_client(client_id) if client_id else []
    return render_template('payments/partials/client_cascades.html', 
                           clients=clients, pos=pos, selected_id=client_id)






from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..models import Adjustment
from ..services.adjustments_service import AdjustmentService
from ..services.settings_service import AdjustmentCategoryService
from ..services.attachment_service import AttachmentService
from ..services.audit_service import AuditLogService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.clients_service import ClientService
from ..utils.auth import role_required
from ..utils.docs import generate_doc_number
from ..utils.errors import handle_post_error
from ..extensions import db
from datetime import datetime

bp = Blueprint('adjustments', __name__)

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

    # Record state for the "Back" button
    session['adjustments_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = AdjustmentService.get_all_with_search(search_term=search_term, 
                                                        page=page, 
                                                        per_page=10, 
                                                        sort_by=sort_by, 
                                                        direction=direction)
    
    if request.headers.get('HX-Request'):
        return render_template('adjustments/partials/list.html', pagination=pagination)
    
    return render_template('adjustments/adjustments.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare Data
            data = {
                'description': request.form.get('description'),
                'adjustment_number': request.form.get('adjustment_number'),
                'amount': request.form.get('amount'),
                'adjustment_date': request.form.get('adjustment_date'),
                'category_id': request.form.get('category_id'),
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'note': request.form.get('note')
            }

            # 2. Parse Attachments
            new_files = request.files.getlist('attachments')
            
            # 3. Call Service (handles numbering/parsing)
            new_adjustment = AdjustmentService.add_adjustment(data, new_files=new_files)
            
            flash(f"Adjustment {new_adjustment.adjustment_number} recorded!", "success")
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('adjustments.view', id=new_adjustment.id)
            return response
            
        except Exception as e:
            return handle_post_error(e, "adjustments.add")
        
    # GET: Prepare form data from Client, or PO
    referrer = request.referrer
    # Only use referrer if it's not the 'add' page itself
    cancel_url = url_for('adjustments.index')
    if referrer and url_for('adjustments.add') not in referrer:
        cancel_url = referrer
    
    # Extract all possible shortcut IDs
    client_id = request.args.get('client_id', type=int)
    po_id = request.args.get('po_id', type=int)

    pos = []

    # CASE A: From PO Shortcut
    if po_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        if po and po.is_active:
            client_id = po.client_id
            pos = PurchaseOrderService.get_pos_by_client(client_id,
                                                         statuses=['open', 'invoiced', 'completed'])
    # CASE B: From Client View
    elif client_id:
        client = ClientService.get_by_id(client_id)
        if client and client.is_active:
            pos = PurchaseOrderService.get_pos_by_client(client_id, 
                                                         statuses=['open', 'invoiced', 'completed'])
    
    # GET: Prepare form data for the initial render
    categories = AdjustmentCategoryService.get_all()
    suggested_number = generate_doc_number(prefix='A', model=Adjustment, column_name='adjustment_number')
    clients = ClientService.get_all()

    return render_template('adjustments/form.html', 
                           mode='add', 
                           adjustment=None, 
                           clients=clients, 
                           pos=pos,
                           categories=categories,
                           suggested_number=suggested_number,
                           client_id=client_id,
                           po_id=po_id,
                           cancel_url=cancel_url)

@bp.route('/view/<int:id>')
def view(id):
    adjustment = AdjustmentService.get_by_id(id)
    if not adjustment:
        flash("Adjustment not found.", "error")
        return redirect(url_for('adjustments.index'))
    
    history = AuditLogService.get_for_entity('Adjustment', id)

    return render_template('adjustments/form.html', mode='view', adjustment=adjustment, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    adjustment = AdjustmentService.get_by_id(id)
    if not adjustment:
        flash("Adjustment not found.", "error")
        return redirect(url_for('adjustments.index'))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Update Data
            update_data = {
                'description': request.form.get('description'),
                'adjustment_number': request.form.get('adjustment_number'),
                'amount': request.form.get('amount'),
                'adjustment_date': request.form.get('adjustment_date'),
                'category_id': request.form.get('category_id'),
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'note': request.form.get('note')
            }

            # 2. Parse Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            
            # 3. Call Atomic Service
            AdjustmentService.edit_adjustment(id, update_data, new_files=new_files, delete_ids=delete_ids)

            # 4. Success Feedback
            flash(f"Adjustment {adjustment.adjustment_number} updated successfully!", "success")
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('adjustments.view', id=id)
            return response
        
        except Exception as e:
            return handle_post_error(e, "adjustments.edit")

    # GET: Populate dropdowns
    clients = ClientService.get_all()
    categories = AdjustmentCategoryService.get_all()

    # Use include_id and allow 'completed' projects for historical job costing
    pos = []
    if adjustment.client_id:
        pos = PurchaseOrderService.get_pos_by_client(
            adjustment.client_id, 
            include_id=adjustment.po_id, 
            statuses=['open', 'invoiced', 'completed']
        )

    return render_template('adjustments/form.html', 
                           mode='edit', 
                           adjustment=adjustment, 
                           clients=clients, 
                           pos=pos,
                           categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    try:
        adjustment = AdjustmentService.archive(id)
        if adjustment:
            flash(f'Adjustment {adjustment.adjustment_number} moved to archives.', 'warning')
        else:
            raise ValueError("Adjustment not found.")
        return redirect(url_for('adjustments.index'))
    
    except Exception as e:
        return handle_post_error(e, "adjustments.archive")
    
# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """
    Triggered by Client select. 
    Updates PO list and handles Invoice 'Return Home'.
    """
    # Read data
    adjustment_id = request.args.get('adjustment_id', type=int)
    client_id = request.args.get('client_id', type=int)

    po_id = None # add
    if adjustment_id: # edit
        adjustment = AdjustmentService.get_by_id(adjustment_id)
        po_id = adjustment.po_id if adjustment else None

    # Fetch POs for the selected client
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id,   # includes current po in edit
        statuses=['open', 'invoiced', 'completed']  # includes all POs.
        ) if client_id else []

    return render_template('adjustments/partials/client_cascades.html', 
                           adjustment_id=adjustment_id,   # Add if none else Edit
                           client_id=client_id,     # need for enable/disable dropdown
                           pos=pos)

 

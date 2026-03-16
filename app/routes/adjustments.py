from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..models import Adjustment
from ..services.adjustments_service import AdjustmentService
from ..services.settings_service import AdjustmentCategoryService
from ..services.attachment_service import AttachmentService
from ..services.audit_service import AuditLogService
from ..utils.auth import role_required
from ..utils.docs import generate_doc_number
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
            
        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
    # GET: Prepare form data
    categories = AdjustmentCategoryService.get_all()
    suggested_number = generate_doc_number(prefix='A', model=Adjustment, column_name='adjustment_number')
    return render_template('adjustments/form.html', 
                           mode='add', 
                           adjustment=None, 
                           categories=categories,
                           suggested_number=suggested_number)

@bp.route('/view/<int:id>')
def view(id):
    try:
        adjustment = AdjustmentService.get_by_id(id)
        if not adjustment:
            flash("Adjustment not found.", "error")
            return redirect(url_for('adjustments.index'))
        
        history = AuditLogService.get_for_entity('Adjustment', id)

    except Exception as e:
        flash(f"Error loading adjustment: {str(e)}", "error")
        return redirect(url_for('adjustments.index'))

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
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Populate dropdowns
    categories = AdjustmentCategoryService.get_all()
    return render_template('adjustments/form.html', mode='edit', adjustment=adjustment, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    adjustment = AdjustmentService.archive(id)
    if adjustment:
        flash(f'Adjustment {adjustment.adjustment_number} moved to archives.', 'warning')
    else:
        flash('Adjustment not found.', 'error')
    return redirect(url_for('adjustments.index'))
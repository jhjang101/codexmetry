from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..models import Transaction
from ..services.transactions_service import TransactionService
from ..services.settings_service import TransactionCategoryService
from ..services.attachment_service import AttachmentService
from ..utils.auth import role_required
from ..utils.docs import generate_doc_number
from ..extensions import db
from datetime import datetime

bp = Blueprint('transactions', __name__)

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
    session['transactions_last_url'] = request.full_path

    pagination = TransactionService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('transactions/partials/list.html', pagination=pagination)
    
    return render_template('transactions/transactions.html', pagination=pagination, search=search_term)

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
                'transaction_number': request.form.get('transaction_number'),
                'amount': request.form.get('amount'),
                'transaction_date': request.form.get('transaction_date'),
                'category_id': request.form.get('category_id'),
                'note': request.form.get('note')
            }
            
            # 2. Call Service (handles numbering/parsing)
            new_trx = TransactionService.add_transaction(data)

            # 3. Handle Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Transaction', new_trx.id, new_files=new_files)
            
            flash(f"Transaction {new_trx.transaction_number} recorded!", "success")
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('transactions.view', id=new_trx.id)
            return response
            
        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
    # GET: Prepare form data
    categories = TransactionCategoryService.get_all()
    suggested_number = generate_doc_number(prefix='TRX', model=Transaction, column_name='transaction_number')
    return render_template('transactions/form.html', 
                           mode='add', 
                           trx=None, 
                           categories=categories,
                           suggested_number=suggested_number)

@bp.route('/view/<int:id>')
def view(id):
    try:
        trx = TransactionService.get_by_id(id)
        if not trx:
            flash("Transaction not found.", "error")
            return redirect(url_for('transactions.index'))
    except Exception as e:
        flash(f"Error loading transaction: {str(e)}", "error")
        return redirect(url_for('transactions.index'))

    return render_template('transactions/form.html', mode='view', trx=trx)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    trx = TransactionService.get_by_id(id)
    if not trx:
        flash("Transaction not found.", "error")
        return redirect(url_for('transactions.index'))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Update Data
            update_data = {
                'description': request.form.get('description'),
                'transaction_number': request.form.get('transaction_number'),
                'amount': request.form.get('amount'),
                'transaction_date': request.form.get('transaction_date'),
                'category_id': request.form.get('category_id'),
                'note': request.form.get('note')
            }
            
            # 2. Call Atomic Service
            TransactionService.edit_transaction(id, update_data)

            # 3. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Transaction', id, new_files=new_files, delete_ids=delete_ids)

            # 4. Success Feedback
            flash(f"Transaction {trx.transaction_number} updated successfully!", "success")
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('transactions.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Populate dropdowns
    categories = TransactionCategoryService.get_all()
    return render_template('transactions/form.html', mode='edit', trx=trx, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    trx = TransactionService.archive(id)
    if trx:
        flash(f'Transaction {trx.transaction_number} moved to archives.', 'warning')
    else:
        flash('Transaction not found.', 'error')
    return redirect(url_for('transactions.index'))
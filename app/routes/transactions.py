from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.transactions_service import TransactionService
from ..services.settings_service import TransactionCategoryService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..extensions import db
from datetime import datetime

bp = Blueprint('transactions', __name__)

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

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare Data
            data = {
                'description': request.form.get('description'),
                'amount': request.form.get('amount'),
                'transaction_date': request.form.get('transaction_date'),
                'category_id': request.form.get('category_id'),
                'note': request.form.get('note')
            }
            
            # 2. Call specialized creator (handles numbering/parsing)
            new_trx = TransactionService.create_transaction(data)

            # 3. Handle Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Transaction', new_trx.id, new_files=new_files)
            
            flash(f"Transaction {new_trx.transaction_number} recorded!", "success")
            return redirect(url_for('transactions.index'))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('transactions.add'))
        
    # GET: Prepare form data
    categories = TransactionCategoryService.get_all()
    return render_template('transactions/form.html', mode='add', trx=None, categories=categories)

@bp.route('/view/<int:id>')
def view(id):
    trx = TransactionService.get_by_id(id)
    return render_template('transactions/form.html', mode='view', trx=trx)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    trx = TransactionService.get_by_id(id)
    
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data (Manual date parsing for BaseService compatibility)
            raw_date = request.form.get('transaction_date')
            trx_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else None
            category_id = request.form.get('category_id')
            
            update_data = {
                'description': request.form.get('description', '').strip(),
                'amount': parse_to_cents(str(request.form.get('amount', '0'))),
                'transaction_date': trx_date,
                'category_id': int(category_id) if category_id else None,
                'note': request.form.get('note', '')
            }
            
            # 2. Update via BaseService
            TransactionService.update(id, **update_data)

            # 3. Update Attachments
            new_files = request.files.getlist('attachments')
            delete_ids = [int(fid) for fid in request.form.getlist('delete_ids[]') if fid.isdigit()]
            AttachmentService.commit('Transaction', id, new_files=new_files, delete_ids=delete_ids)

            flash(f"Transaction {trx.transaction_number} updated!", "success")
            return redirect(url_for('transactions.view', id=id))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('transactions.edit', id=id))

    # GET: Populate dropdowns
    categories = TransactionCategoryService.get_all()
    return render_template('transactions/form.html', mode='edit', trx=trx, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    trx = TransactionService.archive(id)
    if trx:
        flash(f'Transaction {trx.transaction_number} moved to archives.', 'warning')
    else:
        flash('Transaction not found.', 'error')
    return redirect(url_for('transactions.index'))
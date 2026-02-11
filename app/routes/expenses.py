from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.expenses_service import ExpenseService
from ..services.vendors_service import VendorService
from ..services.settings_service import ExpenseCategoryService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents
from ..extensions import db
from datetime import datetime
import time

bp = Blueprint('expenses', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # Record state for the "Back" button
    session['expenses_last_url'] = request.full_path

    pagination = ExpenseService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('expenses/partials/list.html', pagination=pagination)
    
    return render_template('expenses/expenses.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data
            expense_data = {
                'vendor_id': request.form.get('vendor_id'),
                'category_id': request.form.get('category_id'),
                'description': request.form.get('description'),
                'expense_date': request.form.get('expense_date'),
                'note': request.form.get('note')
            }
            
            # 2. Create Header (Brain handles numbering)
            new_expense = ExpenseService.create_expense(expense_data)

            # 3. Process and Save Line Items (Strings, not Product IDs)
            items = _parse_items_form(request.form)
            ExpenseService.update_items(new_expense.id, items)

            # 4. Commit Attachments
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Expense', new_expense.id, new_files=new_files)
            
            flash(f"Expense {new_expense.expense_number} recorded successfully!", "success")
            return redirect(url_for('expenses.index'))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('expenses.add'))
        
    # GET: Prepare form data    
    vendors = VendorService.get_all()
    categories = ExpenseCategoryService.get_all()
    initial_row_id = str(int(time.time() * 1000))
    return render_template('expenses/form.html', 
                           mode='add', 
                           expense=None, 
                           vendors=vendors, 
                           categories=categories,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    expense = ExpenseService.get_by_id(id)
    return render_template('expenses/form.html', mode='view', expense=expense)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    expense = ExpenseService.get_by_id(id)
    
    if request.method == 'POST':
        try:
            # 1. Update Header (Manual date parsing for BaseService)
            vendor_id = request.form.get('vendor_id')
            expense_date = request.form.get('expense_date')
            category_id = request.form.get('category_id')

            header_data = {
                'vendor_id': int(vendor_id) if vendor_id else None,
                'category_id': int(category_id) if category_id else None,
                'description': request.form.get('description', '').strip(),
                'expense_date': datetime.strptime(expense_date, '%Y-%m-%d').date() if expense_date else None,
                'note': request.form.get('note', '')
            }
            ExpenseService.update(id, **header_data)

            # 2. Update Line Items
            items = _parse_items_form(request.form)
            ExpenseService.update_items(id, items)

            # 3. Update Attachments
            new_files = request.files.getlist('attachments')
            delete_ids = [int(fid) for fid in request.form.getlist('delete_ids[]') if fid.isdigit()]
            AttachmentService.commit('Expense', id, new_files=new_files, delete_ids=delete_ids)

            flash(f"Expense {expense.expense_number} updated successfully!", "success")
            return redirect(url_for('expenses.view', id=id))
            
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('expenses.edit', id=id))

    # GET: Populate dropdowns
    vendors = VendorService.get_all()
    categories = ExpenseCategoryService.get_all()
    return render_template('expenses/form.html', 
                           mode='edit', 
                           expense=expense, 
                           vendors=vendors, 
                           categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    expense = ExpenseService.archive(id)
    if expense:
        flash(f'Expense {expense.expense_number} moved to archives.', 'warning')
    else:
        flash('Expense not found.', 'error')
    return redirect(url_for('expenses.index'))

# --- HTMX Item-row and Calculation Routes ---

@bp.route('/add-row')
def add_row():
    """Returns a blank manual item row."""
    row_id = str(int(time.time() * 1000))
    return render_template('expenses/partials/item_row.html',
                           row_id=row_id, 
                           item=None, 
                           mode='add')

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates specific Line Total and Grand Total."""
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    line_total = 0
    grand_total = 0

    for r_id, qty, price in zip(row_ids, quantities, unit_prices):
        q = int(qty) if qty else 0
        p = parse_to_cents(price)
        row_total = q * p
        grand_total += row_total
        
        if r_id == row_id:
            line_total = row_total

    return render_template('expenses/partials/calculation_result.html', 
                           row_id=row_id,
                           line_total=line_total, 
                           grand_total=grand_total)

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists into a list of dicts. 'item' is a string."""
    items_list = form_data.getlist('items[]') # The text description
    quantities = form_data.getlist('quantities[]')
    unit_prices = form_data.getlist('unit_prices[]')
    
    parsed = []
    for item_text, qty, price in zip(items_list, quantities, unit_prices):
        if item_text:
            parsed.append({
                'item': item_text.strip(),
                'quantity': int(qty) if qty else 1,
                'unit_price': price # Service handles parse_to_cents
            })
    return parsed
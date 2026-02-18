from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from ..services.expenses_service import ExpenseService
from ..services.vendors_service import VendorService
from ..services.settings_service import ExpenseCategoryService
from ..services.attachment_service import AttachmentService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.invoices_service import InvoiceService
from ..services.clients_service import ClientService
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
            # 1. Extract Header Data
            header_data = {
                'vendor_id': request.form.get('vendor_id'),
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'category_id': request.form.get('category_id'),
                'description': request.form.get('description'), # Might be empty, Brain handles fallback
                'expense_date': request.form.get('expense_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }
            
            # 2. Extract and Parse Items
            # This helper converts the parallel lists into a list of dictionaries
            items = _parse_items_form(request.form)
            
            # 3. Call the Atomic Service method
            # This handles numbering, fallback logic, and line item saving
            new_expense = ExpenseService.add_expense(header_data, items)

            # 4. Handle Attachments
            # We call this after the service returns the saved expense object
            new_files = request.files.getlist('attachments')
            AttachmentService.commit('Expense', new_expense.id, new_files=new_files)
            
            # 5. Success Feedback
            flash(f"Expense {new_expense.expense_number} recorded successfully!", "success")
            return redirect(url_for('expenses.index'))
            
        except ValueError as e:
            # Rollback any partial database state (like the CDX registry increment)
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('expenses.add'))
        
    # GET: Prepare form data for the initial render
    vendors = VendorService.get_all()
    categories = ExpenseCategoryService.get_all()
    clients = ClientService.get_all()
    # Generate a unique timestamp for the first dynamic row
    initial_row_id = str(int(time.time() * 1000))
    
    return render_template('expenses/form.html', 
                           mode='add', 
                           expense=None, 
                           vendors=vendors, 
                           clients=clients, 
                           categories=categories,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    try:
        expense = ExpenseService.get_by_id(id)
        if not expense:
            flash("Expense not found.", "error")
            return redirect(url_for('expenses.index'))
    except Exception as e:
        flash(f"Error loading expense: {str(e)}", "error")
        return redirect(url_for('expenses.index'))

    return render_template('expenses/form.html', mode='view', expense=expense)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    expense = ExpenseService.get_by_id(id)
    if not expense:
        flash("Expense not found.", "error")
        return redirect(url_for('expenses.index'))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data
            header_data = {
                'vendor_id': request.form.get('vendor_id'),
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'category_id': request.form.get('category_id'),
                'description': request.form.get('description'),
                'expense_date': request.form.get('expense_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }

            # 2. Parse Items
            items = _parse_items_form(request.form)

            # 3. Call Atomic Service
            ExpenseService.edit_expense(id, header_data, items)

            # 4. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]
            AttachmentService.commit('Expense', id, new_files=new_files, delete_ids=delete_ids)

            flash(f"Expense {expense.expense_number} updated successfully!", "success")
            return redirect(url_for('expenses.view', id=id))
            
        except ValueError as e:
            # Rollback to prevent partial updates
            db.session.rollback()
            flash(str(e), "error")
            return redirect(url_for('expenses.edit', id=id))

    # GET: Populate dropdowns for the edit form
    vendors = VendorService.get_all()
    categories = ExpenseCategoryService.get_all()
    clients = ClientService.get_all()

    # Brain: Use include_id and allow 'completed' projects for historical job costing
    pos = []
    invoices = []
    if expense.client_id:
        pos = PurchaseOrderService.get_pos_by_client(
            expense.client_id, 
            include_id=expense.po_id, 
            statuses=['open', 'completed']
        )
    if expense.po_id:
        invoices = InvoiceService.get_invoices_by_po(
            expense.po_id, 
            include_id=expense.invoice_id, 
            statuses=['open', 'completed']
        )

    return render_template('expenses/form.html', 
                           mode='edit', 
                           expense=expense, 
                           vendors=vendors, 
                           categories=categories,
                           clients=clients,
                           pos=pos,
                           invoices=invoices)

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

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """
    Triggered by Client select. 
    Updates PO list and handles Invoice 'Return Home'.
    """
    client_id = request.args.get('client_id', type=int)
    expense_id = request.args.get('expense_id', type=int)
    expense = ExpenseService.get_by_id(expense_id) if expense_id else None

    # 1. Fetch POs for the selected client
    po_id = expense.po_id if expense else None
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id,
        statuses=['open', 'completed']
    ) if client_id else []

    # 2. SMART RETURN: If switching back to the original client, fetch original invoices
    invoices = []
    if expense and client_id == expense.client_id:
        invoices = InvoiceService.get_invoices_by_po(
            expense.po_id, 
            include_id=expense.invoice_id,
            statuses=['open', 'completed']
        )

    return render_template('expenses/partials/client_cascades.html', 
                           pos=pos, 
                           invoices=invoices,
                           selected_id=client_id, 
                           expense=expense)

@bp.route('/update-po-cascades')
def update_po_cascades():
    """
    Triggered by PO slelct.
    Updates: Invoice List 
    """
    po_id = request.args.get('po_id', type=int)
    expense_id = request.args.get('expense_id', type=int)
    expense = ExpenseService.get_by_id(expense_id) if expense_id else None

    # We need the parent client_id to keep the PO dropdown enabled in the partial
    # The po_id comes from the select, so we look up that PO to find its client
    po = PurchaseOrderService.get_by_id(po_id) if po_id else None

    # Populate eligible Invoices for this PO
    invoices = InvoiceService.get_invoices_by_po(
        po_id, 
        include_id=expense.invoice_id if expense else None,
        statuses=['open', 'completed']
    ) if po_id else []

    # Pass client_id from the PO
    po_client_id = po.client_id if po else None


    return render_template('expenses/partials/po_cascades.html', 
                           invoices=invoices, 
                           selected_po_id=po_id, 
                           selected_id=po_client_id,
                           expense=expense)

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists into a list of dicts. 'item' is a string."""
    items_list = form_data.getlist('items[]') # The text description
    quantities = form_data.getlist('quantities[]')
    unit_prices = form_data.getlist('unit_prices[]')
    catalog_numbers = form_data.getlist('catalog_numbers[]')
    descriptions = form_data.getlist('descriptions[]')
    
    parsed = []
    for item_text, qty, price, catalog_number, description in zip(items_list, quantities, unit_prices, catalog_numbers, descriptions):
        if item_text:
            parsed.append({
                'item': item_text.strip(),
                'quantity': int(qty) if qty else 1,
                'unit_price': price, # Service handles parse_to_cents
                'catalog_number': catalog_number.strip() if catalog_number else '',
                'description': description.strip() if description else ''
            })
    return parsed
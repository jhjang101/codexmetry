from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..models import Expense
from ..services.expenses_service import ExpenseService
from ..services.vendors_service import VendorService
from ..services.settings_service import ExpenseCategoryService
from ..services.attachment_service import AttachmentService
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.invoices_service import InvoiceService
from ..services.clients_service import ClientService
from ..services.audit_service import AuditLogService
from ..services.orders_service import OrderService
from ..utils.money import parse_to_cents
from ..utils.auth import role_required
from ..utils.docs import generate_doc_number
from ..extensions import db
from datetime import datetime
import time

bp = Blueprint('expenses', __name__)

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
    session['expenses_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'date')
    direction = request.args.get('dir', 'desc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ExpenseService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)
    
    if request.headers.get('HX-Request'):
        return render_template('expenses/partials/list.html', pagination=pagination)
    
    return render_template('expenses/expenses.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Extract Header Data
            header_data = {
                'vendor_id': request.form.get('vendor_id'),
                'expense_number': request.form.get('expense_number'),
                'po_id': request.form.get('po_id'),
                'client_id': request.form.get('client_id'),
                'po_id': request.form.get('po_id'),
                'invoice_id': request.form.get('invoice_id'),
                'category_id': request.form.get('category_id'),
                'description': request.form.get('description'), # Might be empty, Brain handles fallback
                'expense_date': request.form.get('expense_date'),
                'status': request.form.get('status'),
                'note': request.form.get('note')
            }

            print('client_id:', header_data.get('client_id'))
        
            
            # 2. Extract and Parse Items
            # This helper converts the parallel lists into a list of dictionaries
            items = _parse_items_form(request.form)
            
            # 3. Parse Attachments
            new_files = request.files.getlist('attachments')

            # 4. Call the Atomic Service method
            # This handles numbering, fallback logic, line item saving, and attachments saving.
            new_expense = ExpenseService.add_expense(header_data, items, new_files=new_files)
            
            # 5. Success Feedback
            flash(f"Expense {new_expense.expense_number} recorded successfully!", "success")
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('expenses.view', id=new_expense.id)
            return response
            
        except ValueError as e:
            # Rollback any partial database state (like the CDX registry increment)
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp
        
    # GET: Prepare form data from Client, Vendor, PO, or Invoice
    referrer = request.referrer
    # Only use referrer if it's not the 'add' page itself
    cancel_url = url_for('expenses.index')
    if referrer and url_for('expenses.add') not in referrer:
        cancel_url = referrer

    # Extract all possible shortcut IDs
    client_id = request.args.get('client_id', type=int)
    po_id = request.args.get('po_id', type=int)
    invoice_id = request.args.get('invoice_id', type=int)
    vendor_id = request.args.get('vendor_id', type=int)


    pos = []
    invoices = []

    # CASE A: From Invoice Shortcut
    if invoice_id:
        invoice = InvoiceService.get_invoice_by_id(invoice_id)
        if invoice and invoice.is_active:
            client_id = invoice.client_id
            po_id = invoice.po_id
            # Hydrate lists so dropdowns are ready
            pos = PurchaseOrderService.get_pos_by_client(client_id, include_id=po_id, statuses=['open', 'invoiced', 'completed'])
            invoices = InvoiceService.get_invoices_by_po(po_id, include_id=invoice_id, statuses=['draft', 'open', 'completed'])

    # CASE B: From PO Shortcut
    elif po_id:
        po = PurchaseOrderService.get_po_by_id(po_id)
        if po and po.is_active:
            client_id = po.client_id
            pos = PurchaseOrderService.get_pos_by_client(client_id, include_id=po_id, statuses=['open', 'invoiced', 'completed'])
            invoices = InvoiceService.get_invoices_by_po(po_id, statuses=['draft', 'open', 'completed'])

    # CASE C: From Client View
    elif client_id:
        client = ClientService.get_by_id(client_id)
        if client and client.is_active:
            pos = PurchaseOrderService.get_pos_by_client(client_id, statuses=['open', 'invoiced', 'completed'])

    # CASE D: From Vendor View
    elif vendor_id:
        vendor = VendorService.get_by_id(vendor_id)
        if not vendor or not vendor.is_active:
            flash("Vendor not found or archived.", "error")
            return redirect(url_for('expenses.index'))
        # client_id remains None, no deal context pre-filled
    
    # GET: Prepare form data for the initial render
    vendors = VendorService.get_all()
    suggested_number = generate_doc_number(prefix='EPX', model=Expense, column_name='expense_number')
    categories = ExpenseCategoryService.get_all()
    clients = ClientService.get_all()
    # Generate a unique timestamp for the first dynamic row
    initial_row_id = str(int(time.time() * 1000))
    
    return render_template('expenses/form.html', 
                           mode='add', 
                           expense=None, 
                           vendors=vendors, 
                           clients=clients, 
                           pos=pos,
                           invoices=invoices,
                           suggested_number=suggested_number,
                           client_id=client_id,
                           po_id=po_id,
                           invoice_id=invoice_id,
                           vendor_id=vendor_id,
                           categories=categories,
                           timestamp=initial_row_id,
                           cancel_url=cancel_url)

@bp.route('/view/<int:id>')
def view(id):
    try:
        expense = ExpenseService.get_expense_by_id(id)
        if not expense:
            flash("Expense not found.", "error")
            return redirect(url_for('expenses.index'))
        
        tree = OrderService.get_deal_tree(expense.order_id)
        history = AuditLogService.get_for_entity('Expense', id)

    except Exception as e:
        flash(f"Error loading expense: {str(e)}", "error")
        return redirect(url_for('expenses.index'))

    return render_template('expenses/form.html', mode='view', expense=expense, tree=tree, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    expense = ExpenseService.get_expense_by_id(id)
    if not expense:
        flash("Expense not found.", "error")
        return redirect(url_for('expenses.index'))
    
    if request.method == 'POST':
        try:
            # 1. Prepare Header Data
            header_data = {
                'vendor_id': request.form.get('vendor_id'),
                'expense_number': request.form.get('expense_number'),
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

            # 3. Update Attachments
            new_files = request.files.getlist('attachments')
            raw_delete_ids = request.form.getlist('delete_ids[]') 
            delete_ids = [int(fid) for fid in raw_delete_ids if fid.isdigit()]

            # 4. Call Atomic Service
            ExpenseService.edit_expense(id, header_data, items, new_files=new_files, delete_ids=delete_ids)

            flash(f"Expense {expense.expense_number} updated successfully!", "success")
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('expenses.view', id=id)
            return response
            
        except ValueError as e:
            # Rollback to prevent partial updates
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

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
            statuses=['open', 'invoiced', 'completed']
        )
    if expense.po_id:
        invoices = InvoiceService.get_invoices_by_po(
            expense.po_id, 
            include_id=expense.invoice_id, 
            statuses=['draft', 'open', 'completed']
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
@role_required(['admin']) # Only Admin can delete
def archive(id):
    expense = ExpenseService.archive(id)
    if expense:
        flash(f'Expense {expense.expense_number} moved to archives.', 'warning')
    else:
        flash('Expense not found.', 'error')
    return redirect(url_for('expenses.index'))
    
# --- PRINT ---

@bp.route('/print/<int:id>')
@login_required
def print_view(id):
    """
    Messenger: Fetches hydrated Invoice data for the printable layout.
    Metadata is already injected via global context processor.
    """
    # 1. Fetch hydrated expense using the Service Brain
    expense = ExpenseService.get_expense_by_id(id)
    
    if not expense or not expense.is_active:
        flash("Expense record not found.", "error")
        return redirect(url_for('expenses.index'))

    # 2. Calculate Subtotal (In-Memory)
    subtotal = sum(item.quantity * item.unit_price for item in expense.items)

    # 3. Render the dedicated print template
    return render_template('expenses/print.html', 
                           expense=expense, 
                           subtotal=subtotal)

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
    try:
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
    
    except ValueError as e:
        # Failure: Rollback (Safety first) and OOB Error
        db.session.rollback()
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        # Tell HTMX not to clear the total or the input that caused the error
        resp.headers['HX-Reswap'] = 'none'
        return resp

# --- HTMX CASCADE ROUTES ---

@bp.route('/update-client-cascades')
def update_client_cascades():
    """
    Triggered by Client select. 
    Updates PO list and handles Invoice 'Return Home'.
    """
    # Read data
    expense_id = request.args.get('expense_id', type=int)
    client_id = request.args.get('client_id', type=int)

    po_id = None # add
    if expense_id: # edit
        expense = ExpenseService.get_expense_by_id(expense_id)
        po_id = expense.po_id if expense else None

    # Fetch POs for the selected client
    pos = PurchaseOrderService.get_pos_by_client(
        client_id, 
        include_id=po_id,   # includes current po in edit
        statuses=['open', 'invoiced', 'completed']  # includes all POs.
    ) if client_id else []

    return render_template('expenses/partials/client_cascades.html', 
                           expense_id=expense_id,   # Add if none else Edit
                           client_id=client_id,     # need for enable/disable dropdown
                           pos=pos)

@bp.route('/update-po-cascades')
def update_po_cascades():
    """
    Triggered by PO slelct.
    Updates: Invoice List 
    """
    # Read data
    expense_id = request.args.get('expense_id', type=int)
    po_id = request.args.get('po_id', type=int)

    # Get current invoice_id
    invoice_id = None # add
    if expense_id: # edit
        expense = ExpenseService.get_by_id(expense_id)
        invoice_id = expense.invoice_id if expense.invoice_id else None

    # Populate eligible Invoices for this PO
    invoices = InvoiceService.get_invoices_by_po(
        po_id, 
        include_id=invoice_id,          # includes current invoice in edit
        statuses=['draft', 'open', 'completed']  # includes all POs.
    ) if po_id else []

    return render_template('expenses/partials/po_cascades.html',
                           expense_id=expense_id,   # Add if none else Edit
                           po_id=po_id,             # need for enable/disable dropdown
                           invoices=invoices)


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
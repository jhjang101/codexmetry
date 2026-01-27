from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.purchase_orders_service import PurchaseOrderService
from ..services.products_service import ProductService
from ..services.clients_service import ClientService
from ..services.settings_service import PoTypeService
from ..services.attachment_service import AttachmentService
from ..utils.money import parse_to_cents, format_usd
from datetime import datetime
import time 

bp = Blueprint('purchase_orders', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['purchase_orders_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = PurchaseOrderService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('purchase_orders/partials/list.html', pagination=pagination)
    
    return render_template('purchase_orders/purchase_orders.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Extract and Transform
        client_id = request.form.get('client_id')
        po_number = request.form.get('po_number', '') # Client Reference
        bill_to_id = request.form.get('bill_to_id')
        po_date = request.form.get('po_date')
        po_type_id = request.form.get('po_type_id')
        note = request.form.get('note')

        po_data = {
            'client_id': int(client_id) if client_id else None,
            'po_number': po_number, 
            'bill_to_id': int(bill_to_id) if bill_to_id else int(client_id) if client_id else None,
            'po_date': datetime.strptime(po_date, '%Y-%m-%d').date() if po_date else None,
            'po_type_id': int(po_type_id) if po_type_id else None,
            'note': note
        }

        # 2. Save PurchaseOrder
        new_po = PurchaseOrderService.create_with_registry(po_data)

        # 3. Process and Save Line Items
        items = _parse_items_form(request.form)
        PurchaseOrderService.update_items(new_po.id, items)

        # 4. COMMIT ATTACHMENTS
        new_files = request.files.getlist('attachments')
        # We call commit with an empty delete list because it's a new quote
        AttachmentService.commit('PurchaseOrder', new_po.id, new_files=new_files)

        flash(f'PO {new_po.po_number} added successfully!', 'success')
        return redirect(url_for('purchase_orders.index'))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all()
    po_types = PoTypeService.get_all()
    initial_row_id = str(int(time.time() * 1000))   
    return render_template('purchase_orders/form.html', 
                           mode='add', 
                           po=None, 
                           clients=clients, 
                           products=products,
                           po_types=po_types,
                           timestamp=initial_row_id)

@bp.route('/view/<int:id>')
def view(id):
    po = PurchaseOrderService.get_by_id(id)
    return render_template('purchase_orders/form.html', mode='view', po=po)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    po = PurchaseOrderService.get_by_id(id)
    if request.method == 'POST':
        # 1. Extract and Transform
        client_id = request.form.get('client_id')
        po_number = request.form.get('po_number', '')
        bill_to_id = request.form.get('bill_to_id')
        po_date = request.form.get('po_date')
        po_type_id = request.form.get('po_type_id')
        note = request.form.get('note')
        status = request.form.get('status')

        po_data = {
            'client_id': int(client_id) if client_id else None,
            'po_number': po_number, 
            'bill_to_id': int(bill_to_id) if bill_to_id else int(client_id) if client_id else None,
            'po_date': datetime.strptime(po_date, '%Y-%m-%d').date() if po_date else None,
            'po_type_id': int(po_type_id) if po_type_id else None,
            'note': note,
            'status': status
        }

        # 2. Update Header
        PurchaseOrderService.update(id, **po_data)

        # 3. Update Line Items
        items = _parse_items_form(request.form)
        PurchaseOrderService.update_items(id, items)

        # 4. Commit Attachments (Handle new and marked for delete)
        new_files = request.files.getlist('attachments')
        delete_ids = [int(fid) for fid in request.form.getlist('delete_ids[]') if fid.isdigit()]
        AttachmentService.commit('PurchaseOrder', id, new_files=new_files, delete_ids=delete_ids)

        flash(f'PO {po.po_number} updated successfully!', 'success')
        return redirect(url_for('purchase_orders.view', id=id))

    # GET: Prepare form data
    clients = ClientService.get_all()
    products = ProductService.get_all()
    po_types = PoTypeService.get_all()
    return render_template('purchase_orders/form.html', 
                           mode='edit', 
                           po=po, 
                           clients=clients, 
                           products=products,
                           po_types=po_types)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    po = PurchaseOrderService.archive(id)
    if po:
        flash(f'PO {po.po_number} has been moved to archives.', 'warning')
    else:
        flash('PO not found.', 'error')
    return redirect(url_for('purchase_orders.index'))

# --- HTMX CALCULATION ROUTES ---

@bp.route('/add-row')
def add_row():
    """Returns a blank product row for the dynamic sub-form."""
    products = ProductService.get_all()
    # Generate a unique row_id based on a timestamp
    row_id = str(int(time.time() * 1000))
    return render_template('purchase_orders/partials/item_row.html',
                           products=products, 
                           row_id=row_id, 
                           item=None, 
                           mode='add')

@bp.route('/get-unit-price')
def get_unit_price():
    """Returns the default_unit_price for the selected product."""
    raw_pid = request.args.get('product_ids[]')
    row_id = request.args.get('row_id')

    product_id = int(raw_pid) if raw_pid and raw_pid.strip() else None

    # Query product for its default price
    product = ProductService.get_by_id(product_id)
    default_unit_price = product.default_unit_price if product else 0

    return render_template('purchase_orders/partials/unit_price_input.html',
                           row_id=row_id,
                           price=default_unit_price)

@bp.route('/calculate', methods=['POST'])
def calculate():
    """Calculates the specific Line Total and the global Grand Total."""
    row_id = request.form.get('row_id')
    row_ids = request.form.getlist('row_ids[]')
    quantities = request.form.getlist('quantities[]')
    unit_prices = request.form.getlist('unit_prices[]')

    line_total = 0
    grand_total = 0

    # If this is the row the user is currently editing, capture its total
    if row_id in row_ids:
        idx = row_ids.index(row_id)
        line_total = int(quantities[idx]) * parse_to_cents(unit_prices[idx])

    # calculate grand total
    items = [{'qty': q, 'price': p} for q, p in zip(quantities, unit_prices)]
    for item in items:
        qty = int(item['qty'])
        price = parse_to_cents(item['price'])
        grand_total += qty * price

    return render_template('purchase_orders/partials/calculation_result.html', 
                           row_id=row_id,
                           line_total=line_total, 
                           grand_total=grand_total)

# --- INTERNAL HELPERS ---

def _parse_items_form(form_data):
    """Parses parallel lists from form into a list of dictionaries."""
    product_ids = form_data.getlist('product_ids[]')
    quantities = form_data.getlist('quantities[]')
    unit_prices = form_data.getlist('unit_prices[]')
    
    items = []
    for pid, q, p in zip(product_ids, quantities, unit_prices):
        if pid:
            items.append({
                'product_id': int(pid),
                'quantity': int(q) if q else 1,
                'unit_price': parse_to_cents(p)
            })
    return items
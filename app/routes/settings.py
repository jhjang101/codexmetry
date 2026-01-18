from flask import Blueprint, render_template, request, redirect, url_for
from ..services.settings_service import (
    MetadataService as Metadata,
    PoTypeService as PoType,
    ProductCategoryService as ProductCategory, 
    ExpenseCategoryService as ExpenseCategory, 
    PaymentTypeService as PaymentType, 
    TransactionCategoryService as TransactionCategory
)
from ..utils.money import parse_to_cents


LOOKUPS = {
    'po_types': PoType,
    'product_categories': ProductCategory,
    'expense_categories': ExpenseCategory,
    'payment_types': PaymentType,
    'transaction_categories': TransactionCategory
}

bp = Blueprint('settings', __name__)

@bp.route('/')
def index():
    # Metadata is injected in @app.context_processor decorator
    lookups = {}
    for name, service in LOOKUPS.items():
        lookups[name] = service.get_all()
        
    return render_template('settings/settings.html', lookups=lookups)

# Route to update metadata
@bp.route('/metadata/update', methods=['POST'])
def update_metadata():
    print("update_metadata")
    metadata = {
        'company_name': request.form.get('company_name'),
        'address': request.form.get('address'),
        'timezone': request.form.get('timezone'),
        'invoice_threshold': parse_to_cents(request.form.get('threshold', '$100.00')),
        'doc_padding': int(request.form.get('doc_padding', 4))
    }
    
    # TDDO: Image Logic Implementation

    Metadata.update(1, **metadata)

    return redirect(url_for('settings.index'))

# HTMX Route to add a lookup item
@bp.route('/lookup/add', methods=['POST'])
def add_lookup():
    table_name = request.form.get('table_name')
    value = request.form.get('value')
    if table_name:
        table = LOOKUPS.get(table_name)

    if table and value:
        table.add(type=value)
        items = table.get_all()

    return render_template('settings/partials/lookup_card.html', 
                           table_name=table_name, 
                           items = items)

# HTMX Route to archive a lookup item
@bp.route('/lookup/archive/<table_name>/<int:id>', methods=['POST'])
def archive_lookup(table_name, id):
    table = LOOKUPS.get(table_name)
    if table:
        table.archive(id)

    return "" # HTMX will remove the row if we handle it, or we can just redirect
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from ..services.settings_service import (
    MetadataService,
    PoTypeService,
    ProductCategoryService, 
    ExpenseCategoryService, 
    PaymentTypeService, 
    TransactionCategoryService
)
from ..utils.images import save_image
from ..utils.money import parse_to_cents


LOOKUPS = {
    'po_types': PoTypeService,
    'product_categories': ProductCategoryService,
    'expense_categories': ExpenseCategoryService,
    'payment_types': PaymentTypeService,
    'transaction_categories': TransactionCategoryService
}

bp = Blueprint('settings', __name__)

@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

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
    metadata = {
        'company_name': request.form.get('company_name'),
        'address': request.form.get('address'),
        'timezone': request.form.get('timezone'),
        'invoice_threshold': parse_to_cents(request.form.get('threshold', '$100.00')),
        'doc_padding': int(request.form.get('doc_padding', 4))
    }
    
    # Image Logic Implementation
    new_logo = request.files.get('logo')
    if new_logo:
        new_filename = save_image(
            file=new_logo, 
            subfolder='logos', 
            old_filename=request.form.get('old_image')
        )
        if new_filename:
            metadata['company_logo'] = new_filename

    MetadataService.update(1, **metadata)
    flash('Metadata updated successfully!', 'success')

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
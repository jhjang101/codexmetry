from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from ..services.users_service import UserService
from ..utils.auth import role_required
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

@bp.before_request
@login_required
@role_required(['admin']) # Only admins can enter any route in this file
def before_request():
    """Protect all routes within this blueprint."""
    pass

@bp.route('/')
def index():
    # Metadata is injected in @app.context_processor decorator
    lookups = {}
    for name, service in LOOKUPS.items():
        lookups[name] = service.get_all()

    users = UserService.get_all()
        
    return render_template('settings/settings.html', lookups=lookups, users=users)

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

# --- USER MANAGEMENT HTMX ROUTES ---

@bp.route('/users/add', methods=['POST'])
def add_user():
    """Messenger: Handles new user creation and returns updated table."""
    try:
        data = request.form.to_dict()
        UserService.add_user(data)
        
        # Return the full table partial to show the new user
        users = UserService.get_all()
        return render_template('settings/partials/user_table.html', users=users)
    
    except ValueError as e:
        # Return our pulse-red error banner via OOB swap
        return render_template('partials/error_notification.html', message=str(e)), 200

@bp.route('/users/edit/<int:id>', methods=['GET'])
def edit_user_row(id):
    """Messenger: Returns an inline 'Edit' row for the user table."""
    user = UserService.get_by_id(id)
    return render_template('settings/partials/user_row_edit.html', user=user)

@bp.route('/users/update/<int:id>', methods=['POST'])
def update_user(id):
    """Messenger: Saves user changes and returns to 'View' row."""
    try:
        data = request.form.to_dict()
        UserService.update_user(id, data)
        
        # Return the read-only row partial
        user = UserService.get_by_id(id)
        return render_template('settings/partials/user_row_view.html', user=user)
    
    except ValueError as e:
        return render_template('partials/error_notification.html', message=str(e)), 200

@bp.route('/users/toggle/<int:id>', methods=['POST'])
def toggle_user_status(id):
    """Messenger: Flips is_active status and returns updated row."""
    try:
        user = UserService.toggle_status(id)
        return render_template('settings/partials/user_row_view.html', user=user)
    except ValueError as e:
        return render_template('partials/error_notification.html', message=str(e)), 200

# --- HTMX Route to add a lookup item ---
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

# --- HTMX Route to archive a lookup item ---
@bp.route('/lookup/archive/<table_name>/<int:id>', methods=['POST'])
def archive_lookup(table_name, id):
    table = LOOKUPS.get(table_name)
    if table:
        table.archive(id)

    return "" # HTMX will remove the row if we handle it, or we can just 


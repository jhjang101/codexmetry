from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response
from flask_login import login_required
from ..extensions import db
from ..services.users_service import UserService
from ..utils.auth import role_required
from ..services.settings_service import (
    MetadataService,
    PoTypeService,
    ProductCategoryService, 
    ExpenseCategoryService, 
    PaymentTypeService, 
    AdjustmentCategoryService
)
from ..utils.images import save_image
from ..utils.money import parse_to_cents


LOOKUPS = {
    'po_types': PoTypeService,
    'product_categories': ProductCategoryService,
    'expense_categories': ExpenseCategoryService,
    'payment_types': PaymentTypeService,
    'adjustment_categories': AdjustmentCategoryService
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
    """
    Messenger: Orchestrates the global settings update.
    Handles image persistence and delegates logic to MetadataService.
    """
    try:
        # 1. Prepare raw data dictionary from form
        data = {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address'),
            'timezone': request.form.get('timezone'),
            'invoice_threshold': request.form.get('threshold'), # Raw string, Service handles parsing
            'doc_padding': request.form.get('doc_padding')
        }
        
        # 2. Specialized Image Handling (The Messenger manages files)
        new_logo = request.files.get('logo')
        if new_logo and new_logo.filename != '':
            new_filename = save_image(
                file=new_logo, 
                subfolder='logos', 
                old_filename=request.form.get('old_image')
            )
            if new_filename:
                data['company_logo'] = new_filename

        # 3. Brain Call: Validation and Database Commit
        MetadataService.update_metadata(data)
        
        flash('Metadata updated successfully!', 'success')

        # 4. Standardize for HTMX redirects
        response = make_response("", 200)
        response.headers['HX-Redirect'] = url_for('settings.index')
        return response

    except ValueError as e:
        # 5. Logic Failure Flow: Rollback and OOB Error
        db.session.rollback()
        # We return the error partial (OOB) and tell HTMX NOT to swap the form
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp

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
        db.session.rollback()
        # 1. Prepare the error fragment
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        # 2. BRAIN: Tell HTMX NOT to swap the primary target (the table)
        # This preserves the data already typed into the form rows
        resp.headers['HX-Reswap'] = 'none'
        return resp

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
        db.session.rollback()
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp

@bp.route('/users/toggle/<int:id>', methods=['POST'])
def toggle_user_status(id):
    """Messenger: Flips is_active status and returns updated row."""
    try:
        user = UserService.toggle_status(id)
        return render_template('settings/partials/user_row_view.html', user=user)
    except ValueError as e:
        db.session.rollback()
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp
    
@bp.route('/users/row/<int:id>', methods=['GET'])
def view_user_row(id):
    """Messenger: Returns a read-only 'View' row for the user table (used for Cancel)."""
    user = UserService.get_by_id(id)
    return render_template('settings/partials/user_row_view.html', user=user)

# --- HTMX Route to add a lookup item ---
@bp.route('/lookup/add', methods=['POST'])
def add_lookup():
    """Adds a lookup value and returns the updated card."""
    try:
        table_name = request.form.get('table_name')
        value = request.form.get('value', '').strip()
        
        if not table_name:
            raise ValueError("Target table not specified.")
        
        table = LOOKUPS.get(table_name)
        if not table:
            raise ValueError("Invalid lookup table.")

        if not value:
            raise ValueError("Value cannot be empty.")

        # Brain Call: Add to database
        table.add(type=value)
        
        # Success: Return the updated card partial
        items = table.get_all()
        return render_template('settings/partials/lookup_card.html', 
                               table_name=table_name, 
                               items=items)

    except ValueError as e:
        db.session.rollback()
        # Failure: Return OOB Error and keep the "Add" input intact
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp

# --- HTMX Route to archive a lookup item ---
@bp.route('/lookup/archive/<table_name>/<int:id>', methods=['POST'])
def archive_lookup(table_name, id):
    """Archives a lookup value."""
    try:
        table = LOOKUPS.get(table_name)
        if not table:
            raise ValueError("Invalid lookup table.")

        # Archive record
        table.archive(id)

        # Success: HTMX will remove the row on the frontend because we return empty
        return "" 

    except ValueError as e:
        db.session.rollback()
        # Failure: Return OOB Error and prevent the row from disappearing
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp


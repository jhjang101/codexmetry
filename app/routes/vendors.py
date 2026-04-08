from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.vendors_service import VendorService
from ..services.audit_service import AuditLogService
from ..utils.auth import role_required
from ..utils.errors import handle_post_error
from ..extensions import db

bp = Blueprint('vendors', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main directory for Vendors module."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE
    session['vendors_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = VendorService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)


    if request.headers.get('HX-Request'):
        return render_template('vendors/partials/list.html', pagination=pagination)
    
    return render_template('vendors/vendors.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare data
            vendor_data = {
                'company_name': request.form.get('company_name'),
                'url': request.form.get('url'),
                'address': request.form.get('address')
            }
            contacts_data = _parse_contact_form(request.form)

            # 2. Call Service
            new_vendor = VendorService.add_vendor(vendor_data, contacts_data)

            # 3. Success Feedback
            flash(f'Vendor {new_vendor.company_name} created successfully!', 'success')
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('vendors.view', id=new_vendor.id)
            return response

        except Exception as e:
            return handle_post_error(e, "vendors.add")

    return render_template('vendors/form.html', mode='add', vendor=None)

@bp.route('/view/<int:id>')
def view(id):
    vendor = VendorService.get_by_id(id)
    if not vendor:
        flash("Vendor not found.", "error")
        return redirect(url_for('vendors.index'))
    
    history = AuditLogService.get_for_entity('Vendor', id)
    
    return render_template('vendors/form.html', mode='view', vendor=vendor, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    vendor = VendorService.get_by_id(id)
    if not vendor:
        flash("Vendor not found.", "error")
        return redirect(url_for('vendors.index'))

    if request.method == 'POST':
        try:
            # 1. Prepare data
            vendor_data = {
                'company_name': request.form.get('company_name'),
                'url': request.form.get('url'),
                'address': request.form.get('address')
            }
            contacts = _parse_contact_form(request.form)

            # 2. Call Service
            VendorService.edit_vendor(id, vendor_data, contacts)

            # 3. Success Feedback
            flash(f'Vendor {vendor.company_name} updated successfully!', 'success')
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('vendors.view', id=id)
            return response
        
        except Exception as e:
            return handle_post_error(e, "vendors.edit")

    return render_template('vendors/form.html', mode='edit', vendor=vendor)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    """Soft delete the vendor."""
    try:
        vendor = VendorService.archive(id)
        if vendor:
            flash(f'Vendor {vendor.company_name} archived.', 'success')
        else:
            raise ValueError("Vendor not found.")
        return redirect(url_for('vendors.index'))
    
    except Exception as e:
        return handle_post_error(e, "vendors.archive")

# --- HTMX PARTIALS ---

@bp.route('/contact-row')
def contact_row():
    """Returns a blank contact row for the dynamic form."""
    return render_template('vendors/partials/contact.html', contact=None)

# --- INTERNAL HELPERS ---

def _parse_contact_form(form_data):
    """Helper to zip parallel list inputs into a list of dictionaries."""
    first_names = form_data.getlist('contact_first[]')
    last_names = form_data.getlist('contact_last[]')
    emails = form_data.getlist('contact_email[]')
    phones = form_data.getlist('contact_phone[]')
    
    contacts = []
    for first_name, last_name, email, phone in zip(first_names, last_names, emails, phones):
        if any([first_name.strip(), last_name.strip(), email.strip(), phone.strip()]):
            contacts.append({
                'first_name': first_name.strip(),
                'last_name': last_name.strip(),
                'email': email.strip(),
                'phone': phone.strip()
            })
    return contacts
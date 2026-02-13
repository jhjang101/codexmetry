from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.vendors_service import VendorService
from ..extensions import db

bp = Blueprint('vendors', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main directory for Vendors module."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE
    session['vendors_last_url'] = request.full_path

    pagination = VendorService.get_all_with_search(search_term, page=page, per_page=10)

    if request.headers.get('HX-Request'):
        return render_template('vendors/partials/list.html', pagination=pagination)
    
    return render_template('vendors/vendors.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
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
            flash(f'Vendor {new_vendor.company_name} added successfully!', 'success')
            return redirect(url_for('vendors.index'))

        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return redirect(url_for('vendors.add'))

    return render_template('vendors/form.html', mode='add', vendor=None)

@bp.route('/view/<int:id>')
def view(id):
    try:
        vendor = VendorService.get_by_id(id)
        if not vendor:
            flash("Vendor not found.", "error")
            return redirect(url_for('vendors.index'))
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('vendors.index'))
    
    return render_template('vendors/form.html', mode='view', vendor=vendor)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    try:
        vendor = VendorService.get_by_id(id)
        if not vendor:
            flash("Vendor not found.", "error")
            return redirect(url_for('vendors.index'))
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
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
            return redirect(url_for('vendors.view', id=id))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return redirect(url_for('vendors.edit', id=id))

    return render_template('vendors/form.html', mode='edit', vendor=vendor)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    """Soft delete the vendor."""
    vendor = VendorService.archive(id)
    if vendor:
        flash(f'Vendor {vendor.company_name} moved to archives.', 'warning')
    else:
        flash('Vendor not found.', 'error')
    return redirect(url_for('vendors.index'))

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
    
    contacts = []
    for first_name, last_name, email in zip(first_names, last_names, emails):
        if first_name.strip() or last_name.strip(): # Only include if there is a name
            contacts.append({
                'first_name': first_name.strip(),
                'last_name': last_name.strip(),
                'email': email.strip()
            })
    return contacts
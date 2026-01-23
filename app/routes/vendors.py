from flask import Blueprint, render_template, request, redirect, url_for, session
from ..services.vendors_service import VendorService

bp = Blueprint('vendors', __name__)

@bp.route('/')
def index():
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['vendors_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = VendorService.get_all_with_search(search_term, page=page, per_page=2)

    # If HTMX request, return only the table partial
    if request.headers.get('HX-Request'):
        return render_template('vendors/partials/list.html', pagination=pagination)
    
    return render_template('vendors/vendors.html', pagination=pagination, search=search_term)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Save Main Vendor Data
        vendor_data = {
            'company_name': request.form.get('company_name'),
            'url': request.form.get('url'),
            'address': request.form.get('address')
        }
        new_vendor = VendorService.add(**vendor_data)

        # 2. Process and Save Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        VendorService.update_personnel(new_vendor.id, contacts)
        return redirect(url_for('vendors.index'))

    return render_template('vendors/form.html', mode='add', vendor=None)

@bp.route('/view/<int:id>')
def view(id):
    vendor = VendorService.get_by_id(id)
    return render_template('vendors/form.html', mode='view', vendor=vendor)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    vendor = VendorService.get_by_id(id)
    if request.method == 'POST':
        # 1. Update Main Vendor Data
        vendor_data = {
            'company_name': request.form.get('company_name'),
            'url': request.form.get('url'),
            'address': request.form.get('address')
        }
        VendorService.update(id, **vendor_data)

        # 2. Update Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        VendorService.update_personnel(id, contacts)
        return redirect(url_for('vendors.view', id=id))

    return render_template('vendors/form.html', mode='edit', vendor=vendor)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    VendorService.archive(id)
    return redirect(url_for('vendors.index'))

# --- HTMX PARTIALS ---

@bp.route('/contact-row')
def contact_row():
    return render_template('vendors/partials/contact.html', contact=None)

# --- INTERNAL HELPERS ---

def _parse_contact_form(form_data):
    first_names = form_data.getlist('contact_first[]')
    last_names = form_data.getlist('contact_last[]')
    emails = form_data.getlist('contact_email[]')
    
    contacts = []
    for f, l, e in zip(first_names, last_names, emails):
        if f.strip() or l.strip():
            contacts.append({
                'first_name': f.strip(),
                'last_name': l.strip(),
                'email': e.strip()
            })
    return contacts
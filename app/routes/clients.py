from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.clients_service import ClientService
from ..services.audit_service import AuditLogService
from ..utils.auth import role_required
from ..extensions import db

bp = Blueprint('clients', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main landing page for Clients module."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['clients_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ClientService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)

    # If HTMX request, return only the table partial
    if request.headers.get('HX-Request'):
        return render_template('clients/partials/list.html', pagination=pagination)
    
    return render_template('clients/clients.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Prepare data
            client_data = {
                'company_name': request.form.get('company_name'),
                'address': request.form.get('address')
            }
            contacts_data = _parse_contact_form(request.form)

            # 2. Save data
            new_client = ClientService.add_client(client_data, contacts_data)

            # 3. Flash message
            flash(f'Client {new_client.company_name} added successfully!', 'success')

            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('clients.view', id=new_client.id)
            return response

        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp

    return render_template('clients/form.html', mode='add', client=None)

@bp.route('/view/<int:id>')
def view(id):
    try:
        client = ClientService.get_by_id(id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for('clients.index'))
        
        history = AuditLogService.get_for_entity('Client', id)
        
    except ValueError as e:
        db.session.rollback()
        flash(f"Error loading client: {str(e)}", 'error')
        return redirect(url_for('clients.index'))

    return render_template('clients/form.html', mode='view', client=client, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    try:
        client = ClientService.get_by_id(id)
        if not client:
            flash("Client not found.", "error")
            return redirect(url_for('clients.index'))
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('clients.index'))

    if request.method == 'POST':
        try:
            # 1. Prepare data
            client_data = {
                'company_name': request.form.get('company_name'),
                'address': request.form.get('address')
            }
            contacts = _parse_contact_form(request.form)

            # 2. Update data
            ClientService.edit_client(id, client_data, contacts)

            # 3. Flash
            flash(f'Client {client.company_name} updated successfully!', 'success')
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('clients.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    return render_template('clients/form.html', mode='edit', client=client)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    client = ClientService.archive(id)
    if client:
        flash(f'Client {client.company_name} has been moved to archives.', 'warning')
    else:
        flash('Client not found.', 'error')
    return redirect(url_for('clients.index'))

# --- HTMX PARTIALS ---

@bp.route('/contact-row')
def contact_row():
    """Returns a blank contact row for the dynamic form."""
    return render_template('clients/partials/contact.html', contact=None)

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
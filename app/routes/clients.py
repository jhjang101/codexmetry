from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.clients_service import ClientService

bp = Blueprint('clients', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main landing page for Clients module."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['clients_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ClientService.get_all_with_search(search_term, page=page, per_page=10)

    # If HTMX request, return only the table partial
    if request.headers.get('HX-Request'):
        return render_template('clients/partials/list.html', pagination=pagination)
    
    return render_template('clients/clients.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Save Main Client Data
        client_data = {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        }
        new_client = ClientService.add(**client_data)

        # 2. Process and Save Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        ClientService.update_personnel(new_client.id, contacts)

        flash(f'Client {new_client.company_name} added successfully!', 'success')
        return redirect(url_for('clients.index'))

    return render_template('clients/form.html', mode='add', client=None)

@bp.route('/view/<int:id>')
def view(id):
    client = ClientService.get_by_id(id)
    return render_template('clients/form.html', mode='view', client=client)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    client = ClientService.get_by_id(id)
    if request.method == 'POST':
        # 1. Update Main Client Data
        client_data = {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        }
        ClientService.update(id, **client_data)

        # 2. Update Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        ClientService.update_personnel(id, contacts)

        flash(f'Client {client.company_name} updated successfully!', 'success')
        return redirect(url_for('clients.view', id=id))

    return render_template('clients/form.html', mode='edit', client=client)

@bp.route('/archive/<int:id>', methods=['POST'])
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
    
    contacts = []
    for f, l, e in zip(first_names, last_names, emails):
        if f.strip() or l.strip(): # Only include if there is a name
            contacts.append({
                'first_name': f.strip(),
                'last_name': l.strip(),
                'email': e.strip()
            })
    return contacts
from flask import Blueprint, render_template, request, redirect, url_for
from ..services.clients_service import ClientService as Client

bp = Blueprint('clients', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main landing page for Clients module."""
    search_term = request.args.get('search', '')

    print(f"Search Term: {search_term}")

    clients = Client.get_all_with_search(search_term)
    
    # If HTMX request, return only the table partial
    if request.headers.get('HX-Request'):
        return render_template('clients/partials/list.html', clients=clients)
    
    return render_template('clients/clients.html', clients=clients)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Save Main Client Data
        client_data = {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        }
        new_client = Client.add(**client_data)

        # 2. Process and Save Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        Client.update_personnel(new_client.id, contacts)

        return redirect(url_for('clients.index'))

    return render_template('clients/form.html', mode='add', client=None)

@bp.route('/view/<int:id>')
def view(id):
    client = Client.get_by_id(id)
    return render_template('clients/form.html', mode='view', client=client)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    client = Client.get_by_id(id)
    if request.method == 'POST':
        # 1. Update Main Client Data
        client_data = {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        }
        Client.update(id, **client_data)

        # 2. Update Personnel (Contacts)
        contacts = _parse_contact_form(request.form)
        Client.update_personnel(id, contacts)

        return redirect(url_for('clients.view', id=id))

    return render_template('clients/form.html', mode='edit', client=client)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    Client.archive(id)
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
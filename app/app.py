import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, g, request, redirect, url_for
from database import *
from datetime import datetime
from zoneinfo import ZoneInfo

# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
DATABASE=os.path.join(app.root_path, 'instance', 'codexmetry.db')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DATABASE'] = DATABASE

# Ensure the upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Register Jinja Filter
@app.template_filter('usd')
def usd_filter(cents):
    return format_usd(cents)

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# Initialize the database
init_db(app)

# --- ROUTES ---

@app.context_processor
def inject_metadata():
    metadata_raw = read_db(table_name='settings_metadata', active_only=False, id=1, one=True)
    metadata = dict(metadata_raw) if metadata_raw else None
    if metadata:
        tz = metadata.get('timezone', 'America/Chicago')
    else:
        tz = 'America/Chicago'
    now = datetime.now(ZoneInfo(tz))

    return dict(metadata=metadata, now=now)

@app.route('/')
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/purchase-orders')
def purchase_orders(): return "Purchase Orders Coming Soon"

@app.route('/invoices')
def invoices(): return "Invoices Coming Soon"

@app.route('/payments')
def payments(): return "Payments Coming Soon"

@app.route('/expenses')
def expenses(): return "Expenses Coming Soon"

@app.route('/products')
def products(): return "Products Coming Soon"

@app.route('/vendors')
def vendors(): return "Vendors Coming Soon"

@app.route('/transactions')
def transactions(): return "Transactions Coming Soon"

@app.route('/reports')
def reports(): return "Reports Coming Soon"

# --- CLIENTS ---
@app.route('/clients')
def clients():
    search_query = request.args.get('search', '')

    if search_query:
        client_data = read_db(table_name='clients', where_clause="company_name LIKE ?", args=(f"%{search_query}%",))
    else:
        client_data = get_clients_with_contacts()

    context = {
        "clients": client_data,
        "search_query": search_query
    }

    # If it's an HTMX request, return ONLY the partial
    if request.headers.get('HX-Request'):
        return render_template('partials/client_table.html', **context)

    # Otherwise, return the full page (which includes the partial)
    return render_template('clients.html', clients=client_data)

@app.route('/clients/add', methods=['GET', 'POST'])
def client_add():
    if request.method == 'POST':
        # 1. Save Company
        client_id = insert_db('clients', {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        })
        
        # 2. Save Contacts (Loop through lists)
        first_names = request.form.getlist('contact_first[]')
        last_names = request.form.getlist('contact_last[]')
        emails = request.form.getlist('contact_email[]')
        
        for i in range(len(first_names)):
            if first_names[i] or last_names[i]: # Only save if name exists
                insert_db('client_contacts', {
                    'client_id': client_id,
                    'first_name': first_names[i],
                    'last_name': last_names[i],
                    'email': emails[i]
                })
        
        return redirect(url_for('clients'))
    
    return render_template('client_form.html', mode='add', client={}, contacts=[])

@app.route('/clients/view/<int:id>')
def client_view(id):
    client = read_db('clients', id=id, one=True)
    if not client: # If client is archived or doesn't exist
        return redirect(url_for('clients'))
    contacts = read_db('client_contacts', active_only=False, where_clause="client_id = ?", args=(id,))
    return render_template('client_form.html', mode='view', client=client, contacts=contacts)

@app.route('/clients/edit/<int:id>', methods=['GET', 'POST'])
def client_edit(id):
    if request.method == 'POST':
        # 1. Update Company
        update_db('clients', id, {
            'company_name': request.form.get('company_name'),
            'address': request.form.get('address')
        })
        
        # 2. Simple Update Pattern: Clear old contacts and re-insert new ones
        # This is much easier than tracking which specific contact changed
        delete_db('client_contacts', where_clause="client_id = ?", args=(id,))
        
        first_names = request.form.getlist('contact_first[]')
        last_names = request.form.getlist('contact_last[]')
        emails = request.form.getlist('contact_email[]')
        
        for i in range(len(first_names)):
            if first_names[i] or last_names[i]:
                insert_db('client_contacts', {
                    'client_id': id,
                    'first_name': first_names[i],
                    'last_name': last_names[i],
                    'email': emails[i]
                })

        return redirect(url_for('client_view', id=id))
    
    # GET: Load the edit form
    client = read_db('clients', id=id, one=True)
    contacts = read_db('client_contacts', active_only=False, where_clause="client_id = ?", args=(id,))
    return render_template('client_form.html', mode='edit', client=client, contacts=contacts)

@app.route('/clients/archive/<int:id>', methods=['POST'])
def client_archive(id):
    archive_db('clients', id)
    return redirect(url_for('clients'))

# Route to fetch the empty contact row (HTMX)
@app.route('/clients/contact/row')
def client_contact_row():
    return render_template('partials/contact_row.html')







# --- SETTINGS ---
@app.route('/settings')
def settings():
    # Metadata is injected in @app.context_processor decorator

    # Fetch Lookup Tables
    lookups = {
        'po_types': read_db(table_name='po_types'),
        'product_categories': read_db(table_name='product_categories'),
        'expense_categories': read_db(table_name='expense_categories'),
        'payment_types': read_db(table_name='payment_types'),
        'transaction_categories': read_db(table_name='transaction_categories')
    }

    return render_template('settings.html', lookups=lookups)

@app.route('/settings/metadata/update', methods=['POST'])
def update_metadata():
    company_name = request.form.get('company_name')
    address = request.form.get('address')
    timezone = request.form.get('timezone')
    threshold_raw = request.form.get('threshold', '$100.00')
    threshold_cents = parse_to_cents(threshold_raw)
    doc_padding = request.form.get('doc_padding', 4)

    # Image Logic Implementation
    new_image = request.files.get('logo')
    
    if new_image and allowed_file(new_image.filename):
        # 1. Get old_image to delete it later 
        old_image = request.form.get('old_image') # None in the bigining
        
        # 2. Prepare new_image filename
        filename = secure_filename(f"logo_{new_image.filename}")
        filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

        # 3. Save to physical disk
        new_image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # 4. Update DB
        update_db(table_name='settings_metadata', 
                  id=1,
                  data={'company_name': company_name,
                        'address': address,
                        'timezone': timezone,
                        'invoice_threshold': threshold_cents,
                        'doc_padding': doc_padding,
                        'company_logo': filename
                        })
        
        # 5. Delete OLD file
        if old_image:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_image)
            if os.path.exists(old_path):
                os.remove(old_path)

    else:
        # Standard update DB - No image update
        update_db(table_name='settings_metadata', 
                  id=1,
                  data={'company_name': company_name,
                        'address': address,
                        'timezone': timezone,
                        'invoice_threshold': threshold_cents,
                        'doc_padding': doc_padding
                        })
    
    return redirect(url_for('settings'))

# HTMX Route to add a lookup item
@app.route('/settings/lookup/add', methods=['POST'])
def add_lookup():
    table = request.form.get('table')
    item = request.form.get('item')
    if table and item:
        insert_db(table_name=table, data={'name': item})
    
    # Return ONLY the specific card HTML instead of a redirect
    items = read_db(table_name=table)
    return render_template('partials/lookup_card.html', table_name=table, items=items)

# HTMX Route to archive a lookup item
@app.route('/settings/lookup/archive/<table_name>/<int:id>', methods=['POST'])
def archive_lookup(table_name, id):
    archive_db(table_name=table_name, id=id)
    return "" # HTMX will remove the row if we handle it, or we can just redirect








if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)
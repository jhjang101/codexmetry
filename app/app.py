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
    metadata = read_db(table_name='settings_metadata', active_only=False, id=1, one=True)
    tz = metadata['timezone']
    now = datetime.now(ZoneInfo(tz))

    return dict(metadata=metadata, now=now)

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# --- SETTINGS ROUTES ---
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
    threshold_raw = request.form.get('threshold')
    threshold_cents = parse_to_cents(threshold_raw)

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
                        'invoice_threshold': threshold_cents
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
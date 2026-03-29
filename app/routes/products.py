from flask import Blueprint, render_template, request, redirect, url_for, session, flash, make_response
from flask_login import login_required
from ..services.products_service import ProductService
from ..services.settings_service import ProductCategoryService
from ..services.audit_service import AuditLogService
from ..utils.images import save_image
from ..utils.auth import role_required
from ..extensions import db

bp = Blueprint('products', __name__)

@bp.before_request
@login_required
def before_request():
    """Protect all routes within this blueprint."""
    pass

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main product directory with HTMX search support."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['products_last_url'] = request.full_path

    # 1. Extract Sorting Parameters (with defaults)
    sort_by = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    # 2. pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ProductService.get_all_with_search(search_term=search_term, 
                                                    page=page, 
                                                    per_page=10, 
                                                    sort_by=sort_by, 
                                                    direction=direction)
    
    if request.headers.get('HX-Request'):
        return render_template('products/partials/list.html', pagination=pagination)
    
    return render_template('products/products.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---
# view, add, and edit route is now htmx

@bp.route('/add', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def add():
    if request.method == 'POST':
        try:
            # 1. Handle Image Upload via Utility
            image_file = request.files.get('image')
            # subfolder 'products' ensures images go to static/uploads/products/
            saved_filename = save_image(image_file, subfolder='products')

            # 2. Prepare data
            product_data = {
                'name': request.form.get('name'),
                'catalog_number': request.form.get('catalog_number'),
                'category_id': request.form.get('category_id'),
                'document_placement': request.form.get('document_placement'),
                'default_unit_price': request.form.get('unit_price'),
                'image_url': saved_filename
            }

            # 3. Call Service
            new_product = ProductService.add_product(product_data)

            flash('Product added successfully!', 'success')
            # The Safe Save Redirect: Forces a clean page load to 'View' mode
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('products.view', id=new_product.id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            # Return the OOB Error partial
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            # Tell HTMX NOT to swap the form, preserving all user input
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='add', product=None, categories=categories)

@bp.route('/view/<int:id>')
def view(id):
    product = ProductService.get_product_by_id(id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for('products.index'))
    
    history = AuditLogService.get_for_entity('Product', id)

    return render_template('products/form.html', mode='view', product=product, history=history)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@role_required(['admin', 'user'])
def edit(id):
    product = ProductService.get_product_by_id(id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for('products.index'))
    
    if request.method == 'POST':
        try:
            # 1. Handle Image Update (includes physical cleanup of old file)
            image_file = request.files.get('image')
            old_image = request.form.get('old_image')
            saved_filename = save_image(image_file, subfolder='products', old_filename=old_image)

            # 2. Prepare data
            product_data = {
                'name': request.form.get('name'),
                'catalog_number': request.form.get('catalog_number'),
                'category_id': request.form.get('category_id'),
                'document_placement': request.form.get('document_placement', 'Lineitem'),
                'default_unit_price': request.form.get('unit_price', ''),
                'image_url': old_image
            }
            
            # Only update image_url in DB if a new file was actually uploaded
            if saved_filename:
                product_data['image_url'] = saved_filename

            # 3. Call Service
            ProductService.edit_product(id, product_data)

            # 4. Flash
            flash(f'Product {product.name} updated successfully!', 'success')
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('products.view', id=id)
            return response
        
        except ValueError as e:
            db.session.rollback()
            resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
            resp.headers['HX-Reswap'] = 'none'
            return resp

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='edit', product=product, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
@role_required(['admin']) # Only Admin can delete
def archive(id):
    try:
        product = ProductService.archive_product(id)
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for('products.index'))
        
        flash(f'Product {product.name} has been moved to archives.', 'warning')
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')

    return redirect(url_for('products.index'))
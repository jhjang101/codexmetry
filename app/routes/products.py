from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..services.products_service import ProductService
from ..services.settings_service import ProductCategoryService
from ..utils.images import save_image
from ..extensions import db

bp = Blueprint('products', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main product directory with HTMX search support."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # RECORD THE STATE: Save the current full URL into the session
    # request.full_path includes the ?search=...&page=...
    session['products_last_url'] = request.full_path

    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ProductService.get_all_with_search(search_term, page=page, per_page=10)
    
    if request.headers.get('HX-Request'):
        return render_template('products/partials/list.html', pagination=pagination)
    
    return render_template('products/products.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
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
                'default_unit_price': request.form.get('unit_price'),
                'image_url': saved_filename
            }

            # 3. Call Service
            ProductService.add_product(product_data)

            flash('Product added successfully!', 'success')
            return redirect(url_for('products.index'))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return redirect(url_for('products.add'))

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='add', product=None, categories=categories)

@bp.route('/view/<int:id>')
def view(id):
    try:
        product = ProductService.get_product_by_id(id)
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for('products.index'))
        
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', mode='view', product=product)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    try:
        product = ProductService.get_product_by_id(id)
        if not product:
            flash("Product not found.", "error")
            return redirect(url_for('products.index'))
    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'error')
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
                'category_id': request.form.get('category_id') or None,
                'default_unit_price': request.form.get('unit_price', ''),
            }
            
            # Only update image_url in DB if a new file was actually uploaded
            if saved_filename:
                product_data['image_url'] = saved_filename

            # 3. Call Service
            ProductService.edit_product(id, product_data)

            # 4. Flash
            flash(f'Product {product.name} updated successfully!', 'success')
            return redirect(url_for('products.view', id=id))
        
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'error')
            return redirect(url_for('products.edit', id=id))

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='edit', product=product, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
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
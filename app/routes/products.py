from flask import Blueprint, render_template, request, redirect, url_for
from ..services.products_service import ProductService
from ..services.settings_service import ProductCategoryService
from ..utils.images import save_image
from ..utils.money import parse_to_cents

bp = Blueprint('products', __name__)

# --- LIST & SEARCH ---

@bp.route('/')
def index():
    """Main product directory with HTMX search support."""
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    # pagination is an object containing .items, .has_next, .has_prev, etc.
    pagination = ProductService.get_all_with_search(search_term, page=page, per_page=2)
    
    if request.headers.get('HX-Request'):
        return render_template('products/partials/list.html', pagination=pagination)
    
    return render_template('products/products.html', pagination=pagination, search=search_term)

# --- CRUD OPERATIONS ---

@bp.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 1. Handle Image Upload via Utility
        image_file = request.files.get('image')
        # subfolder 'products' ensures images go to static/uploads/products/
        saved_filename = save_image(image_file, subfolder='products')

        # 2. Prepare and Save Product Data
        product_data = {
            'name': request.form.get('name'),
            'catalog_number': request.form.get('catalog_number'),
            'category_id': request.form.get('category_id') or None,
            'default_unit_price': parse_to_cents(request.form.get('unit_price', '')),
            'image_url': saved_filename
        }
        ProductService.add(**product_data)
        return redirect(url_for('products.index'))

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='add', product=None, categories=categories)

@bp.route('/view/<int:id>')
def view(id):
    product = ProductService.get_by_id_with_category(id)

    return render_template('products/form.html', mode='view', product=product)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    product = ProductService.get_by_id(id)
    
    if request.method == 'POST':
        # 1. Handle Image Update (includes physical cleanup of old file)
        image_file = request.files.get('image')
        old_image = request.form.get('old_image')
        saved_filename = save_image(image_file, subfolder='products', old_filename=old_image)

        # 2. Update Product Data
        product_data = {
            'name': request.form.get('name'),
            'catalog_number': request.form.get('catalog_number'),
            'category_id': request.form.get('category_id') or None,
            'default_unit_price': parse_to_cents(request.form.get('unit_price', '')),
        }
        
        # Only update image_url in DB if a new file was actually uploaded
        if saved_filename:
            product_data['image_url'] = saved_filename

        ProductService.update(id, **product_data)
        return redirect(url_for('products.view', id=id))

    # GET: Load categories for the dropdown
    categories = ProductCategoryService.get_all()
    return render_template('products/form.html', mode='edit', product=product, categories=categories)

@bp.route('/archive/<int:id>', methods=['POST'])
def archive(id):
    ProductService.archive(id)
    return redirect(url_for('products.index'))
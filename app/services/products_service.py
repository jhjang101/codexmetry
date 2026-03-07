from .base_service import BaseService
from ..models import Product, ProductCategory
from ..utils.money import parse_to_cents
from ..extensions import db
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager

class ProductService(BaseService):
    model = Product

    # Define the Whitelist for sorting
    SORT_MAP = {
        'name': Product.name,
        'catalog': Product.catalog_number,
        'category': ProductCategory.type,  # Joined via category_id
        'price': Product.default_unit_price
    }


    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'name', 
                            direction: str = 'asc'):
        """
        Search: Fetches all active products.
        Joins with ProductCategory and hides system products.
        """
        # 1. Base statement (Hide system items and eager load category)
        stmt = (
            select(cls.model)
            .outerjoin(ProductCategory)
            .options(contains_eager(cls.model.category))
            .where(cls.model.is_active == True, cls.model.is_system == False)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.name.icontains(search_term),
                    cls.model.catalog_number.icontains(search_term),
                    ProductCategory.type.icontains(search_term)
                )
            )

        # 3. Apply Sorting using the BaseService helper
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.name
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page,
                            sort_by=sort_by, 
                            direction=direction)

    @classmethod
    def get_all_products(cls):
        """
        Dropdowns: Fetches active non-system products for form selection.
        """
        stmt = select(cls.model).where(
            cls.model.is_active == True,
            cls.model.is_system == False
        ).order_by(cls.model.name.asc())
        return db.session.execute(stmt).scalars().all()

    @classmethod
    def get_product_by_id(cls, product_id: int) -> Product | None:
        """
        Fetcher: Returns a single product with category data.
        Protects system products from being accessed for editing.
        """
        stmt = select(cls.model).outerjoin(ProductCategory).where(cls.model.id == product_id)
        product = db.session.execute(stmt).scalar_one_or_none()
        
        if product and product.is_system:
            raise ValueError("System products cannot be modified or archived.")
        
        return product

    @classmethod
    def add_product(cls, data: dict) -> Product:
        """
        Create new product.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create product
        product = cls.model(**clean_data)
        db.session.add(product)
        db.session.commit()

        return product

    @classmethod
    def edit_product(cls, product_id: int, data: dict) -> Product:
        """
        Update existing product.
        """
        # 1. Validation
        product = cls.get_product_by_id(product_id)
        if not product:
            raise ValueError("Product not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Update header
        for key, value in clean_data.items():
            setattr(product, key, value)

        db.session.commit()
        return product

    @classmethod
    def archive_product(cls, id) -> Product | None:
        """
        Soft delete with system protection.
        """
        # 1. Protection logic handled by get_product_by_id
        product = cls.get_by_id(id)
        if not product:
            return None
        
        # 2. Prevent uapdting system product
        is_system_product = product.is_system
        if is_system_product:
            raise ValueError("System products cannot be modified or archived.")
        
        # 2. Archive
        product.is_active = False
        db.session.commit()

        return product
    
    # --- INTERNAL HELPERS ---
    
    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles validation and price conversion."""
        # 1. Validation
        name = data.get('name', '').strip()
        if not name:
            raise ValueError("Product Name is required.")
        category_id = data.get('category_id')
        
        # 2. Transform data
        clean_data = {
            'name': name,
            'catalog_number': data.get('catalog_number', '').strip() if data.get('catalog_number') else None,
            'category_id': int(category_id) if category_id else None,
            'document_placement': data.get('document_placement', 'Lineitem'),
            'default_unit_price': parse_to_cents(str(data.get('default_unit_price', 0))),
            'image_url': data.get('image_url') # Handled by Route/images.py
        }
        
        return clean_data
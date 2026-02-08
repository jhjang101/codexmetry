from .base_service import BaseService
from ..models import Product, ProductCategory
from ..utils.money import parse_to_cents
from ..extensions import db
from sqlalchemy import select, or_

class ProductService(BaseService):
    model = Product

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches all active products.
        Joins with ProductCategory to allow searching by Category Type.
        """
        # 1. Start with a select statement joining the category table
        # We use outerjoin so products without a category still show up
        stmt = select(cls.model).outerjoin(ProductCategory).where(cls.model.is_active == True).where(cls.model.is_system == False)

        # 2. Apply filters if a search term is provided
        if search_term:
            # We search Name, Catalog Number, and the Category Type string
            stmt = stmt.where(
                or_(
                    cls.model.name.icontains(search_term),
                    cls.model.catalog_number.icontains(search_term),
                    ProductCategory.type.icontains(search_term)
                )
            )

        # 3. Order by product name alphabetically
        stmt = stmt.order_by(cls.model.name.asc())

        # 4. Use the paginate helper
        return cls.paginate(stmt, page=page, per_page=per_page)

    @classmethod
    def get_product_by_id(cls, product_id: int):
        """
        Fetches a single product and ensures category data is available.
        """
        stmt = select(cls.model).outerjoin(ProductCategory).where(cls.model.id == product_id)
        product = db.session.execute(stmt).scalar_one_or_none()
        if not product:
            return None

        is_system_product = product.is_system
        if is_system_product:
            raise ValueError("System products cannot be modified or archived.")
        
        return product
    
    @classmethod
    def update_product(cls, product_id: int, data: dict) -> Product | None:
        """
        Updates a single product.
        """
        product = cls.get_by_id(product_id)
        if not product:
            return None
        
        # 1. Prevent uapdting system product
        is_system_product = product.is_system
        if is_system_product:
            print("System product detected")
            raise ValueError("System products cannot be modified or archived.")
        
        # 2. Perform the validation loop
        value = data.get('name')
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Product Name is required.")
        
        # 3. Read data
        name = data['name']
        catalog_number = data.get('catalog_number')
        category_id = data.get('category_id')
        default_unit_price = data.get('default_unit_price')
        image_url = data.get('image_url')

        # 4. Transform data
        product_data = {
            'name': name.strip(),
            'catalog_number': catalog_number.strip() if catalog_number else None,
            'category_id': int(category_id) if category_id else None,
            'default_unit_price': parse_to_cents(default_unit_price) if default_unit_price else 0,
            'image_url': image_url if image_url else None
        }

        # 5. Update
        for key, value in product_data.items():
            if hasattr(product, key):
                setattr(product, key, value)
        db.session.commit()

        return product

    @classmethod
    def archive_product(cls, id) -> Product | None:
        """
        Archives a single product.
        """
        product = cls.get_by_id(id)
        if not product:
            return None
        
        # 1. Prevent uapdting system product
        is_system_product = product.is_system
        if is_system_product:
            raise ValueError("System products cannot be modified or archived.")
        
        # 2. Archive
        product.is_active = False
        db.session.commit()

        return product
    
    @classmethod
    def get_all_products(cls):
        """
        Fetches all active non-system products.
        """
        stmt = select(cls.model).where(
            cls.model.is_active == True,
            cls.model.is_system == False
            ).order_by(cls.model.name.asc())
        return db.session.execute(stmt).scalars().all()



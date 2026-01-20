from .base_service import BaseService
from ..models import Product, ProductCategory
from ..extensions import db
from sqlalchemy import select, or_

class ProductService(BaseService):
    model = Product

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None):
        """
        Fetches all active products.
        Joins with ProductCategory to allow searching by Category Type.
        """
        # 1. Start with a select statement joining the category table
        # We use outerjoin so products without a category still show up
        stmt = select(cls.model).outerjoin(ProductCategory).where(cls.model.is_active == True)

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

        # 4. Execute and return results
        return db.session.execute(stmt).scalars().all()

    @classmethod
    def get_by_id_with_category(cls, product_id: int):
        """
        Fetches a single product and ensures category data is available.
        """
        stmt = select(cls.model).outerjoin(ProductCategory).where(cls.model.id == product_id)
        return db.session.execute(stmt).scalar_one_or_none()
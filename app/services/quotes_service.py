from .base_service import BaseService
from ..models import Quote, QuoteItem, Client
from ..extensions import db
from ..utils.docs import generate_doc_number
from sqlalchemy import select, or_

class QuoteService(BaseService):
    model = Quote

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active quotes.
        Joins with Client to allow searching by Company Name.
        """
        stmt = select(cls.model).outerjoin(Client).where(cls.model.is_active == True)

        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.quote_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        stmt = stmt.order_by(cls.model.quote_date.desc())
        return cls.paginate(stmt, page=page, per_page=per_page)

    @classmethod
    def update_items(cls, quote_id: int, items_data: list[dict]):
        """
        Wipe current items and re-insert new ones.
        Calculates and updates the Quote.total_amount denormalized column.
        """
        # 1. Delete old items
        delete_stmt = db.delete(QuoteItem).where(QuoteItem.quote_id == quote_id)
        db.session.execute(delete_stmt)

        total_cents = 0

        # 2. Add new items
        for data in items_data:
            product_id = data.get('product_id')

            if product_id:
                product_id = int(product_id)
                qty = int(data.get('quantity', 0))
                price = int(data.get('unit_price', 0))
                line_total = qty * price
                total_cents += line_total

                new_item = QuoteItem()
                new_item.quote_id = quote_id
                new_item.product_id = product_id
                new_item.quantity = qty
                new_item.quoted_unit_price = price
                db.session.add(new_item)

        # 3. Update the Parent Total
        quote = cls.get_by_id(quote_id)
        if quote:
            quote.total_amount = total_cents
        
        db.session.commit()
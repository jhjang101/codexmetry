from .base_service import BaseService
from ..models import Quote, QuoteItem, Client, OrderRegistry
from ..extensions import db
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager
from datetime import datetime

class QuoteService(BaseService):
    model = Quote

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Search: Fetches active quotes with eager loading of Client and OrderRegistry.
        """
        # 1. Base statement
        stmt = (
            select(cls.model)
            .join(Client)
            .outerjoin(OrderRegistry)
            .options(
                contains_eager(cls.model.client),
                contains_eager(cls.model.order)
            )
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.quote_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term),
                    OrderRegistry.order_number.icontains(search_term)
                )
            )

        # 3. Order by date (newest first)
        stmt = stmt.order_by(cls.model.quote_date.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)
    
    @classmethod
    def add_quote(cls, data: dict, items_data: list[dict]) -> Quote:
        """
        Create new Quote header and line items.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create quote
        quote = cls.model(**clean_data)
        db.session.add(quote)
        db.session.flush() # Get ID for items

        # 3. Save items and calculate total
        cls._save_items(quote, items_data)

        db.session.commit()
        return quote
    
    @classmethod
    def edit_quote(cls, quote_id: int, data: dict, items_data: list[dict]) -> Quote:
        """
        Update Quote header and line items.
        """
        # 1. Validation
        quote = cls.get_by_id(quote_id)
        if not quote:
            raise ValueError("Quote not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Update header
        for key, value in clean_data.items():
            setattr(quote, key, value)

        # 4. Save items (Wipe and re-insert)
        cls._save_items(quote, items_data)

        db.session.commit()
        return quote
    
    @classmethod
    def get_quotes_by_client(cls, client_id: int):
        """
        Fetcher: Returns 'sent' quotes for a client that haven't been converted yet.
        Used for the PO creation dropdown.
        """
        stmt = select(cls.model).where(
            cls.model.client_id == client_id,
            cls.model.order_id == None,
            cls.model.is_active == True,
            cls.model.status.in_(['sent', 'draft'])
        ).order_by(cls.model.quote_date.desc())

        return db.session.execute(stmt).scalars().all()

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles header validation and data type conversion."""
        client_id = data.get('client_id')
        quote_number = data.get('quote_number', '').strip()
        
        if not client_id:
            raise ValueError("Client is required.")
        if not quote_number:
            raise ValueError("Quote Number is required.")

        # Parse dates
        raw_date = data.get('quote_date')
        raw_expiry = data.get('expiration_date')
        
        quote_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else datetime.now().date()
        expiration_date = datetime.strptime(raw_expiry, '%Y-%m-%d').date() if raw_expiry else None

        # Transform data
        clean_data ={
            'client_id': int(client_id),
            'quote_number': quote_number,
            'quote_date': quote_date,
            'expiration_date': expiration_date,
            'status': data.get('status', 'draft'),
            'note': data.get('note', '').strip()
        }

        return clean_data

    @classmethod
    def _save_items(cls, quote: Quote, items_data: list[dict]):
        """Manages QuoteItem rows and updates Quote.total_amount."""
        # 1. Wipe current items
        db.session.execute(
            db.delete(QuoteItem).where(QuoteItem.quote_id == quote.id)
        )

        total_cents = 0

        # 2. Re-insert current list
        for row in items_data:
            product_id = row.get('product_id')
            if product_id:
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                item = QuoteItem()
                item.quote_id = quote.id
                item.product_id = int(product_id)
                item.quantity = qty
                item.quoted_unit_price = price
                db.session.add(item)

        # 3. Update the snapshot total on the header
        quote.total_amount = total_cents

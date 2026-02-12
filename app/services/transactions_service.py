from .base_service import BaseService
from ..models import Transaction, TransactionCategory
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager
from datetime import datetime

class TransactionService(BaseService):
    model = Transaction

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active transactions with eager category loading.
        """
        # 1. Base statement with eager category loading
        stmt = (
            select(cls.model)
            .outerjoin(TransactionCategory)
            .options(contains_eager(cls.model.category))
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.transaction_number.icontains(search_term),
                    cls.model.description.icontains(search_term),
                    TransactionCategory.type.icontains(search_term)
                )
            )

        # 3. Order by date (newest first)
        stmt = stmt.order_by(cls.model.transaction_date.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)

    @classmethod
    def create_transaction(cls, data: dict) -> Transaction:
        """
        Brain logic for creating a non-operational transaction.
        Handles TRX- numbering and date/currency parsing.
        """
        from datetime import date

        # 1. Generate unique TRX number
        trx_number = generate_doc_number(prefix='TRX', model=cls.model, column_name='transaction_number')

        # 2. Validation
        description = data.get('description', '').strip()
        amount_raw = data.get('amount', '0')
        
        if not description:
            raise ValueError("Transaction Description is required.")
        if not amount_raw:
            raise ValueError("Amount is required.")

        # 3. Transform Data
        # Date parsing
        raw_date = data.get('transaction_date')
        category_id = data.get('category_id')
        if raw_date and isinstance(raw_date, str):
            transaction_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        else:
            transaction_date = date.today()

        # Currency parsing (handles gains like '5.00' or losses like '-2.50')
        amount_cents = parse_to_cents(str(amount_raw))
        

        # 4. Create Object
        trx = cls.model()
        trx.transaction_number = trx_number
        trx.description = description
        trx.amount = amount_cents
        trx.transaction_date = transaction_date
        trx.category_id = int(category_id) if category_id else None
        trx.note = data.get('note', '')

        db.session.add(trx)
        db.session.commit()
        return trx
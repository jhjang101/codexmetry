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
    def add_transaction(cls, data: dict) -> Transaction:
        """
        Atomic creation of a non-operational transaction.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Generate Number
        trx_number = generate_doc_number(prefix='TRX', model=cls.model, column_name='transaction_number')

        # 3. Create header
        trx = cls.model(**clean_data)
        trx.transaction_number = trx_number
        db.session.add(trx)
        
        db.session.commit()
        return trx

    @classmethod
    def edit_transaction(cls, trx_id: int, data: dict) -> Transaction:
        """
        Update an existing transaction.
        """
        # 1. Validation
        trx = cls.get_by_id(trx_id)
        if not trx:
            raise ValueError("Transaction not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Update attributes
        for key, value in clean_data.items():
            setattr(trx, key, value)

        db.session.commit()
        return trx

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles validation and type conversion."""
        description = data.get('description', '').strip()
        amount_raw = data.get('amount', '0')
        
        if not description:
            raise ValueError("Transaction Description is required.")
        if not amount_raw:
            raise ValueError("Amount is required.")

        # Parse Date
        raw_date = data.get('transaction_date')
        trx_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if isinstance(raw_date, str) else datetime.now().date()
        category_id = data.get('category_id')

        clean_data = {
            'description': description,
            'amount': parse_to_cents(str(amount_raw)),
            'transaction_date': trx_date,
            'category_id': int(category_id) if category_id else None,
            'note': data.get('note', '').strip()
        }

        return clean_data
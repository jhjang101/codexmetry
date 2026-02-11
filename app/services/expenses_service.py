from .base_service import BaseService
from ..models import Expense, ExpenseCategory, ExpenseItem, Vendor, VendorContact
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents, format_usd
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager
from datetime import datetime

class ExpenseService(BaseService):
    model = Expense
    
    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        # 1. Base statement with eager loading
        stmt = (
            select(cls.model)
            .join(Vendor)
            .outerjoin(ExpenseCategory)
            .options(
                contains_eager(cls.model.vendor),
                contains_eager(cls.model.category)
            )
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.expense_number.icontains(search_term),
                    cls.model.description.icontains(search_term), # Added this
                    Vendor.company_name.icontains(search_term),
                    ExpenseCategory.type.icontains(search_term)
                )
            )

        stmt = stmt.order_by(cls.model.expense_date.desc())
        return cls.paginate(stmt, page=page, per_page=per_page)
    
    @classmethod
    def create_expense(cls, data: dict) -> Expense:
        """
        Creates an Expense header with automated EXP numbering.
        """
        from datetime import date

        # 1. Generate the next EXP number
        expense_number = generate_doc_number(prefix='EXP', model=cls.model, column_name='expense_number')

        # 2. Extract and Validate
        vendor_id = data.get('vendor_id')
        description = data.get('description', '').strip()

        if not vendor_id:
            raise ValueError("Vendor is required.")
        if not description:
            raise ValueError("Description is required.")

        # 3. Extract oters and transform Date string to object
        category_id = data.get('category_id')

        raw_date = data.get('expense_date')
        if raw_date and isinstance(raw_date, str):
            expense_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        else:
            expense_date = date.today()

        # 4. Create the Header Object
        expense = cls.model()
        expense.expense_number = expense_number
        expense.vendor_id = int(vendor_id)
        expense.description = description
        expense.category_id = category_id if category_id else None
        expense.expense_date = expense_date
        expense.note = data.get('note', '')

        db.session.add(expense)
        db.session.commit()
        return expense

    @classmethod
    def update_items(cls, expense_id: int, items_data: list[dict]):
        """
        Wipe current items and re-insert new ones.
        Calculates and updates the Expense.total_amount.
        """
        # 1. Delete old items
        delete_stmt = db.delete(ExpenseItem).where(ExpenseItem.expense_id == expense_id)
        db.session.execute(delete_stmt)

        total_cents = 0

        # 2. Add new items (Item is a string, not an ID)
        for data in items_data:
            # Check if user input item_text
            item_text = data.get('item', '').strip()
            if not item_text:
                raise ValueError(f"Item field is required.")

            qty = int(data.get('quantity', 1))
            price = parse_to_cents(data.get('unit_price', 0))
            line_total = qty * price
            total_cents += line_total

            new_item = ExpenseItem()
            new_item.expense_id = expense_id
            new_item.item = item_text
            new_item.quantity = qty
            new_item.unit_price = price
            db.session.add(new_item)

        # 3. Update the Header Total
        expense = cls.get_by_id(expense_id)
        if expense:
            expense.total_amount = total_cents
        
        db.session.commit()

from .base_service import BaseService
from ..models import Expense, ExpenseItem,  Vendor,  ExpenseCategory, Client, OrderRegistry, PurchaseOrder, Invoice
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime

class ExpenseService(BaseService):
    model = Expense
    
    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        # 1. Base statement with eager loading
        stmt = (
            select(cls.model)
            .join(cls.model.vendor)
            .outerjoin(cls.model.client)
            .outerjoin(cls.model.category)
            .outerjoin(cls.model.order)
            .outerjoin(cls.model.purchase_order)
            .outerjoin(cls.model.invoice)
            .options(
                contains_eager(cls.model.vendor),
                contains_eager(cls.model.category),
                contains_eager(cls.model.client),
                contains_eager(cls.model.order),
                contains_eager(cls.model.purchase_order),
                contains_eager(cls.model.invoice)
            )
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.expense_number.icontains(search_term),
                    cls.model.description.icontains(search_term),
                    Vendor.company_name.icontains(search_term),
                    ExpenseCategory.type.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    OrderRegistry.order_number.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),
                    Invoice.invoice_number.icontains(search_term)
                )
            )

        # 3. Add .distinct() to collapse duplicate rows caused by joins
        stmt = stmt.distinct()

        # 4. Order by date (newest first)
        stmt = stmt.order_by(cls.model.expense_date.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)
    
    @classmethod
    def add_expense(cls, data: dict, items_data: list[dict]) -> Expense:
        """
        Create new Expense header and items.
        Logic: If description is blank, fall back to the first item description.
        """
        # 1. Validate & transform (includes description fallback)
        clean_data = cls._validate_and_transform(data, items_data)

        # 2. Generate Number
        expense_number = generate_doc_number(prefix='EP', model=cls.model, column_name='expense_number')

        # 3. Create header
        expense = cls.model(**clean_data)
        expense.expense_number = expense_number
        db.session.add(expense)
        db.session.flush() # Get ID for items

        # 4. Save items and update total
        cls._save_items(expense, items_data)

        db.session.commit()
        return expense
    
    @classmethod
    def edit_expense(cls, expense_id: int, data: dict, items_data: list[dict]) -> Expense:
        """
        Update Expense header and items.
        """
        # 1. Validation
        expense = cls.get_expense_by_id(expense_id)
        if not expense:
            raise ValueError("Expense not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data, items_data)

        # 3. Update header attributes
        for key, value in clean_data.items():
            setattr(expense, key, value)

        # 4. Save items (Wipe and re-insert)
        cls._save_items(expense, items_data)

        db.session.commit()
        return expense
    
    @classmethod
    def get_expense_by_id(cls, id: int) -> Expense | None:
        """
        Fetcher: Returns Expense with eager-loaded Vendor, Client (and contacts),
        and the full Project Registry hierarchy (Order, PO, Invoice).
        Prevents N+1 queries when using .full_display or viewing job-costing refs.
        """
        stmt = (
            select(cls.model)
            .options(
                # 1. Load mandatory Vendor relationship
                joinedload(cls.model.vendor),
                # 2. Load the optional Client and their contacts for .full_display
                joinedload(cls.model.client).selectinload(Client.contacts),
                # 3. Load the lookup category
                joinedload(cls.model.category),
                # 4. Load the Job Costing hierarchy
                joinedload(cls.model.order),
                joinedload(cls.model.purchase_order),
                joinedload(cls.model.invoice)
            )
            .where(cls.model.id == id)
        )
        return db.session.execute(stmt).scalar_one_or_none()
    
    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict, items_data: list[dict]) -> dict:
        """Handles header validation and description fallback."""
        vendor_id = data.get('vendor_id')
        if not vendor_id:
            raise ValueError("Vendor is required.")
        
        if not items_data:
            raise ValueError("At least one expense item is required.")

        # 1. Description Fallback Logic
        description = data.get('description', '').strip()
        if not description:
            # Fallback to the text of the first item
            description = items_data[0].get('item', '').strip()
        
        if not description:
            raise ValueError("Description is required or must be provided in the first item line.")
        
        # 2. Expense Linkage (Client -> PO -> Invoice -> Order inheritance)
        client_id = data.get('client_id')
        po_id = data.get('po_id')
        invoice_id = data.get('invoice_id')
        order_id = None

        if invoice_id:
            invoice = db.session.get(Invoice, int(invoice_id))
            if invoice:
                client_id = invoice.client_id
                po_id = invoice.po_id
                order_id = invoice.order_id
        elif po_id:
            po = db.session.get(PurchaseOrder, int(po_id))
            if po:
                client_id = po.client_id
                order_id = po.order_id
        # Note: If only client_id was provided, it remains as captured from data.get

        # 3. Transform Date
        raw_date = data.get('expense_date')
        expense_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if isinstance(raw_date, str) else datetime.now().date()
        category_id = data.get('category_id')

        clean_data ={
            'vendor_id': int(vendor_id),
            'category_id': int(category_id) if category_id else None,
            'client_id': int(client_id) if client_id else None,
            'order_id': order_id,
            'po_id': int(po_id) if po_id else None,
            'invoice_id': int(invoice_id) if invoice_id else None,
            'description': description,
            'expense_date': expense_date,
            'status': data.get('status', 'open'),
            'note': data.get('note', '').strip()
        }

        return clean_data


    @classmethod
    def _save_items(cls, expense: Expense, items_data: list[dict]):
        """Manages ExpenseItem rows (strings) and updates Expense.total_amount."""
        # 1. Wipe current items
        db.session.execute(
            db.delete(ExpenseItem).where(ExpenseItem.expense_id == expense.id)
        )

        total_cents = 0

        # 2. Re-insert current snapshot
        for row in items_data:
            item_text = row.get('item', '').strip()
            if item_text:
                description = row.get('description', '').strip()
                catalog_number = row.get('catalog_number', '').strip()
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                item = ExpenseItem()
                item.expense_id = expense.id
                item.catalog_number = catalog_number
                item.item = item_text
                item.quantity = qty
                item.unit_price = price
                item.description = description
                db.session.add(item)
            else:
                raise ValueError("Item description is required for all rows.")

        # 3. Update the header total
        expense.total_amount = total_cents
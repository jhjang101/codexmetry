from .base_service import BaseService
from ..models import Invoice, InvoiceItem, PurchaseOrder, OrderRegistry, Client, Payment, Product, SettingsMetadata
from ..extensions import db
from ..utils.money import parse_to_cents, format_usd
from ..utils.manual_pagination import ManualPagination
from sqlalchemy import select, or_, func, case
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime
from zoneinfo import ZoneInfo

class InvoiceService(BaseService):
    model = Invoice

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active Invoices with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name)
        Use subquery to calculate balance and total due.
        """
        # 1. Subquery for Payment Sum
        pay_sub = (
            select(
                Payment.invoice_id, 
                func.sum(Payment.amount).label('total_paid')
            )
            .where(Payment.is_active == True)
            .group_by(Payment.invoice_id)
            .subquery()
        )

        # 2. Main Query with Calculated Balance Label
        stmt = (
            select(
                cls.model,
                (
                    #  Balance = Total Due (clamped at 0) - Payments
                    case((cls.model.total_amount > 0, cls.model.total_amount), else_=0) - 
                    func.coalesce(pay_sub.c.total_paid, 0)
                ).label('calculated_balance')
            )
            .join(cls.model.order)
            .join(cls.model.purchase_order)
            .join(cls.model.client)
            .outerjoin(pay_sub, pay_sub.c.invoice_id == cls.model.id)
            .where(cls.model.is_active == True)
        )

        # 2.1. Eager load relationships for the list view
        stmt = stmt.options(
            contains_eager(cls.model.order),
            contains_eager(cls.model.purchase_order),
            contains_eager(cls.model.client)
        )

        # 3. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),
                    cls.model.invoice_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        # 4. Order by Registry creation (Newest first)
        stmt = stmt.order_by(OrderRegistry.created_at.desc())

        # 6. Calculate Total Items (for the pagination numbers)
        # 5.1. We create a count query derived from your main statement
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.session.execute(count_stmt).scalar()

        # 5.2. Fetch the Page of Items (keeping the tuples!)
        # Apply limit and offset manually
        paginated_stmt = stmt.limit(per_page).offset((page - 1) * per_page)
        
        # KEY DIFFERENCE: Use db.session.execute() instead of db.paginate()
        # This returns 'Row' objects containing (PurchaseOrder, calculated_balance)
        rows = db.session.execute(paginated_stmt).all()

        # 6.3. Unwrap and Attach Balance
        items = []
        for row in rows:
            invoice = row[0]              # The Invoice model
            invoice.balance = row[1]      # The calculated_balance
            invoice.total_due = max(0, invoice.total_amount) # The calculated_total_due
            items.append(invoice)

        # 6.4. Create the Pagination Object Manually
        return ManualPagination(items=items, page=page, per_page=per_page, total=total)
    
    @classmethod
    def add_invoice(cls, data: dict, items_data: list[dict]) -> Invoice:
        """
        Saves the Invoice header and items, inheriting Registry ID from the PO.
        Includes a Validation Guard to prevent 'Double Spending' of deposits.
        """

        # 1. Validate & Transform
        clean_data = cls._validate_and_transform(data)

        # 2. Double-Spending Guard
        cls._validate_deposit_usage(po_id=clean_data['po_id'], items_data=items_data)

        # 3. Create header (Inherits registry link from PO)
        invoice = cls.model(**clean_data)
        db.session.add(invoice)
        db.session.flush()

        # 4. Save items and calculate total
        cls._save_items(invoice, items_data)

        db.session.commit()
        return invoice
    
    @classmethod
    def edit_invoice(cls, id: int, data: dict, items_data: list[dict]) -> Invoice:
        """Atomic update of header and items with credit pool validation."""
        invoice = cls.get_invoice_by_id(id)
        if not invoice:
            raise ValueError("Invoice not found.")

        # 1. Validate & Transform
        clean_data = cls._validate_and_transform(data)

        # 2. Double-Spending Guard
        cls._validate_deposit_usage(po_id=clean_data['po_id'], items_data=items_data, invoice_id=id)

        # 3. Update Header
        for key, value in clean_data.items():
            setattr(invoice, key, value)

        # 4. Save items
        cls._save_items(invoice, items_data)

        db.session.commit()
        return invoice
    
    @classmethod
    def get_invoice_by_id(cls, id: int) -> Invoice | None:
        """
        Unified Invoice Fetcher:
        Returns the Invoice record augmented with .balance.
        Used for Cascades and Source-Driven logic.
        """
        # 1. Eager load Client, Bill-To, PO, and Order Registry
        stmt = (
            select(cls.model)
            .options(
                joinedload(cls.model.client).selectinload(Client.contacts),
                joinedload(cls.model.bill_to).selectinload(Client.contacts),
                joinedload(cls.model.purchase_order),
                joinedload(cls.model.order)
            )
            .where(cls.model.id == id)
        )
        invoice = db.session.execute(stmt).scalar_one_or_none()
        if not invoice:
            return None
        
        # 2. Total Paid toward this specific invoice
        pay_stmt = select(func.sum(Payment.amount)).where(
            Payment.invoice_id == invoice.id, 
            Payment.is_active == True
        )
        total_paid = db.session.execute(pay_stmt).scalar() or 0

        # 3. The total cash ever received for the linked PO (Initial pool)
        prepay_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == invoice.po_id, 
            Payment.invoice_id == None, 
            Payment.is_active == True
        )
        po_total_prepayment = db.session.execute(prepay_stmt).scalar() or 0
        
        # Attach dynamic UI attributes
        # Total Due: What they owe now (never negative)
        invoice.total_due = max(0, invoice.total_amount)
        # Remaining Credit: The remaining credit snapshot for this document (abs of negative total)
        invoice.remaining_credit = abs(min(0, invoice.total_amount))
        # Balance: Based on what is actually due after payments
        invoice.balance = invoice.total_due - total_paid
        # The total cash ever received for the linked PO (without invoices)
        invoice.po_total_prepayment = po_total_prepayment

        return invoice

    @classmethod
    def archive_invoice(cls, id: int):
        """
        Specialized archive for Invoices.
        Checks for active payments and returns (invoice, has_payments).
        """
        invoice = cls.get_invoice_by_id(id)
        if not invoice:
            return None, False

        # Check for active payments specifically linked to this invoice
        has_payments = any(p.is_active for p in invoice.payments)

        # Soft delete
        invoice.is_active = False
        db.session.commit()

        return invoice, has_payments
    
    @classmethod
    def get_invoices_by_po(cls, 
                           po_id: int, 
                           include_id: int | None = None, 
                           statuses: list[str] | None = None):
        """
        Fetcher: Returns 'open' invoices for a specific PO based on statuses.
        If include_id is provided, that specific invoice is included regardless of status.
        Used for the Payment, and  Expense creation dropdown.
        """
        # 1. Handle Default Statuses
        if statuses is None:
            statuses = ['open']

        # 2. Define the "Standard" criteria
        standard_criteria = (
            cls.model.status.in_(statuses),
        )

        # 3. Build statement
        stmt = select(cls.model).where(
            cls.model.po_id == po_id,
            cls.model.is_active == True,
            # Use OR to allow the currently linked Invoice to bypass status filters
            or_(
                *standard_criteria,
                cls.model.id == include_id
            )
        ).order_by(cls.model.invoice_date.desc())

        return db.session.execute(stmt).scalars().all()
    
    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Header validation and registry link inheritance."""
        po_id = data.get('po_id')
        if not po_id:
            raise ValueError("Source Purchase Order is required.")

        po = db.session.get(PurchaseOrder, int(po_id))
        if not po:
            raise ValueError("The selected Purchase Order does not exist.")

        # Parse dates
        raw_date = data.get('invoice_date')
        # Get TimeZone from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'

        if raw_date:
            invoice_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        else: 
            invoice_date = datetime.now(ZoneInfo(tz_name)).date()

        # Transform data
        clean_data = {
            'order_id': po.order_id,
            'po_id': po.id,
            'client_id': int(data.get('client_id', po.client_id)),
            'bill_to_id': int(data.get('bill_to_id', po.bill_to_id)),
            'invoice_number': data.get('invoice_number', '').strip(),
            'invoice_date': invoice_date,
            'tracking_number': data.get('tracking_number', '').strip(),
            'status': data.get('status', 'open'),
            'note': data.get('note', '').strip()
        }

        return clean_data
    
    @classmethod
    def _save_items(cls, invoice: Invoice, items_data: list[dict]):
        """Manages InvoiceItem snapshot and updates total_amount."""
        db.session.execute(db.delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))

        total_cents = 0
        for row in items_data:
            product_id = row.get('product_id')
            if product_id:
                description = row.get('description', '').strip()
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                item = InvoiceItem()
                item.invoice_id = invoice.id
                item.product_id = int(product_id)
                item.quantity = qty
                item.billed_unit_price = price
                item.description = description
                db.session.add(item)

        invoice.total_amount = total_cents

    @classmethod
    def _validate_deposit_usage(cls, po_id: int, items_data: list[dict], invoice_id: int | None = None):
        """Brain: Prevents over-spending the credit pool (Double-Spending guard)."""
        system_product = db.session.execute(
            select(Product.id).where(Product.is_system == True, Product.name == 'Applied Deposit')
        ).scalar()

        # 1. Calc Proposed Consumption
        proposed_total = 0
        proposed_dep_line = 0
        for row in items_data:
            qty = int(row.get('quantity', 1))
            price = parse_to_cents(str(row.get('unit_price', 0)))
            line = qty * price
            proposed_total += line
            if int(row.get('product_id', 0)) == system_product:
                proposed_dep_line = line
        
        proposed_consumption = abs(proposed_dep_line - min(0, proposed_total))

        # 2. Calc Total Cash Pool
        cash_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == po_id, Payment.invoice_id == None, Payment.is_active == True
        )
        total_cash = db.session.execute(cash_stmt).scalar() or 0

        # 3. Calc Consumption by all OTHER invoices
        other_lines = db.session.execute(
            select(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .join(Invoice).join(Product)
            .where(Invoice.po_id == po_id, Invoice.is_active == True, Product.is_system == True, Invoice.id != invoice_id)
        ).scalar() or 0

        other_negs = db.session.execute(
            select(func.sum(Invoice.total_amount)).where(
                Invoice.po_id == po_id, Invoice.is_active == True, Invoice.total_amount < 0, Invoice.id != invoice_id
            )
        ).scalar() or 0
        
        other_consumption = abs(other_lines - other_negs)

        if (other_consumption + proposed_consumption) > total_cash:
            available = max(0, total_cash - other_consumption)
            raise ValueError(f"Insufficient credit. Available: {format_usd(available)}")

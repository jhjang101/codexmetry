from .base_service import BaseService
from ..models import PurchaseOrder, PoItem, OrderRegistry, Client, Quote, Invoice, InvoiceItem, Payment
from ..extensions import db
from ..utils.docs import generate_doc_number
from sqlalchemy import select, or_, func
from ..utils.manual_pagination import ManualPagination

class PurchaseOrderService(BaseService):
    model = PurchaseOrder

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active POs with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name).
        Use subquery to calculate balance.
        """
        # 1. Subquery for Invoiced Sum
        inv_sub = (
            select(
                Invoice.po_id, 
                func.sum(Invoice.total_amount).label('total_invoiced')
            )
            .where(Invoice.is_active == True)
            .group_by(Invoice.po_id)
            .subquery()
        )

        # 2. Subquery for Invoiceless Payment Sum
        pay_sub = (
            select(
                Payment.po_id, 
                func.sum(Payment.amount).label('total_invoiceless')
            )
            .where(Payment.invoice_id == None, Payment.is_active == True)
            .group_by(Payment.po_id)
            .subquery()
        )

        # 3. Main Query with Calculated Balance Label
        stmt = (
            select(
                cls.model,
                (
                    cls.model.total_amount - 
                    func.coalesce(inv_sub.c.total_invoiced, 0) - 
                    func.coalesce(pay_sub.c.total_invoiceless, 0)
                ).label('calculated_balance')
            )
            .join(cls.model.order)
            .join(cls.model.client)
            .outerjoin(inv_sub, inv_sub.c.po_id == cls.model.id)
            .outerjoin(pay_sub, pay_sub.c.po_id == cls.model.id)
            .where(cls.model.is_active == True)
        )

        # 4. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term),
                    cls.model.po_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        # 5. Order by Registry creation (Newest first)
        stmt = stmt.order_by(OrderRegistry.created_at.desc())

        # 6. Calculate Total Items (for the pagination numbers)
        # 6.1. We create a count query derived from your main statement
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.session.execute(count_stmt).scalar()

        # 6.2. Fetch the Page of Items (keeping the tuples!)
        # Apply limit and offset manually
        paginated_stmt = stmt.limit(per_page).offset((page - 1) * per_page)
        
        # KEY DIFFERENCE: Use db.session.execute() instead of db.paginate()
        # This returns 'Row' objects containing (PurchaseOrder, calculated_balance)
        rows = db.session.execute(paginated_stmt).all()

        # 6.3. Unwrap and Attach Balance
        items = []
        for row in rows:
            po = row[0]              # The PurchaseOrder model
            po.balance = row[1]      # The calculated_balance
            print(po.balance)
            items.append(po)

        # 6.4. Create the Pagination Object Manually
        return ManualPagination(items=items, page=page, per_page=per_page, total=total)

    @classmethod
    def create_with_registry(cls, data: dict) -> PurchaseOrder:
        """
        Creates a new Order Registry entry and links the PO and Quote to it.
        """
        # 1. Generate the next CDX number using the registry model
        cdx_number = generate_doc_number(prefix='CDX', model=OrderRegistry, column_name='order_number')

        # 2. Create the Registry entry
        registry = OrderRegistry()
        registry.order_number = cdx_number
        db.session.add(registry)
        db.session.flush() # Flush to get registry.id before commit

        # 3. Create the Purchase Order
        client_id = data.get('client_id')
        quote_id = data.get('quote_id')
        bill_to_id = data.get('bill_to_id') or client_id # Fallback logic
        po_number = data.get('po_number') # Client's reference
        po_date = data.get('po_date')
        po_type_id = data.get('po_type_id')

        po = PurchaseOrder()
        po.order_id = registry.id
        po.quote_id = int(quote_id) if quote_id else None
        if client_id is None:
            raise ValueError("Client ID is required.")
        po.client_id = int(client_id)
        po.bill_to_id = int(bill_to_id) if bill_to_id else int(client_id)
        po.po_number = po_number 
        if po_date:
            po.po_date = po_date
        if po_type_id:
            po.po_type_id = po_type_id
        po.note = data.get('note')
        po.status = 'open'

        # 4. Link and Accept Quote if provided
        if po.quote_id:
            quote = db.session.get(Quote, po.quote_id)
            if quote:
                quote.status = 'accepted'
                quote.order_id = po.order_id # Share the Registry ID

        db.session.add(po)
        db.session.commit()
        return po
    
    @classmethod
    def update_po(cls, id: int, data: dict) -> PurchaseOrder | None:
        """
        Specialized update to handle 'Release & Re-link' logic for Quotes.
        """
        po = cls.get_by_id(id)
        if not po:
            return None

        old_quote_id = po.quote_id
        quote_id = data.get('quote_id')
        new_quote_id = int(quote_id) if quote_id else None

        # 1. If the quote changed, manage the states
        if old_quote_id != new_quote_id:
            # Release the old quote
            if old_quote_id:
                old_quote = db.session.get(Quote, old_quote_id)
                if old_quote:
                    old_quote.status = 'sent'
                    old_quote.order_id = None
            
            # Capture the new quote
            if new_quote_id:
                new_quote = db.session.get(Quote, new_quote_id)
                if new_quote:
                    new_quote.status = 'accepted'
                    new_quote.order_id = po.order_id

        # 2. Standard Update logic
        for key, value in data.items():
            if hasattr(po, key):
                setattr(po, key, value)

        db.session.commit()
        return po

    @classmethod
    def update_items(cls, po_id: int, items_data: list[dict]):
        """
        Wipes current PO items and re-inserts new ones.
        Updates the denormalized total_amount.
        """
        # 1. Remove old items
        delete_stmt = db.delete(PoItem).where(PoItem.po_id == po_id)
        db.session.execute(delete_stmt)

        total_cents = 0

        # 2. Add new items with explicit attribute setting for Pylance
        for data in items_data:
            raw_pid = data.get('product_id')
            if raw_pid:
                qty = int(data.get('quantity', 0))
                price = int(data.get('unit_price', 0))
                total_cents += (qty * price)

                new_item = PoItem()
                new_item.po_id = po_id
                new_item.product_id = int(raw_pid)
                new_item.quantity = qty
                new_item.agreed_unit_price = price
                db.session.add(new_item)

        # 3. Update parent total
        po = cls.get_by_id(po_id)
        if po:
            po.total_amount = total_cents
        
        db.session.commit()

    @classmethod
    def get_eligible_by_client(cls, client_id: int):
        """Returns Open pos for a specific client."""
        stmt = select(cls.model).where(
            cls.model.client_id == client_id,
            cls.model.is_active == True,
            cls.model.status.in_(['open', 'completed'])
        ).order_by(cls.model.po_date.desc())
        return db.session.execute(stmt).scalars().all()
    
    @classmethod
    def get_po_by_id(cls, id: int) -> PurchaseOrder | None:
        """
        Unified PO Fetcher:
        Returns the PO record augmented with .balance and .remaining_items.
        Used for Cascades and Source-Driven logic.
        """
        # 1. Fetch the base PO record
        po = cls.get_by_id(id)
        if not po:
            return None
        
        # 2. Calculate Balance total amount - sum of invoiced amount
        invoice_sum_stmt = select(func.sum(Invoice.total_amount)).where(
            Invoice.po_id == po.id,
            Invoice.is_active == True
        )
        total_invoiced = db.session.execute(invoice_sum_stmt).scalar() or 0

        invoiceless_payment_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == po.id,
            Payment.invoice_id == None, # Explicitly check for NULL
            Payment.is_active == True
        )
        total_invoiceless_paid = db.session.execute(invoiceless_payment_stmt).scalar() or 0

        po.balance = po.total_amount - total_invoiced - total_invoiceless_paid

        # 3. Calculate Remaining Items
        remaining_items = []
        for po_item in po.items:
            # Sum up how many of this product have already been invoiced for this PO
            already_invoiced_stmt = (
                select(func.sum(InvoiceItem.quantity))
                .join(InvoiceItem.invoice)
                .where(
                    Invoice.po_id == po.id,
                    InvoiceItem.product_id == po_item.product_id,
                    Invoice.is_active == True
                )
            )
            already_invoiced = db.session.execute(already_invoiced_stmt).scalar() or 0
            remaining_qty = po_item.quantity - already_invoiced

            # Only include items that haven't been fully invoiced
            if remaining_qty > 0:
                remaining_items.append({
                    'product_id': po_item.product_id,
                    'product': po_item.product,
                    'quantity': remaining_qty,
                    'agreed_unit_price': po_item.agreed_unit_price
                })
        po.remaining_items = remaining_items

        return po
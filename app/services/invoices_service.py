from .base_service import BaseService
from ..models import Invoice, InvoiceItem, PurchaseOrder, PoItem, OrderRegistry, Client, Payment
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from ..utils.manual_pagination import ManualPagination
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager
from datetime import datetime

class InvoiceService(BaseService):
    model = Invoice

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active Invoices with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name)
        Use subquery to calculate balance.
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
                    cls.model.total_amount - 
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
            print(invoice.balance)
            items.append(invoice)

        # 6.4. Create the Pagination Object Manually
        return ManualPagination(items=items, page=page, per_page=per_page, total=total)
    
    @classmethod
    def get_remaining_items(cls, po_id: int):
        """
        Logic for Partial Invoice
        Returns a list of dicts with product details and remaining quantity.
        """
        po = db.session.get(PurchaseOrder, po_id)
        if not po:
            return []

        remaining_items = []
        for po_item in po.items:
            # 1. Sum up how many of this product have already been invoiced for this PO
            already_invoiced_stmt = select(func.sum(InvoiceItem.quantity)).join(Invoice).where(
                Invoice.po_id == po_id,
                InvoiceItem.product_id == po_item.product_id,
                Invoice.is_active == True
            )
            already_invoiced = db.session.execute(already_invoiced_stmt).scalar() or 0

            # 2. Calculate what's left
            remaining_qty = po_item.quantity - already_invoiced
            
            # 3. Only suggest items that have a remaining balance
            if remaining_qty > 0:
                remaining_items.append({
                    'product_id': po_item.product_id,
                    'product': po_item.product,
                    'quantity': remaining_qty,
                    'billed_unit_price': po_item.agreed_unit_price # Default to PO price
                })
        
        return remaining_items
    
    @classmethod
    def create_invoice(cls, data: dict) -> Invoice:
        """Saves the Invoice header, inheriting Registry ID from the PO."""

        # 1. Define required fields
        required_fields = {
            'po_id': 'Purchase Order',
            'client_id': 'Client',
            'bill_to_id': 'Billing Entity',
            'invoice_number': 'Invoice Number'
        }

        # 2. Perform the validation loop
        for field, label in required_fields.items():
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{label} is required.")

        # 3. Look up the Purchase Order to get the order_id (Registry Link)
        po_id = data['po_id']
        po = db.session.get(PurchaseOrder, int(po_id))
        if not po:
            raise ValueError("The selected Purchase Order does not exist.")

        # 4. Read data
        client_id = data['client_id']
        bill_to_id = data['bill_to_id']
        invoice_number = data['invoice_number']
        invoice_date = data.get('invoice_date')
        tracking_number = data.get('tracking_number')
        note = data.get('note')

        # 5. Proceed to create the object
        invoice = Invoice()
        invoice.order_id = po.order_id
        invoice.po_id = po.id
        invoice.client_id = int(client_id)
        invoice.bill_to_id = int(bill_to_id)
        invoice.invoice_number = invoice_number.strip()
        if invoice_date:
            invoice.invoice_date = datetime.strptime(invoice_date, '%Y-%m-%d').date()
        invoice.tracking_number = tracking_number.strip() if tracking_number else ''
        invoice.note = note if note else ''

        # 6. Commit
        db.session.add(invoice)
        db.session.commit()

        return invoice
    
    @classmethod
    def update_invoice(cls, id: int, data: dict) -> Invoice | None:
        """Updates the Invoice header"""
        invoice = cls.get_by_id(id)
        if not invoice:
            return None

        # 1. Define required fields
        required_fields = {
            'po_id': 'Purchase Order',
            'client_id': 'Client',
            'bill_to_id': 'Billing Entity',
            'invoice_number': 'Invoice Number'
        }

        # 2. Perform the validation loop
        for field, label in required_fields.items():
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{label} is required.")

        # 3. Look up the Purchase Order to get the order_id (Registry Link)
        po_id = data['po_id']
        po = db.session.get(PurchaseOrder, int(po_id))
        if not po:
            raise ValueError("The selected Purchase Order does not exist.")

        # 4. Read data
        client_id = data['client_id']
        bill_to_id = data['bill_to_id']
        invoice_number = data['invoice_number']
        invoice_date = data.get('invoice_date')
        tracking_number = data.get('tracking_number')
        status = data.get('status')
        note = data.get('note')

        # 5. Transform data
        invoice_data = {
            'po_id': po.id,
            'order_id': po.order_id,
            'client_id': int(client_id),
            'bill_to_id': int(bill_to_id),
            'invoice_number': invoice_number.strip(),
            'invoice_date': datetime.strptime(invoice_date, '%Y-%m-%d').date() if invoice_date else None,
            'tracking_number': tracking_number.strip() if tracking_number else '',
            'status': status if status else None,
            'note': note if note else ''
        }

        # 6. Update the object
        for key, value in invoice_data.items():
            if hasattr(invoice, key):
                setattr(invoice, key, value)
        db.session.commit()

        return invoice
    
    @classmethod
    def update_items(cls, invoice_id: int, items_data: list[dict]):
        """
        Wipe current items and re-insert new ones.
        Calculates and updates the Invoice.total_amount denormalized column.
        """
        # 1. Delete old items
        delete_stmt = db.delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
        db.session.execute(delete_stmt)

        total_cents = 0

        # 2. Add new items
        for data in items_data:
            product_id = data.get('product_id')

            if product_id:
                product_id = int(product_id)
                qty = int(data.get('quantity', 1))
                price = parse_to_cents((data.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                new_item = InvoiceItem()
                new_item.invoice_id = invoice_id
                new_item.product_id = product_id
                new_item.quantity = qty
                new_item.billed_unit_price = price
                db.session.add(new_item)

        # 3. Update the Parent Total
        invoice = cls.get_by_id(invoice_id)
        if invoice:
            invoice.total_amount = total_cents
        
        db.session.commit()

    @classmethod
    def get_eligible_by_po(cls, po_id: int):
        """Returns active Invoices for a specific Purchase Order."""
        stmt = select(cls.model).where(
                cls.model.po_id == po_id,
                cls.model.is_active == True
            ).order_by(cls.model.invoice_date.desc())
        return db.session.execute(stmt).scalars().all()
    
    @classmethod
    def get_invoice_by_id(cls, id: int) -> Invoice | None:
        """
        Unified Invoice Fetcher:
        Returns the Invoice record augmented with .balance.
        Used for Cascades and Source-Driven logic.
        """
        # 1. Fetch the base Invoice record
        invoice = cls.get_by_id(id)
        if not invoice:
            return None
        
        # 2. Calculate Balance total amount - sum of paid amount
        payment_sum_stmt = select(func.sum(Payment.amount)).where(
            Payment.invoice_id == invoice.id,
            Payment.is_active == True
        )
        total_paid = db.session.execute(payment_sum_stmt).scalar() or 0
        invoice.balance = invoice.total_amount - total_paid

        return invoice


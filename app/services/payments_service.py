from .base_service import BaseService
from ..models import Payment, Invoice, PurchaseOrder, OrderRegistry, Client
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager
from datetime import datetime

class PaymentService(BaseService):
    model = Payment

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active Payments with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name)
        """
        # 1. Base statement
        stmt = (
            select(cls.model)
            .join(cls.model.order)
            .join(cls.model.client)
            .join(cls.model.purchase_order)
            .outerjoin(cls.model.invoice)
            .where(cls.model.is_active == True)
        )

        # Eager load relationships for the list view
        stmt = stmt.options(
            contains_eager(cls.model.order),
            contains_eager(cls.model.client),
            contains_eager(cls.model.purchase_order),
            contains_eager(cls.model.invoice) # Even the outer join can be eagerly loaded
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term), # CDX-YY0000
                    Client.company_name.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),   # Client's Ref PO #
                    Invoice.invoice_number.icontains(search_term),  # INV-YY0000
                )
            )

        # 3. Order by Registry creation (Newest first)
        stmt = stmt.order_by(OrderRegistry.created_at.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)

    @classmethod
    def create_payment(cls, data: dict) -> Payment:
        """Saves the Payment header, inheriting Registry ID from the PO or Invoice."""

        # 1. Define required fields
        required_fields = {
            'po_id': 'Purchase Order',
            'client_id': 'Client',
            'paid_from_id': 'Paid From',
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
        paid_from_id = data['paid_from_id']
        invoice_id = data.get('invoice_id')
        payment_type_id = data.get('payment_type_id')
        amount = data.get('amount')
        payment_date = data.get('payment_date')
        note = data.get('note')

        # 5. Proceed to create the object
        payment = Payment()
        payment.order_id = po.order_id
        payment.po_id = po.id
        payment.invoice_id = int(invoice_id) if invoice_id else None
        payment.client_id = int(client_id)
        payment.paid_from_id = int(paid_from_id)
        payment.amount = parse_to_cents(amount) if amount else 0
        payment.payment_type_id = int(payment_type_id) if payment_type_id else None
        if payment_date:
            payment.payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
        payment.note = note if note else ''

        # 6. Commit
        db.session.add(payment)
        db.session.commit()

        return payment
    
    @classmethod
    def update_payment(cls, id: int, data: dict) -> Payment | None:
        """Updates the Payment header"""
        payment = cls.get_by_id(id)
        if not payment:
            return None

        # 1. Define required fields
        required_fields = {
            'po_id': 'Purchase Order',
            'client_id': 'Client',
            'paid_from_id': 'Paid From',
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
        paid_from_id = data['paid_from_id']
        invoice_id = data.get('invoice_id')
        payment_type_id = data.get('payment_type_id')
        amount = data.get('amount')
        payment_date = data.get('payment_date')
        note = data.get('note')

        # 5. Transform data
        payment_data = {
            'po_id': po.id,
            'order_id': po.order_id,
            'invoice_id': int(invoice_id) if invoice_id else None,
            'client_id': int(client_id),
            'paid_from_id': int(paid_from_id),
            'payment_type_id': int(payment_type_id) if payment_type_id else None,
            'amount': parse_to_cents(amount) if amount else 0,
            'payment_date': datetime.strptime(payment_date, '%Y-%m-%d').date() if payment_date else None,
            'note': note if note else ''
        }
        
        # 6. Update the object
        for key, value in payment_data.items():
            if hasattr(payment, key):
                setattr(payment, key, value)
        db.session.commit()

        return payment
    
    @classmethod
    def archive_payment(cls, id: int):
        """
        Specialized archive for Payments with Credit Pool protection.
        """
        payment = cls.get_by_id(id)
        if not payment:
            return None

        # 1. Guard for Deposit Payments (Invoiceless)
        if payment.invoice_id is None:
            from .purchase_orders_service import PurchaseOrderService
            po = PurchaseOrderService.get_po_by_id(payment.po_id)
            
            # If the payment amount being deleted is greater than the current pool,
            # it means an invoice is currently "using" this cash.
            if po and payment.amount > po.remaining_deposit: # type: ignore
                from ..utils.money import format_usd
                raise ValueError(
                    f"Cannot archive this payment. {format_usd(payment.amount)} of credit "
                    f"is currently reserved by active invoices. Archive the invoices first."
                )

        # 2. Perform the Soft Delete
        payment.is_active = False
        db.session.commit()
        return payment
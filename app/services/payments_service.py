from .base_service import BaseService
from .purchase_orders_service import PurchaseOrderService
from ..models import Payment, Invoice, InvoiceItem, Product, PurchaseOrder, OrderRegistry, Client
from ..extensions import db
from ..utils.money import parse_to_cents, format_usd
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager
from datetime import datetime

class PaymentService(BaseService):
    model = Payment

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active Payments with search and pagination.
        Joins with OrderRegistry (CDX#), PO, Invoice, and Client (Name)
        """
        # 1. Base statement
        stmt = (
            select(cls.model)
            .join(cls.model.order)
            .join(cls.model.client)
            .join(cls.model.purchase_order)
            .outerjoin(cls.model.invoice) # Outer join because invoice is optional
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
    def add_payment(cls, data: dict) -> Payment:
        """
        Create new payment.
        Inherits Registry link from the Source document.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create object
        payment = cls.model(**clean_data)
        db.session.add(payment)
        
        db.session.commit()
        return payment
    
    @classmethod
    def edit_payment(cls, payment_id: int, data: dict) -> Payment:
        """
        Update existing payment.
        If credit has already been used by an invoice,
        the payment amount cannotbe reduced.
        """
        # 1. Validation
        payment = cls.get_by_id(payment_id)
        if not payment:
            raise ValueError("Payment not found.")
        
        # 1. GUARD FOR PREPAYMENT EDITS (Amount Reduction)
        if payment.invoice_id is None:
            po = PurchaseOrderService.get_po_by_id(payment.po_id)
            
            if po:
                new_amount = parse_to_cents(str(data.get('amount', 0)))
                # Calculate how much the user is trying to "Take Back" from the pool
                reduction = payment.amount - new_amount
                
                # You can only take back what hasn't been spent yet
                if reduction > po.remaining_credit: # type: ignore
                    raise ValueError(
                        f"Cannot reduce payment amount by {format_usd(reduction)}. "
                        f"Only {format_usd(po.remaining_credit)} of remaining credit is currently available." # type: ignore
                    )

        # 2. Standard Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Update header
        for key, value in clean_data.items():
            setattr(payment, key, value)

        db.session.commit()
        return payment
    
    @classmethod
    def archive_payment(cls, id: int) -> Payment | None:
        """
        Specialized archive with Credit Pool protection (Funding Deletion Guard).
        """
        payment = cls.get_by_id(id)
        if not payment:
            return None

        # 1. Guard for Prepayments (Invoiceless Payments)
        # If this is a deposit, we must ensure it hasn't been "spent" by a credit invoice.
        if payment.invoice_id is None:
            po = PurchaseOrderService.get_po_by_id(payment.po_id)
            
            # Check if deleting this cash would make the pool negative
            if po and payment.amount > po.remaining_credit: # type: ignore
                raise ValueError(
                    f"Cannot archive this payment. {format_usd(payment.amount)} of credit "
                    f"is currently reserved by active invoices. Archive the invoices first."
                )

        # 2. Perform the Soft Delete
        payment.is_active = False
        db.session.commit()
        return payment
    
    # --- INTERNAL HELPERS ---
    
    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles document linking and money parsing."""
        # 1. Validation
        client_id = data.get('client_id')
        po_id = data.get('po_id')
        paid_from_id = data.get('paid_from_id')
        
        if not client_id: raise ValueError("Client is required.")
        if not po_id: raise ValueError("Purchase Order is required.")
        if not paid_from_id: raise ValueError("Payer (Paid From) is required.")

        # 2. Look up the Purchase Order to get the order_id (Registry Link)
        po = db.session.get(PurchaseOrder, int(po_id))
        if not po:
            raise ValueError("The selected Purchase Order does not exist.")

        # 3. Transform data
        raw_date = data.get('payment_date')
        payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else datetime.now().date()
        invoice_id = data.get('invoice_id')
        payment_type_id = data.get('payment_type_id')

        clean_data = {
            'order_id': po.order_id, # Inherit from PO Registry
            'po_id': po.id,
            'invoice_id': int(invoice_id) if invoice_id else None,
            'client_id': int(client_id),
            'paid_from_id': int(paid_from_id),
            'payment_type_id': int(payment_type_id) if payment_type_id else None,
            'amount': parse_to_cents(str(data.get('amount', 0))),
            'payment_date': payment_date,
            'note': data.get('note', '').strip()
        }

        return clean_data

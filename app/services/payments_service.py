from .base_service import BaseService
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
        only the internal note can be modified.
        """
        # 1. Validation
        payment = cls.get_by_id(payment_id)
        if not payment:
            raise ValueError("Payment not found.")
        
        # 1. THE SNAPSHOT LOCK GUARD
        # If this is a prepayment and the credit is already in use
        if payment.invoice_id is None and cls._is_credit_used(payment.po_id):
            clean_data = cls._validate_and_transform(data)
            
            # Check if the user is trying to change anything OTHER than the note
            # We compare the submitted clean_data against the stored object
            restricted_fields = [
                'client_id', 'po_id', 'invoice_id', 'paid_from_id', 
                'payment_type_id', 'amount', 'payment_date'
            ]
            
            for field in restricted_fields:
                if getattr(payment, field) != clean_data.get(field):
                    raise ValueError(
                        "Foundation Lock: This payment's credit has already been applied to an active invoice. "
                        "Only the 'Internal Note' can be modified. To change financials, archive the invoices first."
                    )
            
            # Only update the note
            payment.note = clean_data.get('note', '')

        else:
            # 2. Validate & transform
            clean_data = cls._validate_and_transform(data)

            # 3. Update header
            for key, value in clean_data.items():
                setattr(payment, key, value)

        db.session.commit()
        return payment
    
    @classmethod
    def archive_payment(cls, id: int) -> Payment | None:
        """Soft delete with Snapshot Lock protection."""
        payment = cls.get_by_id(id)
        if not payment:
            return None

        if payment.invoice_id is None and cls._is_credit_used(payment.po_id):
            raise ValueError(
                "Foundation Lock: This payment's credit is currently in use by an invoice. "
                "Archive the invoices first before deleting the funding payment."
            )

        payment.is_active = False
        db.session.commit()
        return payment
    
    # --- INTERNAL HELPERS ---

    @classmethod
    def _is_credit_used(cls, po_id: int) -> bool:
        """Checks if any invoice for this PO has an 'Applied Deposit' line."""
        usage_stmt = (
            select(func.count(InvoiceItem.id))
            .join(Invoice).join(Product)
            .where(
                Invoice.po_id == po_id,
                Invoice.is_active == True,
                Product.is_system == True
            )
        )
        count = db.session.execute(usage_stmt).scalar() or 0
        return count > 0
    
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

        # 2. Document Resolution
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

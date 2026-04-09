from .base_service import BaseService
from .purchase_orders_service import PurchaseOrderService
from .attachment_service import AttachmentService
from ..models import Payment, Invoice, InvoiceItem, Product, PurchaseOrder, OrderRegistry, Client, SettingsMetadata
from .audit_service import AuditLogService
from .invoices_service import InvoiceService
from ..extensions import db
from ..utils.money import parse_to_cents, format_usd
from ..utils.sync import sync_invoice_status, sync_po_status
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, joinedload, selectinload, aliased
from datetime import datetime
from zoneinfo import ZoneInfo

class PaymentService(BaseService):
    model = Payment

    # Define Aliases for the two different Client joins
    client_alias = aliased(Client, name="client_alias")
    payer_alias = aliased(Client, name="payer_alias")

    # Define the Whitelist for sorting
    SORT_MAP = {
        'number': model.payment_number,
        'cdx': OrderRegistry.order_number,   # Joined via order_id
        'client': client_alias.company_name, # Sorts by the Account Owner
        'invoice': Invoice.invoice_number,   # Joined via invoice_id
        'payer': payer_alias.company_name,   # Sorts by the person on the check
        'amount': model.amount,
        'date': model.payment_date
    }



    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
        """
        Fetches active Payments with search and pagination.
        Joins with OrderRegistry (CDX#), PO, Invoice, and Client (Name)
        """
        # 1. Base statement
        stmt = (
            select(cls.model)
            .join(cls.model.order)
            .join(cls.model.purchase_order)
            .join(cls.client_alias, cls.model.client_id == cls.client_alias.id)     # Join 1
            .join(cls.payer_alias, cls.model.paid_from_id == cls.payer_alias.id)    # Join 2
            .outerjoin(cls.model.invoice) # Outer join because invoice is optional
            .outerjoin(cls.model.payment_type)
            .where(cls.model.is_active == True)
        )

        # Eager load relationships for the list view
        stmt = stmt.options(
            contains_eager(cls.model.order),
            contains_eager(cls.model.purchase_order),
            contains_eager(cls.model.client, alias=cls.client_alias),
            contains_eager(cls.model.paid_from, alias=cls.payer_alias),
            contains_eager(cls.model.invoice),
            contains_eager(cls.model.payment_type)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term), # CDX-YY0000
                    cls.model.payment_number.icontains(search_term),
                    cls.client_alias.company_name.icontains(search_term),
                    cls.payer_alias.company_name.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),   # Client's Ref PO #
                    Invoice.invoice_number.icontains(search_term),  # I-YY0000
                )
            )

        # 3. Apply Sorting using the BaseService helper
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.payment_date # Default: newest first
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page,
                            sort_by=sort_by, 
                            direction=direction)
    
    @classmethod
    def add_payment(cls, data: dict, new_files=None):
        """
        Create new payment.
        Inherits Registry link from the Source document.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Stage object
        payment = cls.model(**clean_data)
        db.session.add(payment)
        db.session.flush()

        # 3. Stage Attahments
        AttachmentService.stage('Payment', payment.id, new_files=new_files)

        # 4. Flush and Hydrate
        db.session.flush()
        db.session.refresh(payment)

        # 5. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(payment.attachments)

        # 6. Record 'CREATE' Audit
        parent_audit_id = AuditLogService.record(
            target_id=payment.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )

        # 7. Invoice Status Ripple
        if payment.invoice_id:
            invoice = InvoiceService.get_invoice_by_id(payment.invoice_id)
            invoice_status = sync_invoice_status(invoice, 
                                                 original_status = invoice.status, # type: ignore
                                                 parent_id=parent_audit_id)
        else:
            invoice_status = None
        
        # 8. PO Status Ripple
        if payment.po_id:
            po_status = sync_po_status(payment.po_id, parent_id=parent_audit_id)
        else:
            po_status = None

        db.session.commit()
        return payment, invoice_status, po_status
    
    @classmethod
    def edit_payment(cls, payment_id: int, data: dict, new_files=None, delete_ids=None):
        """
        Update existing payment.
        If credit has already been used by an invoice,
        the payment amount cannotbe reduced.
        """
        payment = cls.get_payment_by_id(payment_id)
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

        # 3. Original State Capture
        old_po_id = payment.po_id
        old_invoice_id = payment.invoice_id
        old_snapshot = cls._get_snapshot(payment)
        old_snapshot['attachments'] = AttachmentService._get_fingerprint(payment.attachments)

        # 4. Stage header
        for key, value in clean_data.items():
            setattr(payment, key, value)

        # 5. Stage Attachments
        AttachmentService.stage('Payment', payment_id, new_files=new_files, delete_ids=delete_ids)

        # 6. Flush and Hydrate
        db.session.flush()

        # 7. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(payment.attachments)

        # 8. Record 'UPDATE' Audit
        parent_audit_id = AuditLogService.record(
            payment_id, 
            cls.model.__name__, 
            'UPDATE', 
            old_data=old_snapshot, 
            new_data=new_snapshot
        )
        
        # 9. Invoice Status Ripple
        if old_invoice_id and old_invoice_id != payment.invoice_id:
            old_invoice = InvoiceService.get_invoice_by_id(old_invoice_id)
            old_invoice_status = sync_invoice_status(old_invoice, 
                                                     original_status = old_invoice.status, # type: ignore
                                                     parent_id=parent_audit_id)
        else:
            old_invoice_status = None
        
        if payment.invoice_id:
            new_invoice = InvoiceService.get_invoice_by_id(payment.invoice_id)
            new_invoice_status = sync_invoice_status(new_invoice, 
                                                     original_status = new_invoice.status, # type: ignore 
                                                     parent_id=parent_audit_id)
        else:
            new_invoice_status = None

        # 10. PO Status Ripple
        if old_po_id and old_po_id != payment.po_id:
            old_po_status = sync_po_status(old_po_id, parent_id=parent_audit_id)
        else:
            old_po_status = None
        
        if payment.po_id:
            new_po_status = sync_po_status(payment.po_id, parent_id=parent_audit_id)
        else:
            new_po_status = None

        # 11. Atomic Commit
        db.session.commit()

        return payment, old_invoice_status, new_invoice_status, old_po_status, new_po_status 
    
    @classmethod
    def archive_payment(cls, payment_id: int):
        """
        Specialized archive with Credit Pool protection (Funding Deletion Guard).
        """
        payment = cls.get_payment_by_id(payment_id)
        if not payment:
            return None, None, None

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

        # 2. Forensic Record before we flip the bit
        parent_audit_id = AuditLogService.record(
            target_id=payment_id, 
            target_type=cls.model.__name__, 
            action='ARCHIVE', 
            old_data={'is_active': True}, 
            new_data={'is_active': False}
        )

        # 3. Perform the Soft Delete
        payment.is_active = False

        # 4. Invoice Status Ripple
        if payment.invoice_id:
            invoice = InvoiceService.get_invoice_by_id(payment.invoice_id)
            invoice_status = sync_invoice_status(invoice, 
                                                 original_status = invoice.status, #type: ignore
                                                 parent_id=parent_audit_id)
        else:
            invoice_status = None

        # 5. PO Status Ripple
        if payment.po_id:
            po_status = sync_po_status(payment.po_id, parent_id=parent_audit_id)
        else:
            po_status = None

        # 6. Commit
        db.session.commit()

        return payment, invoice_status, po_status
    
    @classmethod
    def get_payment_by_id(cls, id: int) -> Payment | None:
        """
        Fetcher: Returns Payment with eager-loaded Client (and contacts), 
        Payer (and contacts), and all Registry links (Order, PO, Invoice).
        Prevents N+1 queries when using .full_display or viewing hierarchy refs.
        """
        stmt = (
            select(cls.model)
            .options(
                # 1. Load the primary Client and their contacts for display
                joinedload(cls.model.client).selectinload(Client.contacts),
                # 2. Load the Payer (Paid From) and their contacts
                joinedload(cls.model.paid_from).selectinload(Client.contacts),
                # 3. Load lookup and registry references
                joinedload(cls.model.order),
                joinedload(cls.model.purchase_order),
                joinedload(cls.model.invoice),
                joinedload(cls.model.payment_type)
            )
            .where(cls.model.id == id)
        )
        return db.session.execute(stmt).scalar_one_or_none()
    
    # --- INTERNAL HELPERS ---
    
    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles document linking and money parsing."""
        # 1. Validation
        client_id = data.get('client_id')
        payment_number = data.get('payment_number', '').strip()
        po_id = data.get('po_id')
        invoice_id = data.get('invoice_id')
        payment_type_id = data.get('payment_type_id')
        paid_from_id = data.get('paid_from_id')
        
        if not client_id: 
            raise ValueError("Client is required.")
        if not payment_number:
            raise ValueError("Payment Number is required.")
        if not po_id: 
            raise ValueError("Purchase Order is required.")
        if not payment_type_id: 
            raise ValueError("Payment Type is required.")
        if not paid_from_id: 
            raise ValueError("Payer (Paid From) is required.")
        
        # If no invoice_id provided (Prepayment attempt)
        if not invoice_id:
            po = db.session.get(PurchaseOrder, po_id)
            if po and po.status != 'open':
                raise ValueError(f"Prepayments are not allowed for PO {po.po_number or po.order.order_number} because it is already fully invoiced.")

        # 2. Look up the Purchase Order to get the order_id (Registry Link)
        po = db.session.get(PurchaseOrder, int(po_id))
        if not po:
            raise ValueError("The selected Purchase Order does not exist.")

        # Parse dates
        raw_date = data.get('payment_date')
        # Get TimeZone from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'

        if raw_date:
            payment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        else: 
            payment_date = datetime.now(ZoneInfo(tz_name)).date()

        invoice_id = data.get('invoice_id')
        payment_type_id = data.get('payment_type_id')

        # 3. Transform data
        clean_data = {
            'client_id': int(client_id),
            'payment_number': payment_number,
            'order_id': po.order_id, # Inherit from PO Registry
            'po_id': po.id,
            'invoice_id': int(invoice_id) if invoice_id else None,
            'paid_from_id': int(paid_from_id),
            'payment_type_id': int(payment_type_id) if payment_type_id else None,
            'amount': parse_to_cents(str(data.get('amount', 0))),
            'payment_date': payment_date,
            'note': data.get('note', '').strip()
        }

        return clean_data

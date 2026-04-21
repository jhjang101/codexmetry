from .base_service import BaseService
from ..models import Invoice, InvoiceItem, PurchaseOrder, OrderRegistry, Client, Payment, Product, SettingsMetadata, Adjustment, Attachment
from .audit_service import AuditLogService
from .attachment_service import AttachmentService
from .adjustments_service import AdjustmentService
from ..extensions import db
from ..utils.money import parse_to_cents, format_usd
from ..utils.manual_pagination import ManualPagination
from ..utils.sync import sync_invoice_status, sync_po_status
from ..utils.pdf import save_pdf_from_html
from sqlalchemy import select, or_, func, case
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

class InvoiceService(BaseService):
    model = Invoice

    # Define the Whitelist (Maps UI strings to Database Columns)
    SORT_MAP = {
        'status': model.status,
        'number': model.invoice_number,
        'po': PurchaseOrder.po_number,
        'client': Client.company_name,
        'amount': model.total_amount,
        'date': model.invoice_date,
        'balance': 'calculated_balance', # SQLAlchemy can sort by the label string
        # Special Case: Sorting by 'calculated_balance' (row[1] in your subquery)
        # We'll handle this manually in the service if needed, 
        # but usually, sorting by 'amount' or 'date' is enough for AR.
    }

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10, 
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
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
        
        # 4. Apply Sorting using the BaseService helper
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.invoice_date # Default: newest first
        )

        # 5. Calculate Total Items (for the pagination numbers)
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
            # invoice.total_due is calculated in model @property
            # invoice.total_due = max(0, invoice.total_amount) # The calculated_total_due
            items.append(invoice)

        # 6.4. Create the Pagination Object Manually
        return ManualPagination(items=items, 
                                page=page, 
                                per_page=per_page, 
                                total=total,
                                sort_by=sort_by,
                                direction=direction)
    
    @classmethod
    def add_invoice(cls, data: dict, items_data: list[dict], new_files=None):
        """
        Saves the Invoice header and items, inheriting Registry ID from the PO.
        Includes a Validation Guard to prevent 'Double Spending' of deposits.
        """

        # 1. Validate & Transform
        clean_data = cls._validate_and_transform(data)

        # 2. Guards
        # 2.1. Prepayment Check: Prepayment invoice can not mix with product invoice.
        # returns True if this is a PRE-PMT invoice
        is_prepmt = cls._validate_pure_prepayment(items_data)

        # 2.2. Double-Spending Guard: Consumption of prepayment cannot be more than total prepayment
        # We do not check for Prepayment invoice
        if not is_prepmt:
            cls._validate_deposit_usage(po_id=clean_data['po_id'], items_data=items_data)

        # 3. Stage header (Inherits registry link from PO)
        invoice = cls.model(**clean_data)
        db.session.add(invoice)
        db.session.flush()

        # 4. Stage items and calculate total
        new_items_fingerprint = cls._stage_items(invoice, items_data)

        # 5. Stage Attahments    
        AttachmentService.stage('Invoice', invoice.id, new_files=new_files)

        # 6. Flush and Hydrate
        db.session.flush()
        cls.get_invoice_by_id(invoice.id)

        # 7. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['line_items'] = new_items_fingerprint
        new_snapshot['total_amount'] = invoice.total_amount
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(invoice.attachments)

        # 8. Record 'CREATE' Audit
        parent_audit_id = AuditLogService.record(
            target_id=invoice.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        ) 
        
        # 9. Update Invoice Status
        invoice_status = sync_invoice_status(invoice, parent_id=parent_audit_id)

        # 10. PO Status Ripple
        po_status = sync_po_status(invoice.po_id, parent_id=parent_audit_id)
        
        db.session.commit()
        return invoice, invoice_status, po_status
    
    @classmethod
    def edit_invoice(cls, 
                     invoice_id: int, 
                     data: dict, 
                     items_data: list[dict],
                     new_files=None, 
                     delete_ids=None):
        """Atomic update of header, items, and attachments with credit pool validation."""
        invoice = cls.get_invoice_by_id(invoice_id)
        if not invoice:
            raise ValueError("Invoice not found.")

        # 1. Validate & Transform
        clean_data = cls._validate_and_transform(data)

        # 2. Guard
        # Locking guard: if invoice have payments prevent switching client and po link
        new_client_id = data.get('client_id')
        if new_client_id and int(new_client_id) != invoice.client_id:
            if invoice.has_active_payments: # type: ignore
                raise ValueError("Cannot change Client: active payments exist for this invoice.")
        new_po_id = data.get('po_id')
        if new_po_id and int(new_po_id) != invoice.po_id:
            if invoice.has_active_payments: # type: ignore
                raise ValueError("Cannot change Purchase Order link: this invoice already has active payments.")
            
        # Prepayment Check: Prepayment invoice can not mix with product invoice.
        is_prepmt = cls._validate_pure_prepayment(items_data)

        # Double-Spending Guard: Consumption of prepayment cannot be more than total prepayment
        # We do not check for Prepayment invoice
        if not is_prepmt:
            cls._validate_deposit_usage(po_id=clean_data['po_id'], items_data=items_data, invoice_id=invoice_id)

        # 3. Original State Capture
        old_po_id = invoice.po_id
        old_snapshot = cls._get_snapshot(invoice)
        old_snapshot['line_items'] = cls._get_items_fingerprint(invoice.items, 'quantity', 'billed_unit_price')
        old_snapshot['attachments'] = AttachmentService._get_fingerprint(invoice.attachments)
        
        # 4. Stage Header
        for key, value in clean_data.items():
            setattr(invoice, key, value)
        
        # 5. Stage items
        new_items_fingerprint = cls._stage_items(invoice, items_data)

        # 6. Stage Attachments
        AttachmentService.stage('Invoice', invoice_id, new_files=new_files, delete_ids=delete_ids)

        # 7. Flush and Hydrate
        db.session.flush()
        cls.get_invoice_by_id(invoice_id)

        # 8. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['line_items'] = new_items_fingerprint
        new_snapshot['total_amount'] = invoice.total_amount
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(invoice.attachments)

        # 9. Record 'UPDATE' Audit
        parent_audit_id = AuditLogService.record(
            invoice_id, 
            cls.model.__name__, 
            'UPDATE', 
            old_data=old_snapshot, 
            new_data=new_snapshot
        )
        
        # 10. Update Invoice Status
        invoice_status = sync_invoice_status(invoice, old_snapshot['status'], clean_data['status'], parent_id=parent_audit_id)

        # 11. PO Status Ripple
        new_po_status = sync_po_status(invoice.po_id, parent_id=parent_audit_id)
        
        old_po_status = None
        if old_po_id != invoice.po_id:
            old_po_status = sync_po_status(old_po_id, parent_id=parent_audit_id)

        #12. Atomic Commit
        db.session.commit()

        return invoice, invoice_status, old_po_status, new_po_status
    
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
                joinedload(cls.model.order),
                joinedload(cls.model.carrier),
                selectinload(cls.model.items).joinedload(InvoiceItem.product),
                selectinload(cls.model.payments)
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

        # 3. The invoiceless payments ever received for the linked PO (Initial pool)
        unlinked_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == invoice.po_id, 
            Payment.invoice_id == None, 
            Payment.is_active == True
        )
        unlinked_prepayment = db.session.execute(unlinked_stmt).scalar() or 0

        # 3. Payments to PRE-PMT invoices
        # We find all invoices for this PO where items are only PRE-PMT
        # This is a bit heavy for a property, so we use a filtered query
        prepmt_inv_stmt = select(Invoice.id).join(InvoiceItem).join(Product).where(
            Invoice.po_id == invoice.po_id,
            Invoice.is_active == True
        ).group_by(Invoice.id).having(
            func.sum(case((Product.catalog_number != 'PRE-PMT', 1), else_=0)) == 0
        )
        
        linked_prepay_stmt = select(func.sum(Payment.amount)).where(
            Payment.invoice_id.in_(prepmt_inv_stmt),
            Payment.is_active == True
        )

        linked_prepayment = db.session.execute(linked_prepay_stmt).scalar() or 0
        
        # Attach dynamic UI attributes
        # Total Due: What they owe now (never negative)
        # invoice.total_due is calculated in model @property
        # invoice.total_due = max(0, invoice.total_amount) # The calculated_total_due

        # Remaining Credit: The remaining credit snapshot for this document (abs of negative total)
        invoice.remaining_credit = abs(min(0, invoice.total_amount))
        # Balance: Based on what is actually due after payments
        invoice.balance = invoice.total_due - total_paid
        # The total cash ever received for the linked PO (without invoices)
        invoice.po_total_prepayment = unlinked_prepayment + linked_prepayment

        # Check is invoice has active payment for locking edit.
        invoice.has_active_payments = any(payment.is_active for payment in invoice.payments)

        return invoice

    @classmethod
    def archive_invoice(cls, id: int):
        """
        Specialized archive for Invoices.
        Checks for active payments and a result dictionary with document numbers for UI feedback
        """
        invoice = cls.get_invoice_by_id(id)
        if not invoice:
            return None
        
        # 1. Initialize Result Collection
        results = {
            'invoice_num': invoice.invoice_number,
            'po_ref': invoice.purchase_order.po_number or invoice.order.order_number,
            'deleted_adjustments': [],
            'active_payments': [p.payment_number for p in invoice.payments if p.is_active],
            'po_status': None
        }

        # 2. Audit Record of the primary action
        parent_audit_id = AuditLogService.record(
            target_id=id, 
            target_type=cls.model.__name__, 
            action='ARCHIVE', 
            old_data={'is_active': True}, 
            new_data={'is_active': False}
        )

        # 3. Soft delete
        invoice.is_active = False

        # 4. Ripple Delete Adjustments and Record Audit
        adj_res = AdjustmentService.reconcile_writeoff(invoice, parent_id=parent_audit_id)
        if adj_res and adj_res.get('action') == 'DELETE':
            results['deleted_adjustments'].append(adj_res['number'])

        # 5. PO Status Ripple
        results['po_status'] = sync_po_status(invoice.po_id, parent_id=parent_audit_id)

        # Commit
        db.session.commit()

        return results
    
    @classmethod
    def get_invoices_by_po(cls, 
                           po_id: int, 
                           include_id: int | None = None, 
                           statuses: list[str] | None = None):
        """
        Fetcher: Returns 'open' and 'draft' invoices for a specific PO based on statuses.
        If include_id is provided, that specific invoice is included regardless of status.
        Used for the Payment, and  Expense creation dropdown.
        """
        # 1. Handle Default Statuses
        if statuses is None:
            statuses = ['open', 'draft']

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
    
    @classmethod
    def issue_invoice(cls, id: int, notes: str):
        """
        Transitions Invoice and save PDF as Attatchment.
        Performs item bucketing, versioned PDF generation, triggers system ripples, and Audit logging.
        """
        # 1. Fetch hydrated object (includes .balance and .po_total_prepayment)
        invoice = cls.get_invoice_by_id(id)
        if not invoice or not invoice.is_active:
            return None, None, None
        
        # 2. Preparation: Internal Item Bucketing & Ledger Math
        line_display_items = []
        subtotal = tax_total = shipping_total = 0
        for item in invoice.items:
            val = item.quantity * item.billed_unit_price
            p = item.product.document_placement
            if p == 'Tax': tax_total += val
            elif p == 'Shipping': shipping_total += val
            else:
                line_display_items.append(item)
                subtotal += val

        active_payments = [p for p in invoice.payments if p.is_active]
        total_received = sum(p.amount for p in active_payments)

        # 2.1. total_amount Cross Check
        calculated_total = subtotal + tax_total + shipping_total
        if calculated_total != invoice.total_amount:
            raise ValueError(
                f"Integrity Error: The saved Invoice total ({format_usd(invoice.total_amount)}) "
                f"does not match the calculated sum of its items ({format_usd(calculated_total)}). "
                "Please edit and re-save the Invoice before issuing."
            )

        # 3. Term & Date Logic for PDF
        metadata = db.session.get(SettingsMetadata, 1)
        net_days = invoice.net_days if invoice.net_days is not None else (metadata.default_net_days if metadata else 30)
        due_date = invoice.invoice_date + timedelta(days=net_days)

        # 4. Versioning Logic: Count existing generated snapshots
        v_count = db.session.query(func.count(Attachment.id)).filter_by(
            entity_type='Invoice', 
            entity_id=id, 
            is_generated=True
        ).scalar() or 0
        version = v_count + 1
        
        # 5. Capture current state for Audit
        old_snapshot = cls._get_snapshot(invoice)

        # 6. Physical Archival (PDF Generation)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"Invoice_{invoice.invoice_number}_{timestamp}_v{version}.pdf"

        # Construct the data package for WeasyPrint
        context_data = {
            'invoice': invoice,
            'line_display_items': line_display_items,
            'subtotal': subtotal,
            'tax_total': tax_total,
            'shipping_total': shipping_total,
            'total_received': total_received,
            'active_payments': active_payments,
            'due_date': due_date,
            'net_days': net_days,
            'transient_notes': notes
        }

        # Select template based on current payment status
        template = 'invoices/print_paid.html' if invoice.status == 'completed' else 'invoices/print.html'
        save_pdf_from_html(template, context_data, filename, subfolder='invoices')

        # 7. Database Updates (State & Linkage)
        before = invoice.status
        if before == 'draft':
            invoice.status = 'open'
        invoice.terms_snapshot = notes

        # Create the Forensic Attachment record
        new_snapshot = Attachment()
        new_snapshot.entity_type = 'Invoice'
        new_snapshot.entity_id = id
        new_snapshot.file_path = filename
        new_snapshot.file_name = filename
        new_snapshot.is_generated = True
        db.session.add(new_snapshot)

        # 8. Forensic Trail: Record the ISSUE action
        parent_audit_id = AuditLogService.record(
            target_id=id,
            target_type='Invoice',
            action='ISSUE',
            old_data=old_snapshot,
            new_data={
                'status': invoice.status,
                'terms_snapshot': notes,
                'snapshot_file': filename
            }
        )

        # 9. System Ripples (Sync status and PO)
        # Note: We pass the 'parent_audit_id' so ripples are nested in the timeline
        invoice_status_ripple = sync_invoice_status(invoice, original_status='open', parent_id=parent_audit_id)
        invoice_status_ripple['before'] = before # Correct UI feedback (Draft -> Final Status)
        po_status_ripple = sync_po_status(invoice.po_id, parent_id=parent_audit_id)

        db.session.commit()
        return invoice, invoice_status_ripple, po_status_ripple
    
        
        # before = invoice.status
        # if before == 'draft':
        #     # 1. CAPTURE FULL FORENSIC SNAPSHOT (Matching Quote pattern)
        #     snapshot = cls._get_snapshot(invoice)
        #     snapshot['line_items'] = cls._get_items_fingerprint(invoice.items, 'quantity', 'billed_unit_price')
        #     # We manually set the target status for the notarized record
        #     snapshot['status'] = 'open' 

        #     # 2. RECORD THE PARENT "ISSUE" ACTION (Full dump)
        #     parent_audit_id = AuditLogService.record(
        #         target_id=id,
        #         target_type=cls.model.__name__,
        #         action='ISSUE',
        #         old_data={}, # Forces full snapshot
        #         new_data=snapshot
        #     )

        #     # 3. ADVANCE STATUS & RIPPLE
        #     invoice.status = 'open'
            
        #     # 4. RUN SYSTEM RIPPLES (Linked to Parent)
        #     invoice_status = sync_invoice_status(invoice, original_status='open', parent_id=parent_audit_id)
        #     invoice_status['before'] = before # Correct UI feedback (Draft -> Final Status)
            
        #     po_status = sync_po_status(invoice.po_id, parent_id=parent_audit_id)

        #     db.session.commit()
        #     return invoice, invoice_status, po_status
        
        # return invoice, None, None
    
    @classmethod
    def _validate_pure_prepayment(cls, items_data: list[dict]) -> bool:
        """
        Brain: Enforces the 'Prepayment Check' rule.
        Returns True if the invoice is a Prepayment Request.
        Raises ValueError if PRE-PMT is mixed with other products.
        """
        prepmt_count = 0
        total_items = len(items_data)

        for row in items_data:
            pid = row.get('product_id')
            if not pid: continue
            
            product = db.session.get(Product, int(pid))
            if product and product.catalog_number == 'PRE-PMT':
                prepmt_count += 1

        if prepmt_count > 0:
            # RULE 1: Only 1 line allowed
            if total_items > 1:
                raise ValueError("Prepayment Request invoices cannot contain multiple line items or mixed products.")
            
            # RULE 2: Return True to signify this is a special invoice
            return True
            
        return False
    
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

        # Get Defaults from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'
        default_net_days = metadata.default_net_days if metadata else 30

        # 1. Parse dates
        raw_date = data.get('invoice_date')
        if raw_date:
            invoice_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        else: 
            invoice_date = datetime.now(ZoneInfo(tz_name)).date()

        # 2. Resolve Net Days (The Snapshot Rule)
        raw_net = data.get('net_days')
        if raw_net and str(raw_net).strip():
            try:
                net_days = int(raw_net)
                if net_days < 0: raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Payment Terms (Net Days) must be a valid positive number.")
        elif po and po.net_days is not None:
            # Fallback 1: Use terms snapshot from the PO
            net_days = po.net_days
        else:
            # Fallback 2: Use global system default
            net_days = default_net_days

        # 3. Resolve Customer PO Number (Inheritance Rule)
        customer_po = data.get('customer_po_number', '').strip()
        if not customer_po and po:
            customer_po = po.customer_po_number

        raw_ship_date = data.get('ship_date')
        carrier_id = data.get('carrier_id')

        # Transform data
        clean_data = {
            'order_id': po.order_id,
            'po_id': po.id,
            'client_id': int(data.get('client_id', po.client_id)),
            'bill_to_id': int(data.get('bill_to_id', po.bill_to_id)),
            'invoice_number': data.get('invoice_number', '').strip(),
            'customer_po_number': customer_po, # Resolved inheritance
            'net_days': net_days, # Resolved snapshot
            'invoice_date': invoice_date,
            'ship_date': datetime.strptime(raw_ship_date, '%Y-%m-%d').date() if raw_ship_date else None,
            'carrier_id': int(carrier_id) if carrier_id else None,
            'tracking_number': data.get('tracking_number', '').strip(),
            'status': data.get('status', 'draft'),
            'note': data.get('note', '').strip()
        }

        return clean_data
    
    @classmethod
    def _stage_items(cls, invoice: Invoice, items_data: list[dict]):
        """Manages InvoiceItem snapshot and updates total_amount."""
        db.session.execute(db.delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))

        total_cents = 0
        fingerprint = []

        for idx, row in enumerate(items_data, start=1):
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
                item.po_item_id = row.get('po_item_id')
                item.sort_order = idx 
                db.session.add(item)

                # Generate fingerprint
                product = db.session.get(Product, product_id)
                fingerprint.append({
                    'product_id': int(product_id),
                    'product': product.name if product else "Unknown",
                    'quantity': qty, 
                    'unit_price': price,
                    'description': description,
                    'sort_order': idx,
                    'po_item_id': item.po_item_id
                })

        invoice.total_amount = total_cents

        return sorted(fingerprint, key=lambda x: x['sort_order'])

    @classmethod
    def _validate_deposit_usage(cls, po_id: int, items_data: list[dict], invoice_id: int | None = None):
        """Brain: Prevents over-spending the credit pool (Double-Spending guard)."""
        system_product = db.session.execute(
            select(Product.id).where(Product.is_system == True, Product.name == 'Applied Deposit')
        ).scalar()

        # 1. Calc Proposed Consumption (Current Invoice)
        proposed_total = 0
        proposed_dep_line = 0
        for row in items_data:
            qty = int(row.get('quantity', 1))
            price = parse_to_cents(str(row.get('unit_price', 0)))
            line = qty * price
            proposed_total += line
            if int(row.get('product_id', 0)) == system_product:
                proposed_dep_line = line

        # The amount of credit used to pay for products
        proposed_consumption = abs(proposed_dep_line - min(0, proposed_total))

        # 2. Calc Total Cash Pool (include invoiceless and linked prepayment)
        # Linked Prepayments
        prepmt_inv_stmt = select(Invoice.id).join(InvoiceItem).join(Product).where(
            Invoice.po_id == po_id,
            Invoice.is_active == True
        ).group_by(Invoice.id).having(
            func.sum(case((Product.catalog_number != 'PRE-PMT', 1), else_=0)) == 0
        )
        # Invoiceless Payments + Linked Prepayments
        cash_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == po_id, 
            Payment.is_active == True,
            or_(
                Payment.invoice_id == None,
                Payment.invoice_id.in_(select(prepmt_inv_stmt.c.id))
            )
        )
        total_cash = db.session.execute(cash_stmt).scalar() or 0

        # 3. Calc Consumption by all OTHER invoices
        other_lines = db.session.execute(
            select(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .join(Invoice).join(Product)
            .where(Invoice.po_id == po_id, Invoice.is_active == True, Product.name == 'Applied Deposit', Invoice.id != invoice_id)
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

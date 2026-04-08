from .base_service import BaseService
from ..models import (Adjustment, AdjustmentCategory, 
                      Client, Invoice, SettingsMetadata, 
                      OrderRegistry, PurchaseOrder)
from .audit_service import AuditLogService
from .attachment_service import AttachmentService
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager, joinedload
from datetime import datetime
from zoneinfo import ZoneInfo

class AdjustmentService(BaseService):
    model = Adjustment

    # Define the Whitelist for sorting
    SORT_MAP = {
        'number': model.adjustment_number,
        'description': model.description,
        'category': model.category,
        'amount': model.amount,
        'date': model.adjustment_date,
    }

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
        """
        Fetches active adjustments with eager category loading.
        """
        # 1. Base statement with eager category loading
        stmt = (
            select(cls.model)
            .outerjoin(cls.model.category)
            .outerjoin(cls.model.client)        # Join for display/search
            .outerjoin(cls.model.order) # Join to search by CDX number
            .outerjoin(cls.model.purchase_order) # Join to search by PO number
            .outerjoin(cls.model.invoice)       # Join to search by Invoice number
            .options(
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
                    cls.model.adjustment_number.icontains(search_term),
                    cls.model.description.icontains(search_term),
                    AdjustmentCategory.type.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),
                    Invoice.invoice_number.icontains(search_term),
                    OrderRegistry.order_number.icontains(search_term)
                )
            )

        # 3. Add .distinct() to collapse duplicate rows caused by joins
        stmt = stmt.distinct()

        # 4. Apply Sorting
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.adjustment_date
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page,
                            sort_by=sort_by, 
                            direction=direction)

    @classmethod
    def add_adjustment(cls, data: dict, new_files=None) -> Adjustment:
        """
        Atomic creation of a non-operational adjustment.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create header
        adjustment = cls.model(**clean_data)
        db.session.add(adjustment)
        db.session.flush() # Flush to get adjustment.id before commit

        # 3. Stage Attachments
        AttachmentService.stage('Adjustment', adjustment.id, new_files=new_files)

        # 4. Flush and hydrate
        db.session.flush()
        db.session.refresh(adjustment)

        # 5. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(adjustment.attachments)

        # 6. Record 'CREATE' Audit
        AuditLogService.record(
            target_id=adjustment.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )
        
        db.session.commit()
        return adjustment

    @classmethod
    def edit_adjustment(cls, adjustment_id: int, data: dict, new_files=None, delete_ids=None) -> Adjustment:
        """
        Update an existing adjustment.
        """
        # 1. Validation
        adjustment = cls.get_by_id(adjustment_id)
        if not adjustment:
            raise ValueError("Adjustment not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data, adjustment)

        # 3. Audit_logs snapshot
        old_snapshot = cls._get_snapshot(adjustment)
        old_snapshot['attachments'] = AttachmentService._get_fingerprint(adjustment.attachments)

        # 4. Update attributes
        for key, value in clean_data.items():
            setattr(adjustment, key, value)

        # 5. Stage Attachments
        AttachmentService.stage('Adjustment', adjustment_id, new_files=new_files, delete_ids=delete_ids)
        
        # 6. Flush and hydrate
        db.session.flush()
        db.session.refresh(adjustment)

        # 7. Prepare the Snapshot for the log
        new_smapshot = clean_data.copy()
        new_smapshot['attachments'] = AttachmentService._get_fingerprint(adjustment.attachments)

        # 8. Deep Audit Trigger
        AuditLogService.record(
            adjustment_id, 
            cls.model.__name__, 
            'UPDATE', 
            old_data=old_snapshot, 
            new_data=new_smapshot
        )

        db.session.commit()
        return adjustment
    
    @classmethod
    def get_adjustment_by_id(cls, id: int) -> Adjustment | None:
        """
        Fetcher: Returns Adjustment with full deal and category context.
        Prevents N+1 queries during View/Edit mode rendering.
        """
        stmt = (
            select(cls.model)
            .options(
                joinedload(cls.model.category),
                joinedload(cls.model.client),
                joinedload(cls.model.purchase_order),
                joinedload(cls.model.order),
                joinedload(cls.model.invoice),
                joinedload(cls.model.creator)
            )
            .where(cls.model.id == id)
        )
        return db.session.execute(stmt).scalar_one_or_none()
    
    # --- Auto Create Write-off for Underpayment---
    @classmethod
    def reconcile_writeoff(cls, invoice, parent_id: int | None = None):
        """
        Brain: Automates the creation/deletion of threshold write-offs.
        Ensures Net Income is corrected by the underpayment gap.
        Returns: {action: str, amount: int, number: str} for UI feedback.
        """
        # 1. Fetch the System Category
        category = db.session.execute(
            select(AdjustmentCategory).filter_by(is_system=True, type='Write-off')
        ).scalar_one_or_none()
        
        if not category:
            raise ValueError("'Write-off' category not found. Run seed-db.")

        # 2. Find any existing linked adjustment
        existing_adj = db.session.execute(
            select(Adjustment).filter_by(invoice_id=invoice.id, is_system=True)
        ).scalar_one_or_none()

        # 3. Audit_logs snapshot
        old_snapshot = cls._get_snapshot(existing_adj) if existing_adj else {}

        # 4. Initialize result packet
        result = None

        # 5. Logic Branch: Is the invoice completed?
        if invoice.status == 'completed' and invoice.is_active:
            # Calculate the Gap (Receipts - Billed Amount)
            # Example: $998 received - $1000 billed = -$2 write-off
            total_paid = sum(p.amount for p in invoice.payments if p.is_active)
            gap = total_paid - invoice.total_amount

            # A: If gap exists, create or update
            if gap != 0:
                if existing_adj: # Update 
                    existing_adj.amount = gap
                    existing_adj.adjustment_date = invoice.invoice_date
                    # Ensure links are correct (In case of a PO swap on the invoice)
                    existing_adj.client_id = invoice.client_id
                    existing_adj.po_id = invoice.po_id
                    existing_adj.order_id = invoice.order_id

                    # Capture for audit
                    new_data = {'amount': gap, 
                                'adjustment_date': invoice.invoice_date,
                                'client_id': invoice.client_id,
                                'po_id': invoice.po_id,
                                'order_id': invoice.order_id}

                    # Check for ANY change (Amount or Date)
                    if (old_snapshot.get('amount') != gap or 
                        old_snapshot.get('adjustment_date') != invoice.invoice_date):
                        AuditLogService.record(existing_adj.id,
                                               cls.model.__name__,  
                                               'UPDATE', 
                                               old_data=old_snapshot, 
                                               new_data=new_data,
                                               parent_id=parent_id)
                        result = {'action': 'UPDATE', 'amount': gap, 'number': existing_adj.adjustment_number}
                        
                else: # Create 
                    new_adj = Adjustment()
                    new_adj.adjustment_number = generate_doc_number('A', Adjustment, 'adjustment_number')
                    new_adj.description = f"Write-off for Invoice {invoice.invoice_number}"
                    new_adj.amount = gap
                    new_adj.adjustment_date = invoice.invoice_date
                    new_adj.category_id = category.id
                    new_adj.invoice_id = invoice.id
                    new_adj.client_id = invoice.client_id
                    new_adj.po_id = invoice.po_id
                    new_adj.order_id = invoice.order_id
                    new_adj.note = f"Write-off for Invoice {invoice.invoice_number}"
                    new_adj.is_system = True
                    
                    db.session.add(new_adj)
                    db.session.flush() # Get ID for audit

                    # Capture for audit
                    new_snapshot = cls._get_snapshot(new_adj)
                    AuditLogService.record(new_adj.id, 
                                           cls.model.__name__,  
                                           'CREATE',
                                           new_data=new_snapshot,
                                           parent_id=parent_id)
                    result = {'action': 'CREATE', 'amount': gap, 'number': new_adj.adjustment_number}
            
            # B: If gap is 0 but record exists (e.g. they paid the final cent), delete it
            elif existing_adj:
                adj_number = existing_adj.adjustment_number # Capture BEFORE delete
                AuditLogService.record(existing_adj.id, 
                                       cls.model.__name__, 
                                       'DELETE',
                                       old_data=old_snapshot,
                                       parent_id=parent_id)
                db.session.delete(existing_adj)
                result = {'action': 'DELETE', 'number': adj_number}

        # 4. Logic Branch: If NOT completed, ensure no write-off exists
        else:
            if existing_adj:
                adj_number = existing_adj.adjustment_number # Capture BEFORE delete
                AuditLogService.record(existing_adj.id, 
                                       cls.model.__name__, 
                                       'DELETE',
                                       old_data=old_snapshot,
                                       parent_id=parent_id)
                db.session.delete(existing_adj)
                result = {'action': 'DELETE', 'number': adj_number}
        
        return result


    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict, adjustment=None) -> dict:
        """Handles validation and type conversion."""
        is_system = adjustment.is_system if adjustment else False

        # 1. Fields that are ALWAYS editable (even is_system)
        description = data.get('description', '').strip()
        category_id = data.get('category_id')
        note = data.get('note', '').strip()

        if not description:
            raise ValueError("Adjustment Description is required.")
        if not category_id:
            raise ValueError("Adjustment Category is required.")
        
        clean_data = {
            'description': description,
            'category_id': int(category_id),
            'note': note
        }

        # 2. Only allow if NOT a system record
        if not is_system:
            adjustment_number = data.get('adjustment_number', '').strip()
            amount_raw = data.get('amount', '0')
            
            if not adjustment_number:
                raise ValueError("Adjustment Number is required.")
            if not amount_raw:
                raise ValueError("Amount is required.")

            # Parse Date
            raw_date = data.get('adjustment_date')
            # Get TimeZone from metadata
            metadata = db.session.get(SettingsMetadata, 1)
            tz_name = metadata.timezone if metadata else 'America/Chicago'

            if raw_date:
                adjustment_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            else:
                adjustment_date = datetime.now(ZoneInfo(tz_name)).date()

            # Handle Optional Client -> PO -> Order inheritance
            client_id = data.get('client_id')
            po_id = data.get('po_id')
            order_id = None # Inherit from po

            if po_id:
                # If a PO is chosen, it overrides the client selection to ensure deal integrity
                po = db.session.get(PurchaseOrder, int(po_id))
                if po:
                    client_id = po.client_id
                    order_id = po.order_id
            # Note: If only client_id was provided, it remains as captured from data.get
        
            # Add Data
            clean_data['adjustment_number'] = adjustment_number
            clean_data['amount'] = parse_to_cents(amount_raw)
            clean_data['adjustment_date'] = adjustment_date
            clean_data['client_id'] = int(client_id) if client_id else None
            clean_data['po_id'] = int(po_id) if po_id else None
            clean_data['order_id'] = order_id

        return clean_data
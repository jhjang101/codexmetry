from .base_service import BaseService
from ..models import Adjustment, AdjustmentCategory, SettingsMetadata
from .audit_service import AuditLogService
from .attachment_service import AttachmentService
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager
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
            .outerjoin(AdjustmentCategory)
            .options(contains_eager(cls.model.category))
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.adjustment_number.icontains(search_term),
                    cls.model.description.icontains(search_term),
                    AdjustmentCategory.type.icontains(search_term)
                )
            )

        # 3. Apply Sorting
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
        clean_data = cls._validate_and_transform(data)

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
        AuditLogService.record(adjustment_id, 
                               cls.model.__name__, 
                               'UPDATE', 
                               old_data=old_snapshot, 
                               new_data=new_smapshot)

        db.session.commit()
        return adjustment
    
    # --- Auto Create Write-off for Underpayment---
    @classmethod
    def reconcile_writeoff(cls, invoice):
        """
        Brain: Automates the creation/deletion of threshold write-offs.
        Ensures Net Income is corrected by the underpayment gap.
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

        # 4. Logic Branch: Is the invoice completed?
        if invoice.status == 'completed':
            # Calculate the Gap (Receipts - Billed Amount)
            # Example: $998 received - $1000 billed = -$2 write-off
            total_paid = sum(p.amount for p in invoice.payments if p.is_active)
            gap = total_paid - invoice.total_amount

            # A: If gap exists, create or update
            if gap != 0:
                if existing_adj:
                    # Update
                    existing_adj.description = f"Write-off for Invoice {invoice.invoice_number}"
                    existing_adj.amount = gap
                    existing_adj.adjustment_date = invoice.invoice_date

                    # Capture for audit
                    new_data = {'description': existing_adj.description, 
                                'amount': gap, 
                                'adjustment_date': invoice.invoice_date}

                    # Check for ANY change (Amount or Date)
                    if (old_snapshot.get('amount') != gap or 
                        old_snapshot.get('adjustment_date') != invoice.invoice_date):
                        AuditLogService.record(existing_adj.id,
                                               cls.model.__name__,  
                                               'UPDATE', 
                                               old_data=old_snapshot, 
                                               new_data=new_data)
                        result = {'action': 'UPDATE', 'amount': gap}
                        
                else:
                    new_adj = Adjustment()
                    new_adj.adjustment_number = generate_doc_number('A', Adjustment, 'adjustment_number')
                    new_adj.description = f"Write-off for Invoice {invoice.invoice_number}"
                    new_adj.amount = gap
                    new_adj.adjustment_date = invoice.invoice_date
                    new_adj.category_id = category.id
                    new_adj.invoice_id = invoice.id
                    new_adj.order_id = invoice.order_id
                    new_adj.is_system = True
                    new_adj.is_active = True
                    
                    db.session.add(new_adj)
                    db.session.flush() # Get ID for audit

                    # Capture for audit
                    new_snapshot = cls._get_snapshot(new_adj)
                    AuditLogService.record(new_adj.id, 
                                           cls.model.__name__,  
                                           'CREATE',
                                           new_data=new_snapshot)
                    result = {'action': 'CREATE', 'amount': gap}
            
            # B: If gap is 0 but record exists (e.g. they paid the final cent), delete it
            elif existing_adj:
                AuditLogService.record(existing_adj.id, 
                                       cls.model.__name__, 
                                       'DELETE',
                                       old_data=old_snapshot)
                db.session.delete(existing_adj)
                result = {'action': 'DELETE'}

        # 4. Logic Branch: If NOT completed, ensure no write-off exists
        else:
            if existing_adj:
                AuditLogService.record(existing_adj.id, 
                                       cls.model.__name__, 
                                       'DELETE',
                                       old_data=old_snapshot)
                db.session.delete(existing_adj)
                result = {'action': 'DELETE'}
        
        return result


    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles validation and type conversion."""
        description = data.get('description', '').strip()
        adjustment_number = data.get('adjustment_number', '').strip()
        category_id = data.get('category_id')
        amount_raw = data.get('amount', '0')
        
        if not description:
            raise ValueError("Adjustment Description is required.")
        if not adjustment_number:
            raise ValueError("Adjustment Number is required.")
        if not category_id:
            raise ValueError("Adjustment Category is required.")
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

        clean_data = {
            'description': description,
            'adjustment_number': adjustment_number,
            'amount': parse_to_cents(str(amount_raw)),
            'adjustment_date': adjustment_date,
            'category_id': int(category_id),
            'note': data.get('note', '').strip()
        }

        return clean_data
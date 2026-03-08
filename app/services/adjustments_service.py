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

        # 3. Save Attachments
        AttachmentService.commit('Adjustment', adjustment.id, new_files=new_files)

        # 4. Prepare the Snapshot for the log
        db.session.refresh(adjustment)
        new_snapshot = clean_data.copy()
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(adjustment.attachments)

        # 5. Record 'CREATE' Audit
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

        # 7. Save Attachments
        AttachmentService.commit('Adjustment', adjustment_id, new_files=new_files, delete_ids=delete_ids)
        db.session.refresh(adjustment)
        clean_data['attachments'] = AttachmentService._get_fingerprint(adjustment.attachments)

        # 4. Deep Audit Trigger
        AuditLogService.record(adjustment_id, 
                               cls.model.__name__, 
                               'UPDATE', 
                               old_data=old_snapshot, 
                               new_data=clean_data)

        db.session.commit()
        return adjustment

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles validation and type conversion."""
        description = data.get('description', '').strip()
        adjustment_number = data.get('adjustment_number', '').strip()
        amount_raw = data.get('amount', '0')
        
        if not description:
            raise ValueError("Adjustment Description is required.")
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

        category_id = data.get('category_id')

        clean_data = {
            'description': description,
            'adjustment_number': adjustment_number,
            'amount': parse_to_cents(str(amount_raw)),
            'adjustment_date': adjustment_date,
            'category_id': int(category_id) if category_id else None,
            'note': data.get('note', '').strip()
        }

        return clean_data
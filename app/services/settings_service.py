from .base_service import BaseService
from ..models import (
    SettingsMetadata, PoType, ProductCategory, 
    ExpenseCategory, PaymentType, AdjustmentCategory,
    Carrier,
)
from .audit_service import AuditLogService
from ..extensions import db
from ..utils.money import parse_to_cents
from sqlalchemy import select, or_

# --- SHARED REACTIVATION LOGIC ---
def _upsert_lookup(cls, **kwargs):
    """
    Helper: Implements the Reactivation Pattern.
    Checks for existence (active or archived) by the 'type' field.
    """
    name = kwargs.get('type')
    # 1. Look for existing record (ignoring is_active filter)
    stmt = select(cls.model).where(cls.model.type == name)
    existing = db.session.execute(stmt).scalar_one_or_none()

    if existing:
        if not existing.is_active:
            # 2. Forensic Reactivation
            old_snapshot = cls._get_snapshot(existing)
            existing.is_active = True
            
            # Update extra flags (is_cogs, is_revenue) if provided in kwargs
            for key, value in kwargs.items():
                setattr(existing, key, value)
            
            db.session.flush()
            AuditLogService.record(
                target_id=existing.id,
                target_type=cls.model.__name__,
                action='UPDATE', # Treat reactivation as an update to is_active
                old_data=old_snapshot,
                new_data=cls._get_snapshot(existing)
            )
            db.session.commit()
            return existing
        else:
            # 3. Guard against duplicate active records
            raise ValueError(f"The value '{name}' is already active in the list.")

    # 4. Standard path: Create brand new record via BaseService
    return super(cls, cls).add(**kwargs)

class CarrierService(BaseService):
    model = Carrier
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

class PoTypeService(BaseService):
    model = PoType
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

class ProductCategoryService(BaseService):
    model = ProductCategory
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

    @classmethod
    def get_all(cls):
        """Override: Hide system-deposit category from the UI."""
        stmt = select(cls.model).where(
            cls.model.is_active == True,
            cls.model.is_system == False
        ).order_by(cls.model.type.asc())
        return db.session.execute(stmt).scalars().all()

    @classmethod
    def toggle_revenue(cls, category_id: int) -> ProductCategory:
        """Flips the revenue status for reporting."""
        category = cls.get_by_id(category_id)
        if not category:
            raise ValueError("Product Category not found.")
        
        category.is_revenue = not category.is_revenue
        db.session.commit()
        return category

class PaymentTypeService(BaseService):
    model = PaymentType
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

class AdjustmentCategoryService(BaseService):
    model = AdjustmentCategory
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

    @classmethod
    def get_all(cls, include_id=None):
        """Override: Hide system categories UNLESS explicitly requested (e.g. for Edit)."""
        stmt = select(cls.model).where(
            cls.model.is_active == True,
            or_(
                cls.model.is_system == False,
                cls.model.id == include_id # NEW: Specific bypass
            )
        ).order_by(cls.model.type.asc())
        return db.session.execute(stmt).scalars().all()

class ExpenseCategoryService(BaseService):
    model = ExpenseCategory
    @classmethod
    def add(cls, **kwargs):
        return _upsert_lookup(cls, **kwargs)

    @classmethod
    def toggle_cogs(cls, category_id: int) -> ExpenseCategory:
        """Flips the COGS status for reporting."""
        category = cls.get_by_id(category_id)
        if not category:
            raise ValueError("Expense Category not found.")
        
        category.is_cogs = not category.is_cogs
        db.session.commit()
        return category

class MetadataService(BaseService):
    model = SettingsMetadata

    @classmethod
    def update_metadata(cls, data: dict) -> SettingsMetadata:
        """
        Validates and updates the singleton metadata record (ID 1).
        """
        # 1. Fetch the singleton record
        metadata = cls.get_by_id(1)

        # 2. Audit_logs snapshot
        old_snapshot = cls._get_snapshot(metadata)
        
        # 3. Validate & Transform
        clean_data = cls._validate_and_transform(data)
        
        # 4. Apply changes
        for key, value in clean_data.items():
            setattr(metadata, key, value)
        
        # 5. Deep Audit Trigger
        AuditLogService.record(
            1, 
            cls.model.__name__, 
            'UPDATE', 
            old_data=old_snapshot, 
            new_data=clean_data)
            
        db.session.commit()
        return metadata

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """
        Standardized validation for company settings.
        Ensures threshold is cents and names are not empty.
        """
        company_name = data.get('company_name', '').strip()
        # 1. Mandatory Name Check
        if not company_name:
            raise ValueError("Company Name cannot be empty.")

        # 2. Financial Guard: Threshold must be valid currency and non-negative
        raw_threshold = data.get('invoice_threshold', '0')
        # If the route already parsed it to cents, we use it; otherwise we parse here
        try:
            threshold = int(raw_threshold) if isinstance(raw_threshold, int) else parse_to_cents(str(raw_threshold))
        except (ValueError, TypeError):
            raise ValueError("Invalid Invoice Threshold format.")

        if threshold < 0:
            raise ValueError("Invoice Threshold cannot be negative.")

        # 3. Document Padding Guard
        try:
            padding = int(data.get('doc_padding', 4))
            if not (1 <= padding <= 8):
                raise ValueError("Document padding must be between 1 and 8.")
        except (ValueError, TypeError):
            raise ValueError("Document padding must be a valid number.")

        # 4. Map and sanitize new fields
        clean = {
            'company_name': company_name,
            'address': data.get('address', '').strip(),
            'timezone': data.get('timezone', 'America/Chicago').strip(),
            'invoice_threshold': threshold, # from your existing logic
            'doc_padding': padding,         # from your existing logic
            
            # Identity & Contact
            'company_email': data.get('company_email', '').strip(),
            'company_phone': data.get('company_phone', '').strip(),
            'company_fax': data.get('company_fax', '').strip(),
            'payable_address': data.get('payable_address', '').strip(),
            'shipping_address': data.get('shipping_address', '').strip(),

            # Banking
            'bank_account_name': data.get('bank_account_name', '').strip(),
            'bank_name': data.get('bank_name', '').strip(),
            'bank_swift': data.get('bank_swift', '').strip(),
            'bank_routing': data.get('bank_routing', '').strip(),
            'bank_account': data.get('bank_account', '').strip(),

            # Defaults
            'default_net_days': int(data.get('default_net_days', 30)),
            'default_quote_expiry_days': int(data.get('default_quote_expiry_days', 30)),
            'default_quote_terms': data.get('default_quote_terms', '').strip(),
            'default_invoice_terms': data.get('default_invoice_terms', '').strip(),
            'default_po_terms': data.get('default_po_terms', '').strip(),

            # Quote PDF Toggles
            'show_quote_signature': True if data.get('show_quote_signature') else False
        }
        
        # 5. Handle Optional Logo (only update if provided)
        logo = data.get('company_logo')
        if logo:
            clean['company_logo'] = logo

        return clean
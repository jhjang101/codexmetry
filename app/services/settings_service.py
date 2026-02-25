from .base_service import BaseService
from ..models import (
    SettingsMetadata, PoType, ProductCategory, 
    ExpenseCategory, PaymentType, AdjustmentCategory
)
from ..extensions import db
from ..utils.money import parse_to_cents

class PoTypeService(BaseService):
    model = PoType

class ProductCategoryService(BaseService):
    model = ProductCategory

class ExpenseCategoryService(BaseService):
    model = ExpenseCategory

class PaymentTypeService(BaseService):
    model = PaymentType

class AdjustmentCategoryService(BaseService):
    model = AdjustmentCategory

class MetadataService(BaseService):
    model = SettingsMetadata

    @classmethod
    def update_metadata(cls, data: dict) -> SettingsMetadata:
        """
        Validates and updates the singleton metadata record (ID 1).
        """
        # 1. Fetch the singleton record
        metadata = cls.get_by_id(1)
        
        # 2. Validate & Transform
        clean_data = cls._validate_and_transform(data)
        
        # 3. Apply changes
        for key, value in clean_data.items():
            setattr(metadata, key, value)
            
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
        address = data.get('address', '').strip()
        timezone = data.get('timezone', 'America/Chicago').strip()
        
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

        # 4. Return clean dictionary
        clean = {
            'company_name': company_name,
            'address': address,
            'timezone': timezone,
            'invoice_threshold': threshold,
            'doc_padding': padding
        }
        
        # 5. Handle Optional Logo (only update if provided)
        logo = data.get('company_logo')
        if logo:
            clean['company_logo'] = logo

        return clean
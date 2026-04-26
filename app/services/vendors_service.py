from .base_service import BaseService
from ..models import Vendor, VendorContact
from .audit_service import AuditLogService
from ..extensions import db
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, selectinload

class VendorService(BaseService):
    model = Vendor

    # Define the Whitelist for sorting
    SORT_MAP = {
        'name': model.company_name,
        'url': model.url,
        'contact': 'primary_name_label',  # Matches the label in the query
        'email': 'primary_email_label',    # Matches the label in the query
        'address': model.address
    }

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'name', 
                            direction: str = 'asc'):
        """
        Search: Implementation of filtered search for the vendor list.
        Searches across Company Name, URL, Address, and Contact details.
        """
        # 1. Define the "Primary Contact Name" Subquery
        # This specifically targets the contact with the lowest ID
        primary_name_sq = (
            select(func.coalesce(VendorContact.first_name, '') + ' ' + func.coalesce(VendorContact.last_name, ''))
            .where(VendorContact.vendor_id == cls.model.id)
            .order_by(VendorContact.id.asc())
            .limit(1)
            .correlate(cls.model)
            .scalar_subquery()
        )

        # 2. Define the "Primary Contact Email" Subquery
        primary_email_sq = (
            select(VendorContact.email)
            .where(VendorContact.vendor_id == cls.model.id)
            .order_by(VendorContact.id.asc())
            .limit(1)
            .correlate(cls.model)
            .scalar_subquery()
        )

        # 3. Base statement: Select the model AND the labels
        stmt = (
            select(
                cls.model,
                primary_name_sq.label('primary_name_label'),
                primary_email_sq.label('primary_email_label')
            )
            .outerjoin(VendorContact) # Keep for searching
            .options(selectinload(cls.model.contacts)) # Keep for display
            .where(cls.model.is_active == True)
        )

        # 4. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.company_name.icontains(search_term),
                    cls.model.url.icontains(search_term),
                    cls.model.address.icontains(search_term),
                    VendorContact.email.icontains(search_term),
                    VendorContact.first_name.icontains(search_term),
                    VendorContact.last_name.icontains(search_term) 
                )
            ).distinct()

        # 5. Group by ID and Apply Sorting
        stmt = stmt.group_by(cls.model.id)
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.company_name
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page, 
                            sort_by=sort_by, 
                            direction=direction)

    @classmethod
    def add_vendor(cls, data: dict, contacts_data: list[dict]) -> Vendor:
        """
        Create new vendor with contacts.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create vendor
        vendor = cls.model(**clean_data)
        db.session.add(vendor)
        db.session.flush() # Get ID for contacts

        # 3. Stage contacts
        new_contacts_fingerprint = cls._stage_contacts(vendor.id, contacts_data)

        # 4. Flush and hydrate
        db.session.flush()
        db.session.refresh(vendor)

        # 5. Prepare the Snapshot for Log
        new_snapshot = clean_data.copy()
        new_snapshot['contacts'] = new_contacts_fingerprint

        # 6. Record 'CREATE' Audit 
        AuditLogService.record(
            target_id=vendor.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )

        db.session.commit()
        return vendor

    @classmethod
    def edit_vendor(cls, vendor_id: int, data: dict, contacts_data: list[dict]) -> Vendor:
        """
        Update vendor with contacts.
        """
        # 1. Validation
        vendor = cls.get_by_id(vendor_id)
        if not vendor:
            raise ValueError("Vendor not found.")
        
        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Audit_logs smapshot
        old_snapshot = cls._get_snapshot(vendor)
        old_snapshot['contacts'] = cls._get_contacts_fingerprint(vendor.contacts)

        # 4. Update vendor header
        for key, value in clean_data.items():
            setattr(vendor, key, value)

        # 4. Stage contacts (Wipe and re-insert)
        new_contacts_fingerprint = cls._stage_contacts(vendor.id, contacts_data)

        # 5. Flush and hydrate
        db.session.flush()
        db.session.refresh(vendor)

        # 6. Prepare the Snapshot for the log
        new_snapshot = clean_data.copy()
        new_snapshot['contacts'] = new_contacts_fingerprint

        # 7. Deep Audit Trigger
        AuditLogService.record(vendor_id, 
                               cls.model.__name__, 
                               'UPDATE', 
                               old_data=old_snapshot, 
                               new_data=new_snapshot)

        db.session.commit()
        return vendor

    # --- INTERNAL HELPERS ---
    
    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles header validation and string cleaning."""
        # 1. Validation
        company_name = data.get('company_name', '').strip()
        if not company_name:
            raise ValueError("Vendor Company Name is required.")
        
        # 2. Transform data
        clean_data ={
            'company_name': company_name,
            'url': data.get('url', '').strip(),
            'address': data.get('address', '').strip()
        }

        return clean_data
    
    @classmethod
    def _stage_contacts(cls, vendor_id: int, contacts_data: list[dict]):
        """Manages the child contact rows with ghost record protection."""
        # 1. Remove all current contacts for this vendor
        db.session.execute(
            db.delete(VendorContact).where(VendorContact.vendor_id == vendor_id)
        )

        fingerprint = []
        # 2. Re-insert current list from snapshot
        for row in contacts_data:
            first = row.get('first_name', '').strip()
            last = row.get('last_name', '').strip()
            email = row.get('email', '').strip()
            phone = row.get('phone', '').strip()

            # Guard: Only save if at least one field is provided
            if any([first, last, email, phone]):
                contact = VendorContact()
                contact.vendor_id = vendor_id
                contact.first_name = first
                contact.last_name = last
                contact.email = email
                contact.phone_number = phone
                db.session.add(contact)

                fingerprint.append({
                    'name': f"{first} {last}".strip() or "Unnamed Contact",
                    'email': email or 'No Email',
                    'phone': phone or 'No Phone'
                })
                
        return sorted(fingerprint, key=lambda x: x['name'])
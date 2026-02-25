from .base_service import BaseService
from ..models import Vendor, VendorContact
from ..extensions import db
from sqlalchemy import select, or_
from sqlalchemy.orm import contains_eager, selectinload

class VendorService(BaseService):
    model = Vendor

    # Define the Whitelist for sorting
    SORT_MAP = {
        'name': model.company_name,
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
        # 1. Base statement with eager loading
        stmt = (
            select(cls.model)
            .outerjoin(VendorContact)
            .options(selectinload(cls.model.contacts))
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
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

        # 3. Apply Sorting
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.company_name
        )

        # 4. Use distinct() just to ensure no duplicates from the search join
        stmt = stmt.distinct()

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

        # 3. Save contacts
        cls._save_contacts(vendor.id, contacts_data)

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

        # 3. Update vendor header
        for key, value in clean_data.items():
            setattr(vendor, key, value)

        # 4. Save contacts (Wipe and re-insert)
        cls._save_contacts(vendor.id, contacts_data)

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
    def _save_contacts(cls, vendor_id: int, contacts_data: list[dict]):
        """Manages the child contact rows with ghost record protection."""
        # 1. Remove all current contacts for this vendor
        db.session.execute(
            db.delete(VendorContact).where(VendorContact.vendor_id == vendor_id)
        )

        # 2. Re-insert current list from snapshot
        for row in contacts_data:
            first = row.get('first_name', '').strip()
            last = row.get('last_name', '').strip()
            email = row.get('email', '').strip()

            # Guard: Only save if at least one field is provided
            if any([first, last, email]):
                contact = VendorContact()
                contact.vendor_id = vendor_id
                contact.first_name = first
                contact.last_name = last
                contact.email = email
                db.session.add(contact)
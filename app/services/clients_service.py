from .base_service import BaseService
from ..models import Client, ClientContact
from ..extensions import db
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, selectinload


class ClientService(BaseService):
    model = Client

    # Define the Whitelist for sorting
    SORT_MAP = {
        'name': model.company_name,
        'contact': 'primary_name_label',  # Matches the label in the query
        'email': 'primary_email_label',    # Matches the label in the query
        'address': model.address,
    }

    @classmethod
    def get_all(cls):
        """
        Override: Eager load contacts so that templates using .full_display 
        don't trigger N+1 lazy-loading queries.
        """
        stmt = (
            select(cls.model)
            .options(db.joinedload(cls.model.contacts)) # Fetch contacts in the same query
            .where(cls.model.is_active == True)
            .order_by(cls.model.company_name.asc())
        )
        return db.session.execute(stmt).scalars().unique().all()

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'name', 
                            direction: str = 'asc'):
        """
        Search: Implementation of filtered search for the client list.
        Searches across Company Name, Address, Contact names, and Contact Emails.
        """
        # 1. Define the "Primary Contact Name" Subquery
        # This specifically targets the contact with the lowest ID
        primary_name_sq = (
            select(func.coalesce(ClientContact.first_name, '') + ' ' + func.coalesce(ClientContact.last_name, ''))
            .where(ClientContact.client_id == cls.model.id)
            .order_by(ClientContact.id.asc())
            .limit(1)
            .correlate(cls.model) # Critical: links this subquery to the outer Client
            .scalar_subquery()
        )
        
        # 2. Define the "Primary Contact Email" Subquery
        primary_email_sq = (
            select(ClientContact.email)
            .where(ClientContact.client_id == cls.model.id)
            .order_by(ClientContact.id.asc())
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
            .outerjoin(ClientContact) # Keep for searching
            .options(selectinload(cls.model.contacts)) # Keep for display
            .where(cls.model.is_active == True)
        )

        # 4. Apply filters if search_term exists
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.company_name.icontains(search_term),
                    cls.model.address.icontains(search_term),
                    ClientContact.email.icontains(search_term),
                    ClientContact.first_name.icontains(search_term),
                    ClientContact.last_name.icontains(search_term) 
                )
            )
        
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
    def add_client(cls, data, contacts_data) -> Client:
        """
        Create new client with contacts
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create client
        client = cls.model(**clean_data)
        db.session.add(client)
        db.session.flush() # Get ID for contacts

        # 3. Save contacts
        cls._save_contacts(client.id, contacts_data)

        db.session.commit()
        return client

    @classmethod
    def edit_client(cls, client_id: int, data, contacts_data) -> Client:
        """
        Update client with contacts
        """
        # 1. Validation
        client = cls.get_by_id(client_id)
        if not client:
            raise ValueError("Client not found.")
        
        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 3. Update client
        for key, value in clean_data.items():
            setattr(client, key, value)

        # 4. Save contacts (Wipe and re-insert)
        cls._save_contacts(client.id, contacts_data)

        db.session.commit()
        return client
    
    @classmethod
    def get_client_by_id(cls, client_id: int) -> Client | None:
        """
        Hydrated Fetcher: Returns client with POs and Invoices loaded.
        Ensures 'has_open_pos' and 'has_open_invoices' checks are instant.
        """
        stmt = (
            select(cls.model)
            .options(
                selectinload(cls.model.contacts),
                selectinload(cls.model.purchase_orders),
                selectinload(cls.model.invoices)
            )
            .where(cls.model.id == client_id)
        )
        return db.session.execute(stmt).scalar_one_or_none()

    # --- INTERNAL HELPERS ---
    
    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles header validation and string cleaning."""
        # 1. Validation
        company_name = data.get('company_name', '').strip()
        if not company_name:
            raise ValueError("Company Name is required.")
        
        # 2. Transform data
        clean_data = {
            'company_name': company_name,
            'address': data.get('address', '').strip()
        }
        
        return clean_data
    
    @classmethod
    def _save_contacts(cls, client_id: int, contacts_data: list[dict]):
        """Manages the child contact rows."""
        # 1. Remove all current contacts for this client
        db.session.execute(
            db.delete(ClientContact).where(ClientContact.client_id == client_id)
        )

        # 2. Re-insert current list
        for row in contacts_data:
            first = row.get('first_name', '').strip()
            last = row.get('last_name', '').strip()
            email = row.get('email', '').strip()

            # Guard: Only save if at least one field is provided
            if any([first, last, email]):
                contact = ClientContact()
                contact.client_id = client_id
                contact.first_name = first
                contact.last_name = last
                contact.email = email
                db.session.add(contact)
from .base_service import BaseService
from ..models import Client, ClientContact

from ..extensions import db
from sqlalchemy import select, or_

class ClientService(BaseService):
    model = Client

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None):
        """
        Search POC: Implementation of filtered search for the client list.
        Searches across Company Name, Address, and Contact Emails.
        """
        # 1. Base statement (Active only)
        stmt = select(cls.model).where(cls.model.is_active == True)

        # 2. Apply filters if search_term exists
        if search_term:
            search_filter = f"%{search_term}%"
            # We outerjoin with contacts so we can search by personnel email too
            stmt = stmt.outerjoin(cls.model.contacts).where(
                or_(
                    cls.model.company_name.icontains(search_term),
                    cls.model.address.icontains(search_term),
                    ClientContact.email.icontains(search_term),
                    ClientContact.first_name.icontains(search_term),
                    ClientContact.last_name.icontains(search_term) 
                )
            ).distinct() # Prevent duplicate clients if multiple contacts match

        # 3. Order by name
        stmt = stmt.order_by(cls.model.company_name.asc())

        return db.session.execute(stmt).scalars().all()

    @classmethod
    def update_personnel(cls, client_id: int, contacts_data: list[dict]):
        """
        Handles the dynamic personnel sub-form.
        Strategy: Wipe existing contacts and re-insert new ones (Simple Update Pattern).
        """
        # 1. Remove all current contacts for this client
        delete_stmt = db.delete(ClientContact).where(ClientContact.client_id == client_id)
        db.session.execute(delete_stmt)

        # 2. Add new contacts from the list
        for data in contacts_data:
            # Only save if at least one name field is provided
            if data.get('first_name') or data.get('last_name'):
                new_contact = ClientContact(
                    client_id=client_id,
                    first_name=data.get('first_name'),
                    last_name=data.get('last_name'),
                    email=data.get('email')
                )
                db.session.add(new_contact)

        db.session.commit()
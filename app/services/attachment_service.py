from .base_service import BaseService
from ..models import Attachment
from ..extensions import db
from ..utils.files import save_file, delete_physical_file
from sqlalchemy import select, delete

class AttachmentService(BaseService):
    model = Attachment

    @classmethod
    def get_for_entity(cls, entity_type: str, entity_id: int) -> list[Attachment]:
        """Fetches all attachments for a specific document."""
        stmt = select(cls.model).where(
            cls.model.entity_type == entity_type,
            cls.model.entity_id == entity_id
        ).order_by(cls.model.uploaded_at.asc())
        return list(db.session.execute(stmt).scalars().all())

    @classmethod
    def commit(cls, 
               entity_type: str, 
               entity_id: int, 
               new_files: list | None = None, 
               delete_ids: list[int] | None = None):
        """
        The 'Git-Commit' for files.
        1. Deletes files marked in 'delete_ids' (DB + Disk).
        2. Saves 'new_files' (Disk + DB).
        """
        # Initialize to empty lists if None provided
        files_to_save = new_files or []
        ids_to_delete = delete_ids or []

        # --- 1. HANDLE DELETIONS ---
        for fid in ids_to_delete:
            file_record = cls.get_by_id(fid)
            if file_record:
                # Remove from disk first
                delete_physical_file(file_record.file_path, subfolder=entity_type.lower() + 's')
                # Remove from DB
                db.session.delete(file_record)

        # --- 2. HANDLE NEW UPLOADS ---
        for file in files_to_save:
            if file and file.filename != '':
                # Save to disk using our utility
                # Subfolder is 'quotes', 'invoices', etc.
                saved_name = save_file(file, subfolder=entity_type.lower() + 's')
                
                if saved_name:
                    # Create DB record
                    new_attachment = Attachment()
                    new_attachment.entity_type = entity_type
                    new_attachment.entity_id = entity_id
                    new_attachment.file_path = saved_name
                    new_attachment.file_name = file.filename # Original name
                    db.session.add(new_attachment)

        db.session.commit()
from .base_service import BaseService
from ..models import (Expense, ExpenseItem,  Vendor, Attachment, 
                      ExpenseCategory, Client, OrderRegistry, 
                      PurchaseOrder, Invoice, SettingsMetadata)
from .audit_service import AuditLogService
from .attachment_service import AttachmentService
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents, format_usd
from ..utils.pdf import save_pdf_from_html
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime
from zoneinfo import ZoneInfo

class ExpenseService(BaseService):
    model = Expense

    # Define the Whitelist for sorting
    SORT_MAP = {
        'status': model.status,
        'number': model.expense_number,
        'vendor': Vendor.company_name,    # Joined via vendor_id
        'description': model.description,
        'category': ExpenseCategory.type, # Joined via category_id
        'amount': model.total_amount,
        'date': model.expense_date
    }
    

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: int = 10,
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
        
        # 1. Base statement with eager loading
        stmt = (
            select(cls.model)
            .join(cls.model.vendor)
            .outerjoin(cls.model.client)
            .outerjoin(cls.model.category)
            .outerjoin(cls.model.order)
            .outerjoin(cls.model.purchase_order)
            .outerjoin(cls.model.invoice)
            .options(
                contains_eager(cls.model.vendor),
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
                    cls.model.expense_number.icontains(search_term),
                    cls.model.description.icontains(search_term),
                    Vendor.company_name.icontains(search_term),
                    ExpenseCategory.type.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    OrderRegistry.order_number.icontains(search_term),
                    PurchaseOrder.po_number.icontains(search_term),
                    Invoice.invoice_number.icontains(search_term)
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
            default_col=cls.model.expense_date # Default: newest first
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page,
                            sort_by=sort_by, 
                            direction=direction)
    
    @classmethod
    def add_expense(cls, data: dict, items_data: list[dict], new_files=None) -> Expense:
        """
        Create new Expense header and items.
        Logic: If description is blank, fall back to the first item description.
        """
        # 1. Validate & transform (includes description fallback)
        clean_data = cls._validate_and_transform(data, items_data)

        # 2. Stage Expense header
        expense = cls.model(**clean_data)
        db.session.add(expense)
        db.session.flush() # Get ID for items

        # 3. Stage items and calculate total
        new_items_fingerprint = cls._stage_items(expense, items_data)

        # 4. Stage Attahments
        AttachmentService.stage('Expense', expense.id, new_files=new_files)

        # 5. Flush and hydrate
        db.session.flush()
        db.session.refresh(expense) 

        # 6. Capture new state for audit log
        new_snapshot = clean_data.copy()
        new_snapshot['line_items'] = new_items_fingerprint
        new_snapshot['total_amount'] = expense.total_amount
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(expense.attachments)

        # 7. Record 'CREATE' Audit
        AuditLogService.record(
            target_id=expense.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )

        db.session.commit()
        return expense
    
    @classmethod
    def edit_expense(cls, 
                     expense_id: int, 
                     data: dict, 
                     items_data: list[dict], 
                     new_files=None, 
                     delete_ids=None) -> Expense:
        """
        Update Expense header, items, and attachments.
        """
        # 1. Validation
        expense = cls.get_expense_by_id(expense_id)
        if not expense:
            raise ValueError("Expense not found.")

        # 2. Validate & transform
        clean_data = cls._validate_and_transform(data, items_data, expense)

        # 3. Audit_logs snapshot
        old_snapshot = cls._get_snapshot(expense)
        old_snapshot['items'] = cls._get_items_fingerprint(expense.items)
        old_snapshot['attachments'] = AttachmentService._get_fingerprint(expense.attachments)

        # 4. Stage header attributes
        for key, value in clean_data.items():
            setattr(expense, key, value)

        # 5. Stage items (Wipe and re-insert)
        new_items_fingerprint = cls._stage_items(expense, items_data)

        # 6. Stage Attachments
        AttachmentService.stage('Expense', expense_id, new_files=new_files, delete_ids=delete_ids)
        
        # 7. Flush and hydrate
        db.session.flush()
        db.session.refresh(expense)

        # 8. Capture new state for audit log
        new_smapshot = clean_data.copy()
        new_smapshot['items'] = new_items_fingerprint
        new_smapshot['total_amount'] = expense.total_amount
        new_smapshot['attachments'] = AttachmentService._get_fingerprint(expense.attachments)

        # 9. Deep Audit Trigger
        AuditLogService.record(expense_id, 
                               cls.model.__name__, 
                               'UPDATE', 
                               old_data=old_snapshot, 
                               new_data=new_smapshot)

        db.session.commit()
        return expense
    
    @classmethod
    def get_expense_by_id(cls, id: int) -> Expense | None:
        """
        Fetcher: Returns Expense with eager-loaded Vendor, Client (and contacts),
        and the full Project Registry hierarchy (Order, PO, Invoice).
        Prevents N+1 queries when using .full_display or viewing job-costing refs.
        """
        stmt = (
            select(cls.model)
            .options(
                # 1. Load mandatory Vendor relationship
                joinedload(cls.model.vendor).selectinload(Vendor.contacts),
                # 2. Load the optional Client and their contacts for .full_display
                joinedload(cls.model.client).selectinload(Client.contacts),
                # 3. Load the lookup category
                joinedload(cls.model.category),
                joinedload(cls.model.creator),
                selectinload(cls.model.items),
                # 4. Load the Job Costing hierarchy
                joinedload(cls.model.order),
                joinedload(cls.model.purchase_order),
                joinedload(cls.model.invoice)
            )
            .where(cls.model.id == id)
        )
        return db.session.execute(stmt).scalar_one_or_none()
    
    @classmethod
    def issue_expense(cls, id: int, notes: str):
        """
        Brain: Commits the Expense to the legal record (Vendor PO).
        Performs versioned PDF generation and Audit logging.
        """
        # 1. Fetch hydrated object
        expense = cls.get_expense_by_id(id)
        if not expense or not expense.is_active:
            return None, None, None
        
        # 2. Preparation: Recalculate Subtotal for PDF context
        subtotal = sum(item.quantity * item.unit_price for item in expense.items)

        # 2.1. total_amount Cross Check
        if subtotal != expense.total_amount:
            raise ValueError(
                f"Integrity Error: The saved Expense total ({format_usd(expense.total_amount)}) "
                f"does not match the calculated sum of its items ({format_usd(subtotal)}). "
                "Please edit and re-save the Expense before issuing."
            )

        # 3. Versioning Logic: Count existing generated snapshots
        v_count = db.session.query(func.count(Attachment.id)).filter_by(
            entity_type='Expense', 
            entity_id=id, 
            is_generated=True
        ).scalar() or 0
        version = v_count + 1

        # 4. Capture current state for Audit
        old_snapshot = cls._get_snapshot(expense)
        before_status = expense.status

        # 5. Physical Archival (PDF Generation)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"Expense_{expense.expense_number}_{timestamp}_v{version}.pdf"

        # Construct the data package for WeasyPrint
        context_data = {
            'expense': expense,
            'subtotal': subtotal,
            'transient_notes': notes
        }

        # The utility handles rendering and physical saving
        save_pdf_from_html('expenses/print.html', context_data, filename, subfolder='expenses')

        # 6. Database Updates (State & Linkage)
        if before_status == 'draft':
            expense.status = 'open'
        expense.terms_snapshot = notes

        # Create the Forensic Attachment record
        new_snapshot = Attachment()
        new_snapshot.entity_type = 'Expense'
        new_snapshot.entity_id = id
        new_snapshot.file_path = filename
        new_snapshot.file_name = filename
        new_snapshot.is_generated = True
        db.session.add(new_snapshot)

        # 7. Forensic Trail: Record the ISSUE action
        AuditLogService.record(
            target_id=id,
            target_type='Expense',
            action='ISSUE',
            old_data=old_snapshot,
            new_data={
                'status': expense.status,
                'terms_snapshot': notes,
                'snapshot_file': filename
                }
        )

        db.session.commit()
        return expense, {"before": before_status, "after": expense.status}, filename




        






        
        # before = expense.status
        # if before == 'draft':
        #     # 1. Forensic Record
        #     snapshot = cls._get_snapshot(expense)
        #     snapshot['line_items'] = cls._get_items_fingerprint(expense.items)
        #     snapshot['status'] = 'open'

        #     parent_audit_id = AuditLogService.record(
        #         target_id=id,
        #         target_type='Expense',
        #         action='ISSUE',
        #         old_data={},
        #         new_data=snapshot
        #     )
        #     # 2. Status Flip
        #     expense.status = 'open'
            
        #     db.session.commit()
        
        # return expense, {"before": before, "after": expense.status}
    
    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, 
                                data: dict, 
                                items_data: list[dict],
                                expense: Expense | None = None) -> dict:
        """Handles header validation and description fallback."""
        vendor_id = data.get('vendor_id')
        expense_number = data.get('expense_number', '').strip()
        category_id = data.get('category_id')

        if not vendor_id:
            raise ValueError("Vendor is required.")
        if not expense_number:
            raise ValueError("Expense Number is required.")
        if not category_id:
            raise ValueError("Expense Category is required.")
        
        if not items_data:
            raise ValueError("At least one expense item is required.")

        # 1. Description Fallback Logic
        description = data.get('description', '').strip()
        if not description:
            # Fallback to the text of the first item
            description = items_data[0].get('item', '').strip()
        
        if not description:
            raise ValueError("Description is required or must be provided in the first item line.")
        
        # 2. Get Defaults from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'
        default_terms = metadata.default_po_terms if metadata else ""

        # 3. Parse dates
        raw_date = data.get('expense_date')
        
        if raw_date:
            expense_date = datetime.strptime(raw_date, '%Y-%m-%d').date() 
        else:
            expense_date = datetime.now(ZoneInfo(tz_name)).date()

        # 4. Expense Linkage (Client -> PO -> Invoice -> Order inheritance)
        client_id = data.get('client_id')
        po_id = data.get('po_id')
        invoice_id = data.get('invoice_id')
        order_id = None

        if invoice_id:
            invoice = db.session.get(Invoice, int(invoice_id))
            if invoice:
                client_id = invoice.client_id
                po_id = invoice.po_id
                order_id = invoice.order_id
        elif po_id:
            po = db.session.get(PurchaseOrder, int(po_id))
            if po:
                client_id = po.client_id
                order_id = po.order_id
        # Note: If only client_id was provided, it remains as captured from data.get

        # 5. Terms Resolution
        if expense and expense.terms_snapshot:
            resolved_terms = expense.terms_snapshot
        else:
            resolved_terms = default_terms

        # 6. Transform Data
        clean_data ={
            'vendor_id': int(vendor_id),
            'expense_number': expense_number,
            'category_id': int(category_id),
            'client_id': int(client_id) if client_id else None,
            'order_id': order_id,
            'po_id': int(po_id) if po_id else None,
            'invoice_id': int(invoice_id) if invoice_id else None,
            'description': description,
            'expense_date': expense_date,
            'status': data.get('status', 'open'),
            'note': data.get('note', '').strip(),
            'terms_snapshot': resolved_terms
        }

        return clean_data


    @classmethod
    def _stage_items(cls, expense: Expense, items_data: list[dict]):
        """Manages ExpenseItem rows (strings) and updates Expense.total_amount."""
        # 1. Wipe current items
        db.session.execute(
            db.delete(ExpenseItem).where(ExpenseItem.expense_id == expense.id)
        )

        total_cents = 0
        fingerprint = []

        # 2. Re-insert current snapshot
        for idx, row in enumerate(items_data, start=1):
            item_text = row.get('item', '').strip()
            if item_text:
                description = row.get('description', '').strip()
                catalog_number = row.get('catalog_number', '').strip()
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                item = ExpenseItem()
                item.expense_id = expense.id
                item.catalog_number = catalog_number
                item.item = item_text
                item.quantity = qty
                item.unit_price = price
                item.description = description
                item.sort_order = idx
                db.session.add(item)
                
                # Generate fingerprint
                fingerprint.append({
                    'item': item_text, 
                    'cat_no': catalog_number,
                    'quantity': qty, 
                    'unit_price': price,
                    'description': description,
                    'sort_order': idx
                })

            else:
                raise ValueError("Item description is required for all rows.")

        # 3. Update the header total
        expense.total_amount = total_cents

        return sorted(fingerprint, key=lambda x: x['sort_order'])
    


    @classmethod
    def _get_items_fingerprint(cls, items_collection):
        """
        Specialized Fingerprint for Expenses:
        Uses the 'item' string and 'catalog_number' instead of product_id.
        """
        data = [
            {
                'item': item.item, 
                'cat_no': item.catalog_number,
                'quantity': item.quantity, 
                'unit_price': item.unit_price,
                'description': item.description,
                'sort_order': item.sort_order
            }
            for item in items_collection
        ]
        # Sort by item name so the audit log doesn't think the order change is a data change
        return sorted(data, key=lambda x: x['sort_order'])
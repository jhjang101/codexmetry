from .base_service import BaseService
from ..models import Quote, QuoteItem, Client, OrderRegistry, SettingsMetadata, Product, Attachment
from .audit_service import AuditLogService
from .attachment_service import AttachmentService
from ..extensions import db
from ..utils.money import parse_to_cents, format_usd
from ..utils.pdf import save_pdf_from_html
from sqlalchemy import select, or_, func
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

class QuoteService(BaseService):
    model = Quote

    # Define the Whitelist Mapping
    SORT_MAP = {
        'status': model.status,
        'number': model.quote_number,
        'cdx': OrderRegistry.order_number, # Joined via order_id
        'client': Client.company_name,     # Joined via client_id
        'amount': model.total_amount,
        'date': model.quote_date
    }

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, per_page: 
                            int = 10,
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
        """
        Search: Fetches active quotes
        Includes eager loading of Client and OrderRegistry
        Includes dynamic sorting and pagination.
        """
        # 1. Base statement
        stmt = (
            select(cls.model)
            .join(Client)
            .outerjoin(OrderRegistry)
            .options(
                contains_eager(cls.model.client),
                contains_eager(cls.model.order)
            )
            .where(cls.model.is_active == True)
        )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    cls.model.quote_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term),
                    OrderRegistry.order_number.icontains(search_term)
                )
            )

        # 4. Apply Sorting logic before pagination
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.quote_date # Default: newest first
        )

        return cls.paginate(stmt, 
                            page=page, 
                            per_page=per_page, 
                            sort_by=sort_by, 
                            direction=direction)
    
    @classmethod
    def add_quote(cls, data: dict, items_data: list[dict], new_files=None) -> Quote:
        """
        Create new Quote header and line items.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create quote
        quote = cls.model(**clean_data)
        db.session.add(quote)
        db.session.flush()

        # 3. Stage items and calculate total
        new_items_fingerprint = cls._stage_items(quote, items_data)

        # 4. Stage attachments
        AttachmentService.stage('Quote', quote.id, new_files=new_files)

        # 5. flash and hydrate
        db.session.flush()
        db.session.refresh(quote)

        # 6. Capture new state for audit log
        new_snapshot = clean_data.copy()
        new_snapshot['line_items'] = new_items_fingerprint
        new_snapshot['total_amount'] = quote.total_amount
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(quote.attachments)

        # 5. Record 'CREATE' Audit
        AuditLogService.record(
            target_id=quote.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )

        db.session.commit()
        return quote
    
    @classmethod
    def edit_quote(cls, 
                   quote_id: int, 
                   data: dict, 
                   items_data: list[dict], 
                   new_files=None, 
                   delete_ids=None) -> Quote:
        """
        Update Quote header, line items, and attachments.
        """
        quote = cls.get_by_id(quote_id)
        if not quote:
            raise ValueError("Quote not found.")
        
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)
        
        # 2. Capture original state for audit
        old_snapshot = cls._get_snapshot(quote)
        old_snapshot['line_items'] = cls._get_items_fingerprint(quote.items, 'quantity', 'quoted_unit_price')
        old_snapshot['attachments'] = AttachmentService._get_fingerprint(quote.attachments)

        print('old_snapshot[attachments]:', old_snapshot['attachments'])

        # 3. Stage quote header
        for key, value in clean_data.items():
            setattr(quote, key, value)

        # 4. Stage updated line items and calculate total
        new_items_fingerprint = cls._stage_items(quote, items_data)

        # 5. Stage attachments
        AttachmentService.stage('Quote', quote_id, new_files=new_files, delete_ids=delete_ids)
        
        # 6. Flash and hydrate
        db.session.flush()
        db.session.refresh(quote)

        # 7. Capture new state for audit log
        new_snapshot = clean_data.copy()
        new_snapshot['line_items'] = new_items_fingerprint
        new_snapshot['total_amount'] = quote.total_amount
        new_snapshot['attachments'] = AttachmentService._get_fingerprint(quote.attachments)

        # 8. Record audit
        AuditLogService.record(quote_id, 
                               cls.model.__name__, 
                               'UPDATE', 
                               old_data=old_snapshot, 
                               new_data=new_snapshot)

        # 9. Commit
        db.session.commit()
        return quote
    
    @classmethod
    def get_quote_by_id(cls, id: int) -> Quote | None:
        """
        Fetcher: Returns Quote with eager-loaded Client (and contacts) 
        and Order Registry for high-performance form rendering.
        """
        stmt = (
            select(cls.model)
            .options(
                # Load the Client and their nested contacts
                joinedload(cls.model.client).selectinload(Client.contacts),
                # Load the Order Registry to support quote.order.order_number
                joinedload(cls.model.order),
                joinedload(cls.model.creator),
                selectinload(cls.model.items).joinedload(QuoteItem.product)
            )
            .where(cls.model.id == id)
        )
        return db.session.execute(stmt).scalar_one_or_none()
    
    @classmethod
    def get_quotes_by_client(cls, client_id: int, include_id: int | None = None, statuses: list[str] | None = None):
        """
        Fetcher: Returns 'sent' quotes for a client that haven't been converted yet.
        If include_id is provided, that specific quote is included even if it has an order_id.
        Defaults to ['sent', 'draft'] if no statuses are provided.
        Used for the PO creation dropdown.
        """

        print('statuses:', statuses)
        print('include_id:', include_id)


        # 1. Handle Default Statuses
        if statuses is None:
            statuses = ['sent', 'draft']
        
        print('statuses:', statuses)
        
        # 2. Define the "Standard" criteria based on parameters
        standard_criteria = (
            cls.model.status.in_(statuses),
        )

        # 3. Build the statement
        stmt = select(cls.model).where(
            cls.model.client_id == client_id,
            cls.model.is_active == True,
            # Use OR to include the specifically requested ID
            or_(
                *standard_criteria,
                cls.model.id == include_id
            )
        ).order_by(cls.model.quote_date.desc())

        return db.session.execute(stmt).scalars().all()
    
    @classmethod
    def issue_quote(cls, id: int, notes: str):
        """
        Issue the Quote and save PDF as Attatchment.
        Performs item bucketing, versioned PDF generation, and Audit logging.
        """
        # 1. Fetch hydrated object
        quote = cls.get_quote_by_id(id)
        if not quote or not quote.is_active:
            return None, None
        
        # 2. Preparation: Internal Item Bucketing for PDF Accuracy
        line_display_items = []
        subtotal = tax_total = shipping_total = 0
        for item in quote.items:
            val = item.quantity * item.quoted_unit_price
            placement = item.product.document_placement

            if placement == 'Tax':
                tax_total += val
            elif placement == 'Shipping':
                shipping_total += val
            else:
                line_display_items.append(item)
                subtotal += val
        
        # 2.1. total_amount Cross Check
        calculated_total = subtotal + tax_total + shipping_total
        if calculated_total != quote.total_amount:
            raise ValueError(
                f"Integrity Error: The saved Quote total ({format_usd(quote.total_amount)}) "
                f"does not match the calculated sum of its items ({format_usd(calculated_total)}). "
                "Please edit and re-save the Quote before issuing."
            )

        # 3. Versioning Logic: Count existing generated snapshots
        v_count = db.session.query(func.count(Attachment.id)).filter_by(
            entity_type='Quote', 
            entity_id=id, 
            is_generated=True
        ).scalar() or 0
        version = v_count + 1

        # 4. Capture current state for Audit
        old_snapshot = cls._get_snapshot(quote)

        # 5. Physical Archival (PDF Generation)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"Quote_{quote.quote_number}_{timestamp}_v{version}.pdf"

        # Construct the data package for WeasyPrint
        context_data = {
            'quote': quote,
            'line_display_items': line_display_items,
            'subtotal': subtotal,
            'tax_total': tax_total,
            'shipping_total': shipping_total,
            'transient_notes': notes
        }

        # The utility handles rendering and physical saving
        save_pdf_from_html('quotes/print.html', context_data, filename, subfolder='quotes')

        # 6. Database Updates (State & Linkage)
        if quote.status == 'draft':
            quote.status = 'sent'
        quote.terms_snapshot = notes

        # Create the Forensic Attachment record
        new_snapshot = Attachment()
        new_snapshot.entity_type = 'Quote'
        new_snapshot.entity_id = id
        new_snapshot.file_path = filename
        new_snapshot.file_name = filename
        new_snapshot.is_generated = True
        db.session.add(new_snapshot)

        # 7. Forensic Trail: Record the ISSUE action
        AuditLogService.record(
            target_id=id,
            target_type='Quote',
            action='ISSUE',
            old_data=old_snapshot,
            new_data={
                'status': quote.status,
                'terms_snapshot': notes,
                'snapshot_file': filename # Link for the history timeline
            }
        )

        db.session.commit()
        return quote, {"before": old_snapshot['status'], "after": quote.status}

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles header validation and data type conversion."""
        client_id = data.get('client_id')
        quote_number = data.get('quote_number', '').strip()
        
        if not client_id:
            raise ValueError("Client is required.")
        if not quote_number:
            raise ValueError("Quote Number is required.")

        # Parse dates
        raw_date = data.get('quote_date')
        raw_expiry = data.get('expiration_date')

        # Get TimeZone from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'
        # Get dynamic expiry days (default to 30 if record missing)
        expiry_days = metadata.default_quote_expiry_days if metadata else 30
        
        if raw_date:
            quote_date = datetime.strptime(raw_date, '%Y-%m-%d').date() 
        else:
            quote_date = datetime.now(ZoneInfo(tz_name)).date()
        if raw_expiry:
            expiration_date = datetime.strptime(raw_expiry, '%Y-%m-%d').date() 
        else:
            expiration_date = quote_date + timedelta(days=expiry_days)

        if quote_date > expiration_date:
            raise ValueError("Expiration date cannot be before quote date.")

        # Transform data
        clean_data ={
            'client_id': int(client_id),
            'quote_number': quote_number,
            'quote_date': quote_date,
            'expiration_date': expiration_date,
            'status': data.get('status', 'draft'),
            'note': data.get('note', '').strip()
        }

        return clean_data

    @classmethod
    def _stage_items(cls, quote: Quote, items_data: list[dict]):
        """Manages QuoteItem rows and updates Quote.total_amount."""
        # 1. Wipe current items
        db.session.execute(
            db.delete(QuoteItem).where(QuoteItem.quote_id == quote.id)
        )

        total_cents = 0
        fingerprint = []

        # 2. Re-insert current list
        for idx, row in enumerate(items_data, start=1):
            product_id = row.get('product_id')
            if product_id:
                description = row.get('description', '').strip()
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                line_total = qty * price
                total_cents += line_total

                item = QuoteItem()
                item.quote_id = quote.id
                item.product_id = int(product_id)
                item.quantity = qty
                item.quoted_unit_price = price
                item.description = description
                item.sort_order = idx 
                db.session.add(item)

                # Generate fingerprint
                product = db.session.get(Product, product_id)
                fingerprint.append({
                    'product_id': int(product_id), 
                    'product': product.name if product else "Unknown",
                    'quantity': qty, 
                    'unit_price': price,
                    'description': description,
                    'sort_order': idx,
                    'po_item_id': None # Added for audit symmetry
                })

        # 3. Update the snapshot total on the header
        quote.total_amount = total_cents

        return sorted(fingerprint, key=lambda x: x['sort_order'])
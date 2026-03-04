from .base_service import BaseService
from ..models import PurchaseOrder, PoItem, OrderRegistry, Client, Quote, Invoice, InvoiceItem, Payment, Product, SettingsMetadata
from ..extensions import db
from ..utils.docs import generate_doc_number
from ..utils.money import parse_to_cents
from ..utils.manual_pagination import ManualPagination
from sqlalchemy import select, or_, func, and_, exists
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from datetime import datetime
from zoneinfo import ZoneInfo

class PurchaseOrderService(BaseService):
    model = PurchaseOrder

    # Define the Whitelist Mapping
    SORT_MAP = {
        'status': model.status,
        'number': model.po_number,
        'cdx': OrderRegistry.order_number, # Joined via order_id
        'client': Client.company_name,     # Joined via client_id
        'amount': model.total_amount,
        'to_be_invoiced': 'to_be_invoiced', # SQLAlchemy can sort by the label string
        'date': model.po_date
    }

    @classmethod
    def get_all_with_search(cls, 
                            search_term: str | None = None, 
                            page: int = 1, 
                            per_page: 
                            int = 10,
                            sort_by: str = 'date', 
                            direction: str = 'desc'):
        """
        Fetches active POs with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name).
        Use subquery to calculate 'to_be_invoiced'.
        'to_be_invoiced' = PO Total - Sum(Positive Invoices) - Prepayments.
        """
        # 1. Subquery for Invoiced Sum (Positive totals only). This is Total Due.
        # Invoices with total <= 0 are covered by deposits and shouldn't reduce the to_be_invoiced.
        inv_sub = (
            select(
                Invoice.po_id, 
                func.sum(Invoice.total_amount).label('total_invoiced')
            )
            .where(Invoice.is_active == True, Invoice.total_amount > 0) # Added > 0 filter
            .group_by(Invoice.po_id)
            .subquery()
        )

        # 2. Subquery for Prepayment Sum (Invoiceless Payments)
        pay_sub = (
            select(
                Payment.po_id, 
                func.sum(Payment.amount).label('total_invoiceless')
            )
            .where(Payment.invoice_id == None, Payment.is_active == True)
            .group_by(Payment.po_id)
            .subquery()
        )

        # 3. Main Query with 'to_be_invoiced' Label
        stmt = (
            select(
                cls.model,
                (
                    cls.model.total_amount - 
                    func.coalesce(inv_sub.c.total_invoiced, 0) - 
                    func.coalesce(pay_sub.c.total_invoiceless, 0)
                ).label('to_be_invoiced')
            )
            .join(cls.model.order)
            .join(cls.model.client)
            .outerjoin(inv_sub, inv_sub.c.po_id == cls.model.id)
            .outerjoin(pay_sub, pay_sub.c.po_id == cls.model.id)
            .where(cls.model.is_active == True)
        )

        # 3.1. Eager load relationship for list view
        stmt = stmt.options(
            contains_eager(cls.model.order),
            contains_eager(cls.model.client)
        )

        # 4. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term),
                    cls.model.po_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        # 5. Apply Sorting using the BaseService helper
        stmt = cls.apply_sorting(
            stmt=stmt,
            sort_by=sort_by,
            direction=direction,
            whitelist=cls.SORT_MAP,
            default_col=cls.model.po_date # Default: newest first
        )

        # 6. Calculate Total Items (for the pagination numbers)
        # 6.1. We create a count query derived from your main statement
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.session.execute(count_stmt).scalar()

        # 6.2. Fetch the Page of Items (keeping the tuples!)
        # Apply limit and offset manually
        paginated_stmt = stmt.limit(per_page).offset((page - 1) * per_page)
        
        # KEY DIFFERENCE: Use db.session.execute() instead of db.paginate()
        # This returns 'Row' objects containing (PurchaseOrder, to_be_invoiced)
        rows = db.session.execute(paginated_stmt).all()

        # 7. Unwrap and Attach 'to_be_invoiced'
        items = []
        for row in rows:
            po = row[0]              # The PurchaseOrder model
            po.to_be_invoiced = row[1]      # The to_be_invoiced
            items.append(po)

        # 8. Create the Pagination Object Manually
        return ManualPagination(items=items, 
                                page=page, 
                                per_page=per_page, 
                                total=total,
                                sort_by=sort_by, 
                                direction=direction)

    @classmethod
    def add_po(cls, data: dict, items_data: list[dict]) -> PurchaseOrder:
        """
        Create new Order Registry and Purchase Order with items.
        """
        # 1. Validate & transform
        clean_data = cls._validate_and_transform(data)

        # 2. Create Order Registry (The CDX number)
        cdx_number = generate_doc_number(prefix='CDX', model=OrderRegistry, column_name='order_number')
        registry = OrderRegistry()
        registry.order_number = cdx_number
        db.session.add(registry)
        db.session.flush() # Flush to get registry.id before commit

        # 3. Handle Quote Handshake (1:1 link)
        quote_id = clean_data.get('quote_id')
        if quote_id:
            quote = db.session.get(Quote, quote_id)
            if quote:
                quote.status = 'accepted'
                quote.order_id = registry.id

        # 4. Create PO Header
        po = cls.model(**clean_data)
        po.order_id = registry.id
        po.status = 'open'
        db.session.add(po)
        db.session.flush()

        # 5. Save items
        cls._save_items(po, items_data)

        db.session.commit()
        return po
    
    @classmethod
    def edit_po(cls, po_id: int, data: dict, items_data: list[dict]) -> PurchaseOrder:
        """
        Update PO header and line items.
        Handles Quote status reversion if the link changed.
        """
        # 1. Validation
        po = cls.get_po_by_id(po_id)
        if not po:
            raise ValueError("Purchase Order not found.")
        
        # Locking guard: if PO has invoices or payments prevent switching client and quote link
        new_client_id = data.get('client_id')
        if new_client_id and int(new_client_id) != po.client_id:
            if po.has_active_invoices or po.has_active_payments: # type: ignore
                raise ValueError("Cannot change Client: active invoices or payments exist for this deal.")
        new_quote_id = data.get('quote_id')
        if new_quote_id and int(new_quote_id) != po.quote_id:
            if po.has_active_invoices or po.has_active_payments: # type: ignore
                raise ValueError("Cannot change Quote link: active invoices or payments exist for this deal.")
        
        quote_id = data.get('quote_id')
        
        # 2. Handle Quote Link Reversion (1:1 logic)
        old_quote_id = po.quote_id
        new_quote_id = int(quote_id) if quote_id else None

        if old_quote_id != new_quote_id:
            # Release the old quote
            if old_quote_id:
                old_quote = db.session.get(Quote, old_quote_id)
                if old_quote:
                    old_quote.status = 'sent'
                    old_quote.order_id = None
            # Accept the new quote
            if new_quote_id:
                new_quote = db.session.get(Quote, new_quote_id)
                if new_quote:
                    new_quote.status = 'accepted'
                    new_quote.order_id = po.order_id

        # 3. Validate & transform header
        clean_data = cls._validate_and_transform(data)

        # 4. Update Header
        for key, value in clean_data.items():
            setattr(po, key, value)

        # 5. Save Items
        cls._save_items(po, items_data)

        db.session.commit()
        return po
    
    @classmethod
    def get_po_by_id(cls, 
                     id: int,
                     exclude_invoice_id: int | None = None
                     ) -> PurchaseOrder | None:
        """
        Fetcher: Returns PO with calculated 'to_be_invoiced', prepayment, and remaining credit pools.
        exclude_invoice_id: If provided, this invoice's items/totals are ignored 
        in fulfillment and credit math (useful for Edit mode).
        """
        # 1. Manually build the statement to include eager loading of contacts
        stmt = (
            select(cls.model)
            .options(
                # Load the primary Client and their contacts
                db.joinedload(cls.model.client).selectinload(Client.contacts),
                # Load the Bill-To Client and their contacts
                db.joinedload(cls.model.bill_to).selectinload(Client.contacts),
                joinedload(cls.model.order),
                selectinload(cls.model.invoices),
                selectinload(cls.model.payments)
            )
            .where(cls.model.id == id)
        )
        # Execute and get the result
        po = db.session.execute(stmt).scalar_one_or_none()
        if not po:
            return None
        
        # 2. Calculate Total Invoiced
        # We ONLY sum totals that are greater than zero. This is Total Due.
        # Negative invoices (credits) do not reduce the contract gap.
        inv_sum_stmt = select(func.sum(Invoice.total_amount)).where(
            Invoice.po_id == po.id, 
            Invoice.is_active == True, 
            Invoice.total_amount > 0,
            Invoice.id != exclude_invoice_id
        )
        total_invoiced = db.session.execute(inv_sum_stmt).scalar() or 0

        # 3. Calculate Total Prepayment (invoiceless payments)
        prepay_stmt = select(func.sum(Payment.amount)).where(
            Payment.po_id == po.id, 
            Payment.invoice_id == None, 
            Payment.is_active == True
        )
        total_prepayment = db.session.execute(prepay_stmt).scalar() or 0

        # 4. Calculate Applied Deposit (Sum of 'Applied Deposit' line items)
        applied_stmt = (
            select(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .join(Invoice).join(Product)
            .where(Invoice.po_id == po.id, 
                   Invoice.is_active == True, 
                   Product.is_system == True,
                   Invoice.id != exclude_invoice_id)
        )
        total_applied_deposit = db.session.execute(applied_stmt).scalar() or 0

        # 5. Calculate Carry-over Credits (Negative grand totals). 
        # This is sum of remaining credits in all linked invoices.
        neg_total_stmt = select(func.sum(Invoice.total_amount)).where(
            Invoice.po_id == po.id, 
            Invoice.is_active == True, 
            Invoice.total_amount < 0,
            Invoice.id != exclude_invoice_id
        )
        total_neg_carryover = db.session.execute(neg_total_stmt).scalar() or 0

        # 6. Final Financial Attributes
        po.total_prepayment = total_prepayment
        po.to_be_invoiced = po.total_amount - total_invoiced - total_prepayment
        remaining_credit = total_prepayment + total_applied_deposit - total_neg_carryover
        po.remaining_credit = max(0, remaining_credit)

        # 7. Calculate Fulfillment (Items left to ship)
        remaining_items = []
        for po_item in po.items:
            invoiced_qty_stmt = (
                select(func.sum(InvoiceItem.quantity))
                .join(Invoice).join(Product)
                .where(
                    Invoice.po_id == po.id, 
                    InvoiceItem.product_id == po_item.product_id,
                    Invoice.is_active == True, 
                    Product.is_system == False,
                    Invoice.id != exclude_invoice_id
                )
            )
            already_invoiced = db.session.execute(invoiced_qty_stmt).scalar() or 0
            qty_left = po_item.quantity - already_invoiced

            if qty_left > 0:
                remaining_items.append({
                    'product_id': po_item.product_id,
                    'product': po_item.product,
                    'quantity': qty_left,
                    'agreed_unit_price': po_item.agreed_unit_price,
                    'description': po_item.description
                })
        
        # 8. Add Applied Deposit row for Invoice automation if remaining credit exists
        if po.remaining_credit > 0:
            system_product = db.session.execute(
                select(Product).where(Product.is_system == True, 
                                      Product.name == 'Applied Deposit')
            ).scalar_one_or_none()
            if system_product:
                remaining_items.append({
                    'product_id': system_product.id,
                    'product': system_product,
                    'quantity': 1,
                    'agreed_unit_price': -(po.remaining_credit),
                    'description': 'Applied Deposit from current remaining credit'
                })

        po.remaining_items = remaining_items

        # 9. Check is po has active invoices or payment for locking edit.
        po.has_active_invoices = any(inv.is_active for inv in po.invoices)
        po.has_active_payments = any(pay.is_active for pay in po.payments)

        return po
    
    @classmethod
    def archive_po(cls, id: int):
        """
        Specialized archive that ripples through Registry, Quotes, and Invoices.
        Returns (PO object, has_payments boolean).
        """
        po = cls.get_po_by_id(id)
        if not po:
            return None, False

        # 1. Check for active payments (Money Safety)
        # We check the collection for any item where is_active is True
        has_payments = any(payment.is_active for payment in po.payments)

        # 2. Archive the Registry (frees the CDX number)
        if po.order:
            po.order.is_active = False

        # 3. Revert the Quote (liberates it back to Lead status)
        if po.quote:
            po.quote.status = 'sent'
            po.quote.order_id = None

        # 4. Ripple Archive to Invoices
        for inv in po.invoices:
            inv.is_active = False

        # 5. Archive the PO itself
        po.is_active = False

        db.session.commit()
        return po, has_payments
    
    @classmethod
    def get_pos_by_client(cls, 
                          client_id: int, 
                          include_id: int | None = None, 
                          statuses: list[str] | None = None):
        """
        Fetcher: Returns eligible pos for a client based on statuses.
        Refactored: Uses the 3-stage lifecycle (open, invoiced, completed).
        Defaults to ['open'] for most dropdowns.
        Used for the Invoice, Payment, and Expense creation dropdown.
        """
        # 1. Handle Default Statuses (Usually we only want to invoice/pay 'open' POs)
        if statuses is None:
            statuses = ['open']

        # 2. Base Criteria (OR block)
        criteria = [
            cls.model.status.in_(statuses),
            cls.model.id == include_id
        ]

        # 3. Build statement
        stmt = select(cls.model).where(
            cls.model.client_id == client_id,
            cls.model.is_active == True,
            or_(*criteria)
        ).order_by(cls.model.po_date.desc())

        return db.session.execute(stmt).scalars().all()
    
    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict) -> dict:
        """Handles header validation and type conversion."""
        client_id = data.get('client_id')
        if not client_id:
            raise ValueError("Client is required.")
        
        # Parse dates
        raw_date = data.get('po_date')
        # Get TimeZone from metadata
        metadata = db.session.get(SettingsMetadata, 1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'
        if raw_date:
            po_date = datetime.strptime(raw_date, '%Y-%m-%d').date() 
        else:
            po_date = datetime.now(ZoneInfo(tz_name)).date()
        
        po_type_id = data.get('po_type_id')
        quote_id = data.get('quote_id')

        clean_data ={
            'client_id': int(client_id),
            'bill_to_id': int(data.get('bill_to_id', client_id)),
            'po_number': data.get('po_number', '').strip(),
            'po_date': po_date,
            'po_type_id': int(po_type_id) if po_type_id else None,
            'quote_id': int(quote_id) if quote_id else None,
            'status': data.get('status', 'open'),
            'note': data.get('note', '').strip()
        }

        return clean_data
    
    @classmethod
    def _save_items(cls, po: PurchaseOrder, items_data: list[dict]):
        """Manages PoItem rows and updates total_amount."""
        db.session.execute(db.delete(PoItem).where(PoItem.po_id == po.id))

        total_cents = 0
        for row in items_data:
            product_id = row.get('product_id')
            if product_id:
                description = row.get('description', '').strip()
                qty = int(row.get('quantity', 1))
                price = parse_to_cents(str(row.get('unit_price', 0)))
                total_cents += (qty * price)

                item = PoItem()
                item.po_id = po.id
                item.product_id = int(product_id)
                item.quantity = qty
                item.agreed_unit_price = price
                item.description = description
                db.session.add(item)

        po.total_amount = total_cents

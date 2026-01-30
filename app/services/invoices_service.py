from .base_service import BaseService
from ..models import Invoice, InvoiceItem, PurchaseOrder, PoItem, OrderRegistry, Client
from ..extensions import db
from ..utils.docs import generate_doc_number
from sqlalchemy import select, or_, func
from sqlalchemy.orm import joinedload

class InvoiceService(BaseService):
    model = Invoice

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active Invoices with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name)
        """
        # 1. Base statement
        stmt = select(cls.model).join(cls.model.order).join(cls.model.client).where(cls.model.is_active == True)

        # Eager load relationships for the list view
        # stmt = stmt.options(
        #     joinedload(cls.model.order),
        #     joinedload(cls.model.purchase_order),
        #     joinedload(cls.model.client)
        # )

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term),
                    cls.model.invoice_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        # 3. Order by Registry creation (Newest first)
        stmt = stmt.order_by(OrderRegistry.created_at.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)
    
    @classmethod
    def get_remaining_items(cls, po_id: int):
        """
        Logic for Partial Invoice
        Returns a list of dicts with product details and remaining quantity.
        """
        po = db.session.get(PurchaseOrder, po_id)
        if not po:
            return []

        remaining_items = []
        for po_item in po.items:
            # 1. Sum up how many of this product have already been invoiced for this PO
            already_invoiced_stmt = select(func.sum(InvoiceItem.quantity)).join(Invoice).where(
                Invoice.po_id == po_id,
                InvoiceItem.product_id == po_item.product_id,
                Invoice.is_active == True
            )
            already_invoiced = db.session.execute(already_invoiced_stmt).scalar() or 0

            # 2. Calculate what's left
            remaining_qty = po_item.quantity - already_invoiced
            
            # 3. Only suggest items that have a remaining balance
            if remaining_qty > 0:
                remaining_items.append({
                    'product_id': po_item.product_id,
                    'product': po_item.product,
                    'quantity': remaining_qty,
                    'unit_price': po_item.agreed_unit_price # Default to PO price
                })
        
        return remaining_items
    
    @classmethod
    def create_invoice(cls, data: dict) -> Invoice:
        """Saves the Invoice header, inheriting Registry ID from the PO."""

         # 1. Define required fields and their "Nice Names" for the error message
        required_fields = {
            'order_id': 'Order Registry ID',
            'po_id': 'Purchase Order Link',
            'client_id': 'Client',
            'bill_to_id': 'Billing Entity',
            'invoice_number': 'Invoice Number'
        }

        # 2. Perform the validation loop
        for field, label in required_fields.items():
            value = data.get(field)
            
            # Check for None, empty string, or whitespace-only strings
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{label} is required.")
        
        # Inherit from provided data
        invoice_date = data.get('invoice_date')

        # 3. If validation passes, proceed to create the object
        invoice = Invoice()
        invoice.order_id = int(data['order_id'])
        invoice.po_id = int(data['po_id'])
        invoice.client_id = int(data['client_id'])
        invoice.bill_to_id = int(data['bill_to_id'])
        invoice.invoice_number = data['invoice_number'].strip()
        if invoice_date:
            invoice.invoice_date = invoice_date
        invoice.tracking_number = data.get('tracking_number')
        invoice.note = data.get('note')
        invoice.status = 'open'

        db.session.add(invoice)
        db.session.commit()

        return invoice
    
    @classmethod
    def update_items(cls, invoice_id: int, items_data: list[dict]):
        """Wipes current Invoice items and re-inserts new ones with total recalculation."""
        # 1. Delete old items
        db.session.execute(db.delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id))

        total_cents = 0
        for data in items_data:
            raw_pid = data.get('product_id')
            if raw_pid:
                qty = int(data.get('quantity', 0))
                price = int(data.get('unit_price', 0))
                total_cents += (qty * price)

                new_item = InvoiceItem()
                new_item.invoice_id = invoice_id
                new_item.product_id = int(raw_pid)
                new_item.quantity = qty
                new_item.billed_unit_price = price
                db.session.add(new_item)

        # 2. Update the parent total
        invoice = cls.get_by_id(invoice_id)
        if invoice:
            invoice.total_amount = total_cents
        
        db.session.commit()





    # from datetime import datetime

    # @classmethod
    # def add_with_validation(cls, data: dict) -> Invoice:
    #     """
    #     Validates, Transforms, and Saves the Invoice Header.
    #     Handles string-to-type conversion here to keep routes clean.
    #     """
    #     # 1. Extraction & Transformation
    #     raw_cid = data.get('client_id')
    #     raw_bid = data.get('bill_to_id')
    #     raw_oid = data.get('order_id')
    #     raw_pid = data.get('po_id')
    #     raw_num = data.get('invoice_number', '').strip()
    #     raw_date = data.get('invoice_date')

    #     # 2. Validation
    #     if not all([raw_cid, raw_oid, raw_pid, raw_num]):
    #         raise ValueError("Client, PO, and Invoice Number are required.")

    #     # 3. Construction
    #     invoice = Invoice()
    #     invoice.client_id = int(raw_cid)
    #     invoice.bill_to_id = int(raw_bid) if raw_bid else int(raw_cid)
    #     invoice.order_id = int(raw_oid)
    #     invoice.po_id = int(raw_pid)
    #     invoice.invoice_number = raw_num
        
    #     if raw_date:
    #         invoice.invoice_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        
    #     invoice.tracking_number = data.get('tracking_number')
    #     invoice.note = data.get('note')
    #     invoice.status = 'open'

    #     db.session.add(invoice)
    #     db.session.commit()
    #     return invoice
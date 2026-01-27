from .base_service import BaseService
from ..models import PurchaseOrder, PoItem, OrderRegistry, Client
from ..extensions import db
from ..utils.docs import generate_doc_number
from sqlalchemy import select, or_

class PurchaseOrderService(BaseService):
    model = PurchaseOrder

    @classmethod
    def get_all_with_search(cls, search_term: str | None = None, page: int = 1, per_page: int = 10):
        """
        Fetches active POs with search and pagination.
        Joins with OrderRegistry (CDX#) and Client (Name).
        """
        # 1. Base statement with eager joins
        stmt = select(cls.model).join(cls.model.order).join(cls.model.client).where(cls.model.is_active == True)

        # 2. Apply filters
        if search_term:
            stmt = stmt.where(
                or_(
                    OrderRegistry.order_number.icontains(search_term),
                    cls.model.po_number.icontains(search_term),
                    Client.company_name.icontains(search_term),
                    cls.model.status.icontains(search_term)
                )
            )

        # 3. Order by Registry creation (Newest first)
        stmt = stmt.order_by(OrderRegistry.created_at.desc())

        return cls.paginate(stmt, page=page, per_page=per_page)

    @classmethod
    def create_with_registry(cls, data: dict) -> PurchaseOrder:
        """
        Creates a new Order Registry entry and links the PO to it.
        """
        # 1. Generate the next CDX number using the registry model
        cdx_number = generate_doc_number(prefix='CDX', model=OrderRegistry, column_name='order_number')

        # 2. Create the Registry entry
        registry = OrderRegistry()
        registry.order_number = cdx_number
        db.session.add(registry)
        db.session.flush() # Flush to get registry.id before commit

        # 3. Create the Purchase Order
        po = PurchaseOrder()
        po.order_id = registry.id
        po.client_id = data.get('client_id')
        # PRD 4.3: Bill To defaults to Client but can be overridden
        po.bill_to_id = data.get('bill_to_id') or data.get('client_id')
        po.po_number = data.get('po_number') # Client's reference
        po.po_date = data.get('po_date')
        po.po_type_id = data.get('po_type_id')
        po.note = data.get('note')
        po.status = 'open'

        db.session.add(po)
        db.session.commit()
        return po

    @classmethod
    def update_items(cls, po_id: int, items_data: list[dict]):
        """
        Wipes current PO items and re-inserts new ones.
        Updates the denormalized total_amount.
        """
        # 1. Remove old items
        delete_stmt = db.delete(PoItem).where(PoItem.po_id == po_id)
        db.session.execute(delete_stmt)

        total_cents = 0

        # 2. Add new items with explicit attribute setting for Pylance
        for data in items_data:
            raw_pid = data.get('product_id')
            if raw_pid:
                qty = int(data.get('quantity', 0))
                price = int(data.get('unit_price', 0))
                total_cents += (qty * price)

                new_item = PoItem()
                new_item.po_id = po_id
                new_item.product_id = int(raw_pid)
                new_item.quantity = qty
                new_item.agreed_unit_price = price
                db.session.add(new_item)

        # 3. Update parent total
        po = cls.get_by_id(po_id)
        if po:
            po.total_amount = total_cents
        
        db.session.commit()
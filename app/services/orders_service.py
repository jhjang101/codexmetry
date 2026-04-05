from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from ..models import OrderRegistry, Quote, PurchaseOrder, Invoice, Payment, Expense, Adjustment
from ..extensions import db

class OrderService:
    model = OrderRegistry

    @classmethod
    def get_deal_tree(cls, order_id: int | None) -> OrderRegistry | None:
        """
        Brain: Fetches a fully hydrated CDX project tree.
        Ensures all properties (total_invoiced, contextual_balance, etc.) 
        can calculate in-memory without N+1 queries.
        """
        if not order_id:
            return None

        # The Hydration Statement (2-level deep)
        stmt = (
            select(cls.model)
            .options(
                # 1. Direct Parents (1:1) with deeper Client hydration
                joinedload(cls.model.quote).joinedload(Quote.client),
                joinedload(cls.model.purchase_order).joinedload(PurchaseOrder.client),

                # 2. Child Invoices + their Clients (1:N)
                selectinload(cls.model.invoices.and_(Invoice.is_active == True))
                    .joinedload(Invoice.client),

                # 3. Child Payments + their Payers (1:N)
                 selectinload(cls.model.payments.and_(Payment.is_active == True))
                    .joinedload(Payment.paid_from),
                
                # 4. Child Payments + their Invoices (1:N)
                selectinload(cls.model.payments.and_(Payment.is_active == True))
                    .joinedload(Payment.invoice),

                # 4. Child Expenses + their Vendors (1:N)
                selectinload(cls.model.expenses.and_(Expense.is_active == True))
                    .joinedload(Expense.vendor),
                
                # 5. Child Adjustments + their Categories (1:N)
                selectinload(cls.model.adjustments.and_(Adjustment.is_active == True))
                    .joinedload(Adjustment.category)
            )
            .where(cls.model.id == order_id)
        )
        tree = db.session.execute(stmt).scalar_one_or_none()

        if tree:
            # 2. Attach the Deal Timeline (The "Black Box" data)
            from .audit_service import AuditLogService
            tree.timeline = AuditLogService.get_for_order(tree.id) # type: ignore
        
        return tree
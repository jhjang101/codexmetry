from sqlalchemy import select, func, and_
from datetime import date
from ..extensions import db
from ..models import Invoice, InvoiceItem, ProductCategory, Payment, Client, Product

class AnalyticsReportService:

    @classmethod
    def get_client_performance(cls, year: int, mode='revenue'):
        """
        Brain: Calculates yearly performance ranking for clients.
        mode: 'revenue' (Invoiced Sales) or 'cash' (Payments Received)
        """
        # 1. Define Date Range for the specific year
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        if mode == 'revenue':
            # --- ACCRUAL REVENUE LOGIC ---
            # Sum items where is_revenue=True, from issued invoices
            stmt = (
                select(
                    Client.company_name,
                    func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).label('total')
                )
                .join(Invoice, Invoice.client_id == Client.id)
                .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
                .join(Product, InvoiceItem.product_id == Product.id)
                .join(ProductCategory, Product.category_id == ProductCategory.id)
                .where(
                    Invoice.is_active == True,
                    Invoice.status != 'draft',
                    Invoice.invoice_date.between(start_date, end_date),
                    ProductCategory.is_revenue == True
                )
                .group_by(Client.company_name)
                .order_by(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).desc())
            )
        else:
            # --- CASH PAYMENT LOGIC ---
            # Sum actual cash received per client account
            stmt = (
                select(
                    Client.company_name,
                    func.sum(Payment.amount).label('total')
                )
                .join(Payment, Payment.client_id == Client.id)
                .where(
                    Payment.is_active == True,
                    Payment.payment_date.between(start_date, end_date)
                )
                .group_by(Client.company_name)
                .order_by(func.sum(Payment.amount).desc())
            )

        # 2. Execute and Process
        results = db.session.execute(stmt).all()
        
        # 3. Calculate Global Total for Percentages
        grand_total = sum(r[1] for r in results) or 0
        
        # 4. Format for UI (Bar Chart and Table)
        performance_data = []
        for idx, r in enumerate(results, start=1):
            amount = r[1] or 0
            percentage = (amount / grand_total * 100) if grand_total > 0 else 0
            
            performance_data.append({
                'rank': idx,
                'name': r[0],
                'amount': amount,
                'percentage': round(percentage, 1)
            })

        return {
            'clients': performance_data,
            'grand_total': grand_total,
            'year': year,
            'mode': mode
        }
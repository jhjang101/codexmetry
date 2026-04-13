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
    
    @classmethod
    def get_product_performance(cls, year: int):
        """
        Brain: Aggregates revenue by Category and Product SKU for a specific year.
        Strictly filters for Issued/Completed revenue items.
        """
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        # 1. CATEGORY AGGREGATION
        cat_stmt = (
            select(
                ProductCategory.type,
                func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).label('total')
            )
            .join(Product, Product.category_id == ProductCategory.id)
            .join(InvoiceItem, InvoiceItem.product_id == Product.id)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start_date, end_date),
                ProductCategory.is_revenue == True
            )
            .group_by(ProductCategory.type)
            .order_by(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).desc())
        )
        cat_results = db.session.execute(cat_stmt).all()
        grand_total = sum(r[1] for r in cat_results) or 0

        categories = []
        for r in cat_results:
            categories.append({
                'name': r[0],
                'amount': r[1] or 0,
                'percentage': round((r[1] / grand_total * 100), 1) if grand_total > 0 else 0
            })

        # 2. PRODUCT AGGREGATION (SKU Level)
        prod_stmt = (
            select(
                Product.name,
                Product.catalog_number,
                func.sum(InvoiceItem.quantity).label('qty_sold'),
                func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).label('total')
            )
            .join(InvoiceItem, InvoiceItem.product_id == Product.id)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .join(ProductCategory, Product.category_id == ProductCategory.id) # Filter out non-revenue
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start_date, end_date),
                ProductCategory.is_revenue == True
            )
            .group_by(Product.name, Product.catalog_number)
            .order_by(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price).desc())
        )
        prod_results = db.session.execute(prod_stmt).all()

        products = []
        for idx, r in enumerate(prod_results, start=1):
            products.append({
                'rank': idx,
                'name': r[0],
                'catalog': r[1],
                'qty': r[2] or 0,
                'amount': r[3] or 0
            })

        return {
            'year': year,
            'grand_total': grand_total,
            'categories': categories,
            'products': products
        }
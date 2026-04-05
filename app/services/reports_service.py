from sqlalchemy import select, func, desc, asc, and_, case, extract
from dateutil.relativedelta import relativedelta
from datetime import date
from ..extensions import db
from ..models import (
    Invoice, InvoiceItem, Expense, ExpenseItem, 
    Payment, Adjustment, AdjustmentCategory, 
    Product, ProductCategory, ExpenseCategory, Client, Vendor
)

class ReportService:

    @classmethod
    def get_financial_package(cls, start_date, end_date):
        """Brain: Compiles a 6-table dataset for the Financial Fortress."""
        
        # 1. ACCRUAL DATA (Performance - Based on Issued Documents)
        accrual_revenue = cls._get_accrual_revenue(start_date, end_date)
        accrual_expenses = cls._get_accrual_expenses(start_date, end_date)
        
        # 2. CASH DATA (Liquidity - Based on Cash Movement)
        cash_income = db.session.execute(
            select(func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date.between(start_date, end_date))
        ).scalar() or 0
        
        cash_outgoings = cls._get_cash_outgoings(start_date, end_date)

        # 3. ADJUSTMENTS (Non-Operating)
        adjustments = cls._get_adjustments_breakdown(start_date, end_date)
        total_adj = sum(a['total'] for a in adjustments)

        # 4. CONSOLIDATED SUMMARY MATH
        # Accrual Perspective
        gross_profit_accrual = accrual_revenue - accrual_expenses['cogs_total']
        operating_profit_accrual = gross_profit_accrual - accrual_expenses['opex_total']
        net_income = operating_profit_accrual + total_adj

        # Cash Perspective
        gross_profit_cash = cash_income - cash_outgoings['cogs_paid']
        net_cash_flow = cash_income - cash_outgoings['total_paid']

        return {
            'accrual': {
                'revenue': accrual_revenue,
                'cogs': accrual_expenses['cogs_total'],
                'gross_profit': gross_profit_accrual,
                'opex': accrual_expenses['opex_total'],
                'operating_profit': operating_profit_accrual,
                'net_income': net_income
            },
            'cash': {
                'income': cash_income,
                'cogs_paid': cash_outgoings['cogs_paid'],
                'gross_profit_cash': gross_profit_cash,
                'opex_paid': cash_outgoings['opex_paid'],
                'net_cash': net_cash_flow
            },
            'adjustments': adjustments,
            'audit': {
                'invoices': cls._get_invoice_audit(start_date, end_date),
                'payments': cls._get_payment_audit(start_date, end_date),
                'expenses': cls._get_expense_audit(start_date, end_date),
                'adjustments': cls._get_adjustment_audit(start_date, end_date)
            }
        }

    # --- ACCRUAL HELPERS (Document Based) ---

    @classmethod
    def _get_accrual_revenue(cls, start, end):
        """Sums items where is_revenue is True using InvoiceItem anchor."""
        stmt = (
            select(func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .select_from(InvoiceItem)
            .join(Invoice).join(Product).join(ProductCategory)
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start, end),
                ProductCategory.is_revenue == True
            )
        )
        return db.session.execute(stmt).scalar() or 0

    @classmethod
    def _get_accrual_expenses(cls, start, end):
        """Sums COGS vs OPEX using ExpenseItem anchor."""
        stmt = (
            select(
                ExpenseCategory.is_cogs,
                func.sum(ExpenseItem.quantity * ExpenseItem.unit_price)
            )
            .select_from(ExpenseItem)
            .join(Expense).join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.status != 'draft',
                Expense.expense_date.between(start, end)
            )
            .group_by(ExpenseCategory.is_cogs)
        )
        
        results = db.session.execute(stmt).all()
        data = {'cogs_total': 0, 'opex_total': 0}
        for is_cogs, total in results:
            if is_cogs: data['cogs_total'] = total
            else: data['opex_total'] = total
        return data

    # --- CASH HELPERS (Transaction Based) ---

    @classmethod
    def _get_cash_outgoings(cls, start, end):
        """Sums Completed Expenses, splitting by COGS vs OPEX flags."""
        stmt = (
            select(
                ExpenseCategory.is_cogs,
                func.sum(Expense.total_amount)
            )
            .join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.status == 'completed', # Paid
                Expense.expense_date.between(start, end)
            )
            .group_by(ExpenseCategory.is_cogs)
        )
        results = db.session.execute(stmt).all()
        data = {'cogs_paid': 0, 'opex_paid': 0, 'total_paid': 0}
        for is_cogs, total in results:
            if is_cogs: data['cogs_paid'] = total
            else: data['opex_paid'] = total
        data['total_paid'] = data['cogs_paid'] + data['opex_paid']
        return data
    
    # --- SORTING HELPER ---

    @classmethod
    def _apply_audit_sorting(cls, stmt, sort_by, direction, whitelist, default_col):
        """
        Brain: Local sorting logic for report tables.
        Defaults to ASC (Oldest first) for accounting ledger style.
        """
        # Standardize Direction: Default to ASC for ledgers
        sort_dir = desc if direction == 'desc' else asc
        target_col = whitelist.get(sort_by)

        if target_col is not None:
            # Primary: User Selection | Secondary: Default (Date)
            return stmt.order_by(sort_dir(target_col), asc(default_col))
        
        # Fallback: Chronological Ledger Order
        return stmt.order_by(asc(default_col))

    # --- AUDIT TABLES (The Evidence) ---

    @classmethod
    def _get_invoice_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Accrual Revenue."""
        # Whitelist for Invoices
        MAP = {
            'date': Invoice.invoice_date,
            'number': Invoice.invoice_number,
            'amount': Invoice.total_amount,
            'client': Client.company_name
        }

        stmt = select(Invoice).join(Client, Invoice.client_id == Client.id).where(
            Invoice.is_active == True, 
            Invoice.status != 'draft',
            Invoice.invoice_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Invoice.invoice_date)

        invoices = db.session.execute(stmt).scalars().all()

        audit_rows = []
        for inv in invoices:
            rev = sum(i.quantity * i.billed_unit_price for i in inv.items if i.product.category.is_revenue)
            audit_rows.append({
                'obj': inv,
                'revenue_portion': rev,
                'non_revenue_portion': inv.total_amount - rev
            })
        return audit_rows

    @classmethod
    def _get_payment_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Cash Income."""
        MAP = {
            'date': Payment.payment_date,
            'number': Payment.payment_number,
            'amount': Payment.amount,
            'client': Client.company_name
        }

        stmt = select(Payment).join(Client, Payment.client_id == Client.id).where(
            Payment.is_active == True,
            Payment.payment_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Payment.payment_date)
        return db.session.execute(stmt.options(db.joinedload(Payment.client))).scalars().all()

    @classmethod
    def _get_expense_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Outgoings (Issued and Completed)."""
        MAP = {
            'date': Expense.expense_date,
            'number': Expense.expense_number,
            'amount': Expense.total_amount,
            'vendor': Vendor.company_name,
            'category': ExpenseCategory.type
        }

        stmt = select(Expense).join(Vendor, Expense.vendor_id == Vendor.id).outerjoin(ExpenseCategory).where(
            Expense.is_active == True,
            Expense.status != 'draft',
            Expense.expense_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Expense.expense_date)
        expenses = db.session.execute(stmt.options(db.joinedload(Expense.category), db.joinedload(Expense.vendor))).scalars().all()

        audit_rows = []
        for exp in expenses:
            is_cogs = exp.category.is_cogs if exp.category else False
            audit_rows.append({
                'obj': exp,
                'cogs_portion': exp.total_amount if is_cogs else 0,
                'opex_portion': exp.total_amount if not is_cogs else 0
            })
        return audit_rows

    @classmethod
    def _get_adjustment_audit(cls, start, end, sort_by=None, direction=None):
        """Chronological justification for Adjustments with dynamic sorting."""
        MAP = {
            'date': Adjustment.adjustment_date,
            'number': Adjustment.adjustment_number,
            'amount': Adjustment.amount,
            'category': AdjustmentCategory.type
        }

        stmt = select(Adjustment).join(AdjustmentCategory).where(
            Adjustment.is_active == True,
            Adjustment.adjustment_date.between(start, end)
        )

        stmt = cls._apply_audit_sorting(stmt, sort_by, direction, MAP, Adjustment.adjustment_date)
        return db.session.execute(stmt.options(db.joinedload(Adjustment.category))).scalars().all()

    @classmethod
    def _get_adjustments_breakdown(cls, start, end):
        """Sums adjustments by category for the P&L statement."""
        stmt = (
            select(AdjustmentCategory.type, func.sum(Adjustment.amount))
            .join(Adjustment).where(
                Adjustment.is_active == True,
                Adjustment.adjustment_date.between(start, end)
            )
            .group_by(AdjustmentCategory.type)
        )
        return [{'category': r[0], 'total': r[1]} for r in db.session.execute(stmt).all()]
    

# --- 60-month financial table  ---

    @classmethod
    def get_historical_summary(cls, years=5):
        """
        Brain: Generates a 60-month gapless financial timeline for PostgreSQL.
        Uses 'extract' for cross-DB compatibility and supports YoY grouping.
        """
        # 1. Setup Time Window
        end_date = date.today().replace(day=1) + relativedelta(months=1) - relativedelta(days=1)
        start_date = (end_date + relativedelta(days=1)) - relativedelta(years=years)
        
        # 2. Initialize the Timeline (The Master Dictionary)
        # Key format: "YYYY-MM" for easy sorting and lookup
        timeline = {}
        curr = start_date.replace(day=1)
        while curr <= end_date:
            key = curr.strftime('%Y-%m')
            timeline[key] = {
                'year': curr.year,
                'month': curr.month,
                'month_label': curr.strftime('%b %Y'),
                'accrual': {'revenue': 0, 'cogs': 0, 'opex': 0, 'adj': 0},
                'cash': {'income': 0, 'cogs_paid': 0, 'opex_paid': 0}
            }
            curr += relativedelta(months=1)

        # 3. Aggregate Data via SQL (Postgres Compatible Extract)
        
        # --- BUCKET A: Accrual Revenue ---
        y_ext = extract('year', Invoice.invoice_date)
        m_ext = extract('month', Invoice.invoice_date)
        
        rev_stmt = (
            select(y_ext, m_ext, func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price))
            .select_from(InvoiceItem).join(Invoice).join(Product).join(ProductCategory)
            .where(Invoice.is_active == True, Invoice.status != 'draft', 
                Invoice.invoice_date.between(start_date, end_date), ProductCategory.is_revenue == True)
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(rev_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['accrual']['revenue'] = total or 0

        # --- BUCKET B: Accrual Expenses ---
        y_ext = extract('year', Expense.expense_date)
        m_ext = extract('month', Expense.expense_date)
        
        exp_acc_stmt = (
            select(y_ext, m_ext, ExpenseCategory.is_cogs, func.sum(ExpenseItem.quantity * ExpenseItem.unit_price))
            .select_from(ExpenseItem).join(Expense).join(ExpenseCategory)
            .where(Expense.is_active == True, Expense.status != 'draft', 
                Expense.expense_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, ExpenseCategory.is_cogs)
        )
        for y, m, is_cogs, total in db.session.execute(exp_acc_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                label = 'cogs' if is_cogs else 'opex'
                timeline[key]['accrual'][label] = total or 0

        # --- BUCKET C: Cash Income (Payments) ---
        y_ext = extract('year', Payment.payment_date)
        m_ext = extract('month', Payment.payment_date)
        
        cash_in_stmt = (
            select(y_ext, m_ext, func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(cash_in_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['cash']['income'] = total or 0

        # --- BUCKET D: Cash Outgoings (Completed Expenses) ---
        # Re-use y_ext/m_ext for Expense.expense_date
        cash_out_stmt = (
            select(y_ext, m_ext, ExpenseCategory.is_cogs, func.sum(Expense.total_amount))
            .join(ExpenseCategory).where(Expense.is_active == True, Expense.status == 'completed',
                                        Expense.expense_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, ExpenseCategory.is_cogs)
        )
        for y, m, is_cogs, total in db.session.execute(cash_out_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                label = 'cogs_paid' if is_cogs else 'opex_paid'
                timeline[key]['cash'][label] = total or 0

        # --- BUCKET E: Adjustments ---
        y_ext = extract('year', Adjustment.adjustment_date)
        m_ext = extract('month', Adjustment.adjustment_date)
        
        adj_stmt = (
            select(y_ext, m_ext, func.sum(Adjustment.amount))
            .where(Adjustment.is_active == True, Adjustment.adjustment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(adj_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['accrual']['adj'] = total or 0

        # 4. Final Processing (Derived Math)
        results = []
        for k in sorted(timeline.keys(), reverse=True):
            m = timeline[k]
            m['accrual']['gross_profit'] = m['accrual']['revenue'] - m['accrual']['cogs']
            m['accrual']['operating_profit'] = m['accrual']['gross_profit'] - m['accrual']['opex']
            m['accrual']['net_income'] = m['accrual']['operating_profit'] + m['accrual']['adj']
            m['cash']['net_cash'] = m['cash']['income'] - (m['cash']['cogs_paid'] + m['cash']['opex_paid'])
            results.append(m)

        return results
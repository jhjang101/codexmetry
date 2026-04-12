from sqlalchemy import select, func, desc, asc, and_, case, extract
from dateutil.relativedelta import relativedelta
from datetime import date
from ..extensions import db
from ..models import (
    Invoice, InvoiceItem, Expense, ExpenseItem, 
    Payment, PaymentType, Adjustment, AdjustmentCategory, 
    Product, ProductCategory, ExpenseCategory, Client, Vendor
)

class ReportService:

    @classmethod
    def get_financial_package(cls, start_date, end_date):
        """Brain: Compiles a 6-table dataset for the Financial Fortress."""
        
        # 1. ACCRUAL DATA (Performance - Based on Issued Documents)
        accrual_revenue = cls._get_revenue_summary(start_date, end_date)
        accrual_expenses = cls._get_expense_summary(start_date, end_date, mode='accrual')
        accrual_adjustments = cls._get_adjustment_summary(start_date, end_date, mode='accrual')
        
        # 2. CASH DATA (Liquidity - Based on Cash Movement)
        cash_payments = cls._get_payment_summary(start_date, end_date)
        cash_expenses = cls._get_expense_summary(start_date, end_date, mode='cash')
        cash_adjustments = cls._get_adjustment_summary(start_date, end_date, mode='cash')
        
        # 3. SUMMARY MATH
        # Accrual Perspective
        accrual_gross_profit = accrual_revenue['total'] - accrual_expenses['cogs']['total']
        accrual_operating_profit = accrual_gross_profit - accrual_expenses['opex']['total']
        accrual_net_income = accrual_operating_profit + accrual_adjustments['total']

        # Cash Perspective
        cash_gross_profit = cash_payments['total'] - cash_expenses['cogs']['total']
        cash_operating_profit = cash_gross_profit - cash_expenses['opex']['total']
        cash_net_cash = cash_operating_profit + cash_adjustments['total']

        return {
            'accrual': {
                'revenue': accrual_revenue,
                'cogs': accrual_expenses['cogs'],
                'gross_profit': accrual_gross_profit,
                'opex': accrual_expenses['opex'],
                'operating_profit': accrual_operating_profit,
                'adjustments': accrual_adjustments,
                'net_income': accrual_net_income
            },
            'cash': {
                'payments': cash_payments,
                'cogs': cash_expenses['cogs'],
                'gross_profit': cash_gross_profit,
                'opex': cash_expenses['opex'],
                'operating_profit': cash_operating_profit,
                'adjustments': cash_adjustments,
                'net_cash': cash_net_cash
            },
            'audit': {
                'invoices': cls._get_invoice_audit(start_date, end_date),
                'payments': cls._get_payment_audit(start_date, end_date),
                'expenses': cls._get_expense_audit(start_date, end_date),
                'adjustments': cls._get_adjustment_audit(start_date, end_date)
            }
        }

    # --- HELPERS (Document Based) ---

    @classmethod
    def _get_revenue_summary(cls, start, end):
        """
        Sums items grouped by category where is_revenue is True 
        from open and completed Invoices.
        """
        stmt = (
            select(
                ProductCategory.type, 
                func.sum(InvoiceItem.quantity * InvoiceItem.billed_unit_price)
            )
            .select_from(InvoiceItem)
            .join(Invoice).join(Product).join(ProductCategory)
            .where(
                Invoice.is_active == True,
                Invoice.status != 'draft',
                Invoice.invoice_date.between(start, end),
                ProductCategory.is_revenue == True
            )
            .group_by(ProductCategory.type)
        )
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}
    
    @classmethod
    def _get_payment_summary(cls, start, end):
        """
        Groups actual cash received by Payment Type
        from Payments.
        """
        stmt = (
            select(
                PaymentType.type, 
                func.sum(Payment.amount)
            )
            .join(PaymentType)
            .where(
                Payment.is_active == True, 
                Payment.payment_date.between(start, end)
            )
            .group_by(PaymentType.type)
        )
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}

    @classmethod
    def _get_expense_summary(cls, start, end, mode='accrual'):
        """Groups Expenses by category, separated into COGS and OPEX."""
        stmt = (
            select(
                ExpenseCategory.type, 
                ExpenseCategory.is_cogs, 
                func.sum(Expense.total_amount)
            )
            .join(ExpenseCategory)
            .where(
                Expense.is_active == True,
                Expense.expense_date.between(start, end)
            )
        )

        # Apply status filters based on accounting perspective
        if mode == 'accrual':
            # Accrual basis looks at all open/completed expenses
            stmt = stmt.where(Expense.status != 'draft')
        else:
            # Cash basis looks only at completed espenses
            stmt = stmt.where(Expense.status == 'completed')
        
        # Group by category and separated into COGS and OPEX
        stmt = stmt.group_by(ExpenseCategory.type, ExpenseCategory.is_cogs)

        results = db.session.execute(stmt).all()
        
        cogs_breakdown = [{'category': r[0], 'amount': r[2] or 0} for r in results if r[1]]
        cogs_total = sum(item['amount'] for item in cogs_breakdown)
        
        opex_breakdown = [{'category': r[0], 'amount': r[2] or 0} for r in results if not r[1]]
        opex_total = sum(item['amount'] for item in opex_breakdown)

        expenses = {
            'cogs': {'total': cogs_total, 'breakdown': cogs_breakdown},
            'opex': {'total': opex_total, 'breakdown': opex_breakdown}
        }
        return expenses
    
    @classmethod
    def _get_adjustment_summary(cls, start, end, mode='accrual'):
        """
        Groups Adjustments by category,
        Accrual mode includes all active
        Cash mode excludes system write-offs.
        """
        stmt = (
            select(
                AdjustmentCategory.type, 
                func.sum(Adjustment.amount)
            )
            .join(AdjustmentCategory)
            .where(
                Adjustment.is_active == True,
                Adjustment.adjustment_date.between(start, end)
            )
        )
        # If cash mode, only include manual entries
        if mode == 'cash':
            stmt = stmt.where(Adjustment.is_system == False)

        # Group by category
        stmt = stmt.group_by(AdjustmentCategory.type)
            
        results = db.session.execute(stmt).all()

        breakdown = [{'category': r[0], 'amount': r[1] or 0} for r in results]
        total = sum(item['amount'] for item in breakdown)

        return {'total': total, 'breakdown': breakdown}
    
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
                'accrual': {'revenue': 0, 'cogs': 0, 'opex': 0, 'total_adj': 0},
                'cash': {'payments': 0, 'cogs_paid': 0, 'opex_paid': 0, 'manual_adj': 0}
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

        # --- BUCKET C: Cash Payments Received ---
        y_ext = extract('year', Payment.payment_date)
        m_ext = extract('month', Payment.payment_date)
        
        cash_in_stmt = (
            select(y_ext, m_ext, func.sum(Payment.amount))
            .where(Payment.is_active == True, Payment.payment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext)
        )
        for y, m, total in db.session.execute(cash_in_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline: timeline[key]['cash']['payments'] = total or 0

        # --- BUCKET D: Cash Paid Expenses (Completed Expenses) ---
        y_ext = extract('year', Expense.expense_date)
        m_ext = extract('month', Expense.expense_date)

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

        # --- BUCKET E & F: Adjustments (Accrual vs Cash) ---
        y_ext = extract('year', Adjustment.adjustment_date)
        m_ext = extract('month', Adjustment.adjustment_date)
        
        adj_stmt = (
            select(y_ext, m_ext, Adjustment.is_system, func.sum(Adjustment.amount))
            .where(Adjustment.is_active == True, Adjustment.adjustment_date.between(start_date, end_date))
            .group_by(y_ext, m_ext, Adjustment.is_system)
        )
        for y, m, is_system, total in db.session.execute(adj_stmt).all():
            key = f"{int(y)}-{int(m):02d}"
            if key in timeline:
                # Every adjustment counts for Accrual
                timeline[key]['accrual']['total_adj'] += (total or 0)
                # Only non-system adjustments count for Cash
                if not is_system:
                    timeline[key]['cash']['manual_adj'] = total or 0

        # 4. Final Processing (Derived Math)
        results = []
        for k in sorted(timeline.keys(), reverse=True):
            m = timeline[k]
            # Accrual Perspctive
            m['accrual']['gross_profit'] = m['accrual']['revenue'] - m['accrual']['cogs']
            m['accrual']['operating_profit'] = m['accrual']['gross_profit'] - m['accrual']['opex']
            m['accrual']['net_income'] = m['accrual']['operating_profit'] + m['accrual']['total_adj']
            
            # Cash Perspective
            m['cash']['gross_margin'] = m['cash']['payments'] - m['cash']['cogs_paid']
            m['cash']['operating_cash'] = m['cash']['gross_margin'] - m['cash']['opex_paid']
            m['cash']['net_cash'] = m['cash']['operating_cash'] + m['cash']['manual_adj']
            
            results.append(m)

        return results
    
    @classmethod
    def get_chart_data(cls, history, perspective='accrual', mode='monthly'):
        """
        Brain: Transforms 60-month history into Monthly, Quarterly, Yearly, 
        or Seasonal Overlay aggregates.
        """
        # 1. Perspective Configuration
        if perspective == 'accrual':
            kpi_keys = ['revenue', 'cogs', 'gross_profit', 'opex', 'operating_profit', 'total_adj', 'net_income']
            sub_key = 'accrual'
            focus_kpi = 'net_income'
            primary_color = '#3b82f6' # Blue spectrum
        else:
            kpi_keys = ['payments', 'cogs_paid', 'gross_margin', 'opex_paid', 'operating_cash', 'manual_adj', 'net_cash']
            sub_key = 'cash'
            focus_kpi = 'net_cash'
            primary_color = '#10b981' # Green spectrum

         # ---------------------------------------------------------
        # MODE A: OVERLAY VIEWS (Seasonal Performance & Growth)
        # ---------------------------------------------------------
        if mode in ['yearly_comparison', 'seasonal_cumulative']:
            this_year = date.today().year
            target_years = [this_year, this_year - 1, this_year - 2]
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            datasets = []
            
            overlay_styles = [
                {'label': f"{this_year}", 'color': primary_color, 'width': 3, 'dash': []},
                {'label': f"{this_year - 1}", 'color': primary_color + '88', 'width': 2, 'dash': []},
                {'label': f"{this_year - 2}", 'color': '#94a3b8', 'width': 1, 'dash': [5, 5]}
            ]

            for i, year in enumerate(target_years):
                year_data = [None] * 12
                running_total = 0
                
                # Filter and sort months for this specific year
                year_months = sorted([m for m in history if m['year'] == year], key=lambda x: x['month'])
                
                for m in year_months:
                    val = m[sub_key].get(focus_kpi, 0) / 100
                    
                    if mode == 'seasonal_cumulative':
                        running_total += val
                        year_data[m['month'] - 1] = running_total
                    else:
                        year_data[m['month'] - 1] = val

                style = overlay_styles[i]
                datasets.append({
                    'label': f"{style['label']} {'(YTD Growth)' if mode == 'seasonal_cumulative' else '(Monthly)'}",
                    'data': year_data,
                    'borderColor': style['color'],
                    'borderWidth': style['width'],
                    'borderDash': style['dash'],
                    'tension': 0.1 if mode == 'seasonal_cumulative' else 0.3,
                    'pointRadius': 3,
                    'fill': i == 0 
                })
            
            return {'labels': labels, 'datasets': datasets}

        # ---------------------------------------------------------
        # MODE B: LINEAR AGGREGATION (Chronological MoM, QoQ, YoY)
        # ---------------------------------------------------------
        raw_data = sorted(history, key=lambda x: f"{x['year']}-{x['month']:02d}")
        aggregated = {}

        for m in raw_data:
            if mode == 'yearly':
                group_key = str(m['year'])
            elif mode == 'quarterly':
                q = (m['month'] - 1) // 3 + 1
                group_key = f"{m['year']} Q{q}"
            else: # monthly
                group_key = m['month_label']

            if group_key not in aggregated:
                aggregated[group_key] = {k: 0 for k in kpi_keys}
            
            for k in kpi_keys:
                aggregated[group_key][k] += (m[sub_key].get(k, 0) / 100)

        labels = list(aggregated.keys())
        if mode == 'monthly': labels = labels[-24:] # Filter to last 2 years for MoM clarity

        datasets = []
        style_map = {
            'revenue': {'color': '#3b82f6', 'width': 3, 'dash': []},
            'payments': {'color': '#10b981', 'width': 3, 'dash': []},
            'net_income': {'color': '#0f172a', 'width': 3, 'dash': []},
            'net_cash': {'color': '#064e3b', 'width': 3, 'dash': []},
            'cogs': {'color': '#ef4444', 'width': 1, 'dash': [5, 5]},
            'cogs_paid': {'color': '#ef4444', 'width': 1, 'dash': [5, 5]},
            'opex': {'color': '#f59e0b', 'width': 1, 'dash': [2, 2]},
            'opex_paid': {'color': '#f59e0b', 'width': 1, 'dash': [2, 2]},
        }

        for k in kpi_keys:
            style = style_map.get(k, {'color': '#94a3b8', 'width': 1, 'dash': [5, 5]})
            datasets.append({
                'label': k.replace('_', ' ').capitalize(),
                'data': [aggregated[l][k] for l in labels],
                'borderColor': style['color'],
                'borderWidth': style['width'],
                'borderDash': style['dash'],
                'tension': 0.3,
                'pointRadius': 2 if len(labels) < 20 else 0
            })

        return {'labels': labels, 'datasets': datasets}
# Reports Technical Reference

The Reports module, representing the **Metry** half of the system identity, provides the high-integrity representation of real-time business data. It functions as a "Truth Engine," isolating operational performance from fund liquidity to provide a comprehensive view of business health.

---

## 1. The Dual-Perspective Framework

Codexmetry processes every financial event through two distinct accounting lenses. This separation is required to distinguish between economic value and available cash.

### A. Accrual Basis (Performance Statement)

Tracks the economic truth of the business based on **Issued Documents**. It measures the value generated and the costs committed during the period, regardless of cash movement.

- **Sales Revenue**: Aggregates all line items from `Open` or `Completed` Invoices where the product category is marked **is_revenue**.
- **Cost of Goods Sold (COGS)**: Aggregates all items from `Open` or `Completed` Expenses where the category is marked **is_cogs**.
- **Gross Profit**: `Sales Revenue` minus `COGS`.
- **Operating Expenses (OPEX)**: Aggregates all items from `Open` or `Completed` Expenses where the category is NOT marked as COGS.
- **Operating Profit (EBIT)**: `Gross Profit` minus `OPEX`.
- **Adjustments**: Includes all manual and system-generated corrections (e.g., Write-offs) recorded during the period.
- **Net Income**: `Operating Profit` plus/minus `Adjustments`. Represents the total profitability for the period.

### B. Cash Basis (Cash Flow Summary)

Tracks the liquidity truth of the business based on **Settled Transactions**. It measures the actual physical movement of funds into and out of the bank accounts.

- **Payments Received**: The sum of all active Payments confirmed during the period.
- **COGS Actually Paid**: Only counts items from Expenses with a status of `Completed` that are marked **is_cogs**.
- **Gross Margin**: `Payments Received` minus `COGS Actually Paid`.
- **OPEX Actually Paid**: Only counts items from Expenses with a status of `Completed` that are NOT marked as COGS.
- **Operating Cash Flow**: `Gross Margin` minus `OPEX Actually Paid`.
- **Adjustments (Manual)**: Only includes non-system adjustments (manual entries) to reflect intentional cash corrections. System write-offs are excluded.
- **Net Cash Income**: `Operating Cash Flow` plus/minus `Manual Adjustments`. Represents the actual change in the bank balance.

---

## 2. Reporting Logic & Flags

The aggregation of reports is driven by specific metadata flags defined in the **Settings** and **Products** modules:

- **is_revenue (Product Category)**: If disabled, items in this category (e.g., "Applied Deposits" or "Security Deposits") are excluded from the Top-line Revenue figure to prevent the artificial inflation of sales metrics.
- **is_cogs (Expense Category)**: Determines if an expense is deducted before or after the "Gross Profit" calculation.
- **is_system (Adjustment)**: System-generated write-offs are included in **Accrual** reports (to correct Net Income) but are excluded from **Cash** reports (as no money moved).
- **Status Guard**:
  - `Draft` documents are **excluded** from all reports.
  - `Open` expenses are recognized as Accrual liabilities but not as Cash outgoings.

---

## 3. Drill-down & Audit Tables

To ensure every metric is verifiable, the Reports module provides detailed audit tables beneath the summary matrices.

- **Traceability**: Each row in the audit tables (Revenue, Payments, Expenses, Adjustments) contains a direct link to the source document.
- **Verification**: These tables allow an Administrator to reconcile high-level statement totals against the specific transactions that created them.
- **Sorting**: Supports server-side sorting by Date, Amount, and Client to assist in period-end reconciliation.

---

## 4. Historical Trends

The Trends engine provides a 60-month linear horizon of business health, allowing for long-term growth analysis and seasonal performance benchmarking.

### A. Linear Aggregation (Time-Series)

The system aggregates raw document data into chronological "buckets" based on the selected granularity. This allows for the identification of long-term trajectories and structural shifts in business performance.

- **Month-over-Month (MoM)**: The default view. Provides a granular 24-month rolling look at revenue velocity and margin stability.
- **Quarter-over-Quarter (QoQ)**: Filters out short-term noise to show fiscal performance trends.
- **Year-over-Year (YoY)**: Executive view of annual growth and long-term profitability.

### B. Seasonal Intelligence (Overlay Logic)

Unlike linear views, Seasonal modes re-map historical data onto a single 12-month axis (January to December). This allows for direct comparison of specific months across the last three fiscal years.

- **Seasonal Performance**: Overlays the absolute monthly performance of the current year against previous years.
  - *Business Logic*: Answers "How did this April compare to last April?"
- **Seasonal Cumulative (YTD Growth)**: Calculates a running total of performance throughout each fiscal year.
  - *Business Logic*: Visualizes the "Growth Velocity." It allows you to see if the current year is reaching financial targets faster or slower than previous years at the same point in time.

### C. Perspective Integration

The Trends engine respects the Dual-Perspective framework, allowing the user to apply the linear and seasonal logic to either side of the ledger:

- **Performance Perspective (Accrual)**: Trends focus on **Net Income** and **Revenue**. It visualizes the economic productivity of the business over time.
- **Liquidity Perspective (Cash)**: Trends focus on **Net Cash** and **Payments Received**. It visualizes the historical patterns of cash availability and burn rates.

### D. Visual Visualization & Interactivity

- **Interactive Legend**: The trend charts support dynamic filtering. By clicking on a KPI in the legend (e.g., "COGS" or "OPEX"), the user can hide that specific dataset to focus on a single metric without reloading the page.

- **PostgreSQL Extraction**: To ensure high performance, the system uses the native `EXTRACT` functions of the PostgreSQL engine to bucket dates, ensuring that even systems with tens of thousands of records can generate 5-year trends in sub-second time.

---

## 5. Performance Analytics & Metrics

The Analytics suite transforms raw transaction data into prioritized rankings and categorical visualizations. This allow for the immediate identification of the primary drivers of revenue and cost.

### A. Client Performance Analytics

This pane provides a ranking of the most significant customer accounts based on yearly volume. It is designed to identify account concentration and customer health.

- **Rank by Volume**: Displays the Top 10 clients by volume in a horizontal bar chart, with a full-ranked list in the supporting data table.
- **Perspective Switch**:
  - *Revenue Perspective*: Ranks clients by the total value of invoices issued. Identifies the "highest value" accounts in terms of economic activity.
  - *Payment Perspective*: Ranks clients by actual cash received. Identifies the most reliable sources of liquidity.
- **Yearly Contribution**: Calculates each client's percentage share of the total business volume for the selected year.

### B. Product Analytics (Market Mix)

Product analytics provide a dual-level view of sales performance, aggregating data by both specific SKUs and high-level categories.

- **Market Mix (Category Level)**: A doughnut visualization representing the distribution of revenue across product categories.
  - *Logic*: Respects the **is_revenue** flag. Only categories marked as revenue drivers are included in this mix.
- **SKU Ranking**: Identifies the specific products generating the most volume.
  - *Metrics Captured*: Total Quantity Sold and Total Revenue Generated per unique Catalog Number.
- **Trend Alignment**: Ensures that product performance aligns with the **Accrual Statement**, providing the "Product Story" behind the monthly revenue figures.

### C. Expense Breakdown (Spend Mix)

The Expense pane analyzes the outward flow of capital, focusing on vendor concentration and the nature of the costs incurred.

- **Vendor Concentration**: Ranks the Top 10 vendors by total spend. Identifies the suppliers who consume the largest portion of operational cash.
- **Spend Mix (Classification Level)**: A doughnut visualization that highlights the balance between **COGS** and **OPEX**.
  - *Visual Logic*: Uses color-coded HSL gradients (Reds for COGS, Ambers for OPEX) to provide an immediate intuitive understanding of cost distribution.
- **Operational Efficiency**: Helps identify if cost increases are driven by direct project costs (COGS) or rising business overhead (OPEX).

### D. Technical Implementation

- **SQL Aggregation**: All rankings are calculated via high-performance `GROUP BY` queries in the service layer, minimizing the data transferred from the database to the application.

- **Dynamic Gradients**: The system utilizes HSL (Hue, Saturation, Lightness) math to generate dynamic color palettes for charts based on the number of categories found, ensuring visualizations remain readable and aesthetically consistent as the business grows.
- **State Persistence (HTMX OOB)**: Analytics panes are delivered via **HTMX Out-of-Band (OOB)** swaps. This architecture allows the user to switch between analytical lenses (e.g., from Product Analytics to Client Performance) while **retaining the currently selected period**.
  - *Logic*: The system automatically includes the active Month/Year filters in every tab-switch request, ensuring the "Financial Truth" remains consistent across all views without requiring a full page refresh.

# Expenses Technical Reference

The Expenses module tracks the operational costs incurred to run the business or fulfill specific client orders. It is the primary driver of the system's **Operating Expense (OPEX)** and **Cost of Goods Sold (COGS)** metrics, and provides project-specific profitability analysis.

---

## 1. Identification & Project Linking

*   **Vendor** [Input]: The supplier or service provider associated with the cost. This field is required.
*   **Expense Number** [Input/System]: The unique identifier for the document. 
    *   *Logic:* Defaults to the `E-YYQSSSV` format (Year, Quarter, Sequence, Checksum), but allows manual override for custom numbering schemes.
*   **Link to Client (Optional)** [Input]: Associates the cost with a specific client account.
    *   *Ripple:* Selecting a Client filters the available Purchase Orders for that client.
*   **Link to PO (Optional)** [Input]: Associates the cost with a specific Purchase Order.
    *   *Ripple:* Selecting a PO automatically prefills the **Client** and **Order Registry (CDX)** links.
*   **Link to Invoice (Optional)** [Input]: Associates the cost with a specific Invoice event.
    *   *Ripple:* Selecting an Invoice automatically prefills the **Client**, **PO**, and **Order Registry (CDX)** links, ensuring a high-integrity connection between revenue and cost.
*   **Order Registry (CDX)** [System]: The permanent anchor for the order's history and metrics. 
    *   *Logic:* Inherited from the linked PO or Invoice. This link is required for the expense to appear in the "Total Linked Expenses" metric within the **Order History**.

---

## 2. Categorization & Lifecycle

*   **Expense Category** [Input]: The categorical classification of the cost (e.g., Office Supplies, Materials, Travel). 
    *   *Ripple:* The **is_cogs** flag assigned to the category in Settings determines whether this expense reduces **Gross Profit** (COGS) or only **Net Income** (OPEX) in financial reports.
*   **Expense Date** [Input]: The legal date the cost was incurred. 
    *   *Ripple:* This date determines which **Monthly Statement** and **Performance Trend** the cost is attributed to.
*   **Status** [Input/System]: Defines the accounting state of the expense:
    *   `Draft`: Work-in-progress. Items do not yet count toward any financial reports.
    *   `Open`: The cost is committed or a Vendor PO has been issued. Recognized in **Accrual Basis** reports.
    *   `Completed`: The expense has been paid. This is the only status recognized in **Cash Basis** reports.

---

## 3. Financial Logic

*   **Summary (Optional)** [Input]: A brief overview of the expense (e.g., "Software Subscription").
    *   *Logic:* If left blank on save, the system automatically populates this field with the description of the first line item.
*   **Total Amount** [System]: The raw mathematical sum of all item lines (recorded in cents).
    *   *Visual:* Displayed in **Red** for positive costs (Standard) or **Green** for negative costs (Refunds/Credits).

---

## 4. Line Item Details (Sub-form)

Unlike Sales documents which use a fixed Product Catalog, Expenses use flexible text-entry rows to accommodate unique vendor descriptions.

*   **Catalog Number** [Input]: The vendor's specific SKU or part number.
*   **Item Name** [Input]: The primary name of a product or service.
*   **Description** [Input]: Supporting details or specifications for the line item.
*   **Quantity** [Input]: The number of units purchased.
*   **Unit Price** [Input]: The cost per unit in cents.
*   **Line Total** [System]: `Quantity` * `Unit Price`. 

---

## 5. Metadata & Accountability

*   **Internal Note** [Input]: Private comments for internal use. Not visible on the printed PDF.
*   **Terms & Notes** [Input]: Instructions or terms included in the PDF footer. Defaults to global system terms on creation but is editable.
*   **Attachments** [Input/System]: Standard file upload for receipts or vendor invoices, and system-generated PDFs during the "Issue" process.
*   **Version Counter** [System]: Increments every time the document is "Issued." Used to track the version of issued PDFs in the attachment zone.
*   **Activity Log** [System]: Displays the chronological record of every change made to the expense, including user identity and the modified fields.


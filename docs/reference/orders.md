# Order Registry (CDX) Technical Reference

The Order Registry, represented by the **CDX** prefix, is the immutable anchor for a confirmed business deal. It provides a unified identity that bridges the gap between Sales (Quotes/POs), Fulfillment (Invoices), and Accounting (Payments/Expenses).

---

## 1. Core Identity Fields

*   **Order Number (CDX)** [System]: The unique, permanent identifier for the project. 
    *   *Logic:* Follows the `CDX-YYQSSSV` format (Year, Quarter, Sequence, Checksum). 
    *   *Integrity:* Generated automatically upon the creation of a Purchase Order. Once assigned, it cannot be manually modified.
*   **Creation Date** [System]: The UTC timestamp of when the deal was first initialized in the registry.
*   **Active Status (is_active)** [System]: A boolean flag used for soft-deletion.
    *   *Ripple:* Setting this to `False` (Archiving) effectively deactivates the entire deal chain, including all linked Invoices and system-generated Write-offs.
    *   *Exception:* **Payments** and **Expenses** associated with the deal are **not** automatically archived. Because these represent actual cash movements and vendor liabilities, they remain active to preserve the accuracy of the general ledger and cash-basis reports. If these financial records also need to be removed, they must be archived manually within their respective modules.

---

## 2. Relationship Mapping

The Order Registry maintains a 1-to-N relationship with every document type in the system. These links are established via the `order_id` foreign key:

*   **Linked Quote**: The original proposal that led to the deal. (1-to-1)
*   **Linked Purchase Order**: The primary contract governing the deal. (1-to-1)
*   **Child Invoices**: Every invoice issued against the deal's Purchase Order.
*   **Child Payments**: Every cash receipt (linked or unlinked) associated with the deal.
*   **Child Expenses**: Every operational cost linked to the deal for profit tracking.
*   **Child Adjustments**: Every non-operating correction (like Write-offs) affecting the deal's balance.

---

## 3. Aggregate Metrics (The Order History)

The Registry does not store financial values directly. Instead, it uses dynamic properties to aggregate data from all child documents in real time. These metrics power the **Order History** visualization:

*   **PO Value** [Property]: The total amount of the linked Purchase Order (the original contract value).
*   **To Be Invoiced** [Property]: The remaining balance to billed from the Purchase Order. 
    *   *Math:* (Value of unfulfilled PO line items) minus (Unapplied Credit Pool). 
    *   *Logic:* This field effectively represents "Backlog" for the Purchase Order.
*   **Total Invoiced (Balance)** [Property]: A dual metric representing both the total amount officially billed and the portion still outstanding.
    *   *Total Invoiced:* The sum of "Total Due" across all active invoices.
    *   *Balance:* The sum of "Invoice Balances" (Total Due - Payments) across those same invoices.
*   **Total Received** [Property]: The sum of all active payments received for this Order, including both invoice-linked payments and unapplied prepayments.
*   **Total Linked Expenses** [Property]: The sum of all active operational costs linked to this CDX number. This is the primary metric for tracking project-specific profitability (Job Costing).
*   **Total Linked Adjustments** [Property]: The sum of all non-operational gains or losses linked to the deal. This includes manual corrections and automated system write-offs.

---

## 4. Forensic Audit (Full Order Timeline)

The Order Registry maintains a dedicated **Audit Timeline** that differs from standard module logs:

*   **Nested History**: The Full Order Timeline captures not only changes to the CDX record itself but also surfaces every action performed on its child documents.
*   **Parent-Child Map**: If an Admin archives a Purchase Order, the Registry log shows the primary action and the resulting "System Ripples" (e.g., the automatic archiving of linked Invoices) as a single, connected event chain.
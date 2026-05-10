# Purchase Orders Technical Reference

The Purchase Order (PO) represents the formal commitment between the business and the client. It initializes the **Order Registry (CDX)** and serves as the system of record for all subsequent Invoices and Payments.

---

## 1. Identification & Relationship Fields

- **Order Ref (CDX)** [System]: The order’s unique identifier. Assigned automatically upon creation of the PO.

- **Quote Number** [Input/System]: Links the PO to its source proposal.
  - *Handshake Logic:* Linking a Quote automatically sets that Quote's status to **Accepted**. Unlinking or archiving the PO reverts the Quote to **Sent** status and clears its `order_id`.
- **Client** [Input]: The primary account holder.
  - *Integrity Lock:* This field becomes read-only once the PO has active child Invoices or Payments, preventing data orphaning.
- **Bill To** [Input]: The specific department or entity responsible for payment. Defaults to the Client but can be manually overridden.
- **PO Number** [Input]: The client-provided document number or your internal reference number.
- **Customer PO #** [Input]: An optional secondary reference used for external distributors or end-users.

---

## 2. Scheduling & Logic Defaults

- **PO Date** [Input]: The legal date of the contract. Defaults to the current business day.
- **PO Type** [Input]: A categorical lookup used to classify orders (e.g., Service, Product, Government).
- **Terms (Net Days)** [Input]: Defaults to the [global payment terms](./settings.md#c-transactional-defaults) but can be overridden for this specific PO.
  - *Ripple:* This value is inherited by every Invoice created from the PO.
- **Status** [System]: The three-stage lifecycle of the PO:
  - `Open`: Items remain to be fulfilled and invoiced.
  - `Invoiced`: All items have been moved to invoices, but invoice balances are not yet fully settled.
  - `Completed`: All items are billed and all invoices are fully paid.

---

## 3. Financial Metrics

- **Total Amount** [System]: The total sum of all PO line items (in cents).
- **Total Prepayment** [Property]: The sum of all cash received for the deal that was not linked to a standard product invoice.
- **Remaining Credit** [Property]: The current available credit balance for the deal.
  - *Math:* `(Prepayments + Applied Deposits) - Negative Carryovers`
- **Balance To Be Invoiced** [Property]: The total value of goods and services not yet billed.
  - *Logic:* Represents the remaining financial backlog of the PO.

---

## 4. Line Item Integrity (Sub-form)

The line items within a PO are protected by strict **Lifecycle Locks** once billing begins:

- **Product & Unit Price:**
  - *Integrity Guard:* These fields become **permanently locked** for a specific line once that line has been included in an active Invoice (including Drafts). This ensures the original contract pricing remains consistent with billed pricing.
- **Quantity:**
  - *Quantity Floor:* A line item’s quantity cannot be reduced below its "Allocated Quantity" (the total units already assigned to active Invoices).
- **Remaining Items** [Property]: A dynamic calculation of all remaining billable items.
  - *Automation:* If the PO contains a [**Remaining Credit**](#3-financial-metrics) balance, the system automatically adds an "[Applied Deposit](./products.md#4-system-products-internal-logic)" line item to suggest credit consumption on the next Invoice.

---

## 5. Metadata & Auditing

- **Internal Note** [Input]: Private comments for internal use.
- **Attachments** [Input]: Standard file upload. Commonly used for storing scanned copies of PO documents.
- **Active Status (is_active)** [System]: Boolean flag used for soft-deletion.
  - *Ripple:* Setting this value to `False` triggers a cascading deactivation of the **Order Registry**, including all linked **Invoices** and system-generated Write-offs.
  - *Exception:* **Payments** and **Expenses** associated with the deal are **not** automatically archived. Because these represent actual cash movements and vendor liabilities, they remain active to preserve the accuracy of the general ledger and cash-basis reports. If these financial records also need to be removed, they must be archived manually within their respective modules.
- **Activity Log** [System]: Displays the chronological record of every change made to the PO, including user identity and the modified fields.

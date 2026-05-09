## 1. Quotes (The Proposal)

The lifecycle typically begins with a **Quote**, your formal offer to a client.

1.  **Drafting:** Select a Client and add Products from your catalog. The system automatically pulls default unit prices.
2.  **Issuing:** Open the **Print Preview** and click **Issue**. The system generates a versioned PDF and attaches it to the record.
3.  **Outcome:**
    *   **Draft:** Initial state while preparing the quote.
    *   **Sent:** Updated automatically upon issuance.
    *   **Accepted:** Status changes once the Quote is converted into a Purchase Order.

---

## 2. Purchase Orders (The Commitment)

The **Purchase Order (PO)** represents a order received and initializes the **Order Registry (CDX)**.

1.  **Initiation:** You can generate a PO in two ways:
    *   **Convert from Quote:** Automatically copies all line items and links the documents.
    *   **Manual Add:** Create a PO directly for a client when no formal quote was required.
2.  **CDX Assignment:** Upon saving, the system assigns a unique **CDX Number**. This number is the permanent anchor for the order's history and metrics.
3.  **Outcome:**
    *   **Open:** goods or services remain to be invoiced.
    *   **Invoiced:** All items have been billed, but payments are pending.
    *   **Completed:** All items are invoiced and all balances are settled.

---

## 3. Invoices (The Fulfillment)

Invoices represent the fulfillment of goods or services and the official request for payment.

1.  **Fulfillment Selection:** Select an active PO. The system automatically prefills the items and quantities remaining to be billed. You can edit these quantities for partial billing.
2.  **Issuing:** Like Quotes, clicking **Issue** in the preview generates a versioned PDF snapshot for the client.
3.  **Outcome:**
    *   **Draft:** Initial state while staging the shipment or billing.
    *   **Open:** The invoice has been issued and is awaiting payment.
    *   **Completed:** The balance has been paid or falls within the **Invoice Threshold**.

---

## 4. Payments (The Settlement)

Payments record the arrival of cash and "close the loop" on outstanding balances.

1.  **Receipt Entry:** Enter the amount received and select the payment type.
2.  **Auto-Reconciliation:**
    *   **Invoice Link:** Apply the payment to a specific invoice to reduce its balance.
    *   **Prepayment:** Leave the invoice field blank to record a deposit. This cash enters the **Credit Pool** for that specific order.
3.  **Completion:** If an invoice's remaining balance falls below the **Invoice Threshold**, the system automatically moves it to **Completed** and generates a **System Write-off** to reconcile the gap.

---

## 5. Expenses (Operational Spend)

Expenses track the costs incurred to run the business or fulfill specific orders.

1.  **Record Cost:** Select a Vendor and enter text descriptions for the items.
2.  **Issuing:** Open the **Print Preview** and click **Issue** to generate a professional PDF. This can be used as a formal Purchase Order for your vendors.
3.  **Link to CDX:** (Optional) Link the expense to a CDX Registry number. This enables "Order Costing" in your Order Histoty to track the exact profitability of a specific deal.
4.  **Outcome:**
    *   **Open:** The cost is committed/ordered but not yet paid.
    *   **Completed:** The expense is fully settled.

---

## 6. Adjustments (Corrections)

Adjustments are single-entry records used for non-operational financial events.

1.  **Manual Entry:** Record items like Bank Interest (Gain) or Annual Fees (Loss).
2.  **Balance Correction:** Automatically created by the [Payment Automation](./workflow.md#5-Payments-the-Settlement) when an invoice is completed with a minor balance gap.

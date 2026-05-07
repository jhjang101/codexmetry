# The Document Lifecycle

Codexmetry is designed to manage the "Chain of Documents" for a business deal. While each module can be used independently, the system is at its most powerful when following the **Golden Path** of document progression.

## 1. Order Registry (Codex)

The core of the system is the **Order Registry** also know as **Codex**. This provides a unique identity (the **CDX** number) that links every Quote, Purchase Order, Invoice(s), Payment(s), Expense(s), and Adjustment(s) together. The Codex is completly managed by system and is visible in detail view in any linked document.

*   **Quotes** exist outside the registry initially before linked to POs.
*   The **Registry ID** is born the moment a Quote is accepted or a manual Purchase Order is created.

---

## 2. The Proposal (Quotes)

The lifecycle typically begins with a **Quote**. This is your formal offer to a client.

1.  **Drafting:** Add products and services. The system pulls default prices from your catalog.
2.  **Issuing:** Clicking "Issue" in print preview automatically generates a versioned PDF snapshot.
3.  **Status:** Until a Quote is linked to a Purchase Order, it remains a "Sent" and does not consume a CDX registry number.

---

## 3. The Commitment (Purchase Orders)

When a client accepts a Quote, you convert it into a **Purchase Order (PO)**.

*   **Conversion:** Converting a Quote automatically copies all line items and links the Quote to the new Order Registry.
*   **The Anchor:** This is the legal foundation of the order. Once a PO is created, a unique **CDX** number is assigned, populating the linked documents and timeline.

---

## 4. The Fulfillment (Invoices)

Invoices represent the fulfillment of goods or the completion of services.

*   **Source Driven:** Every Invoice must stem from an active Purchase Order.
*   **Partial Billing:** You can invoice only a portion of a PO. The system tracks "Remaining Quantity" and prefill the line items with the next invoice.
*   **Credit Utilization:** If a client has a remining credit balance to the PO, you can apply it here using the [Credit Pool logic](../reference/invoices.md#the-credit-pool).

---

## 5. The Settlement (Payments)

Payments represent the actual arrival of cash into the business.

*   **Direct Link:** Payments are linked to specific Invoices to "close the loop."
*   **Prepayments:** You can record a payment against a Purchase Order **before** an invoice has been issued. 
*   **Automation:** When the unpaid balance of an Invoice falls below your global **Invoice Threshold**, the system automatically moves the status to "Completed." The system **automatically generates a Write-off Adjustment** for the underpayment gap.
*   **Self-Healing:** If a payment is archived, the linked Invoice and Purchase Order will automatically "re-open" to reflect the missing funds.

---

## 6. Operational Spend (Expenses)

Expenses represent the costs incurred to run your business or fulfill a specific order. 

*   **Order Cost:** Expenses can be linked to a **CDX Order Registry**. This allows you to track the exact profitability by comparing "Payments Received" vs "Costs Paid" for that specific order.
*   **Itemized Records:** Expenses use manual text descriptions for line items, allowing you to record specific vendor details without needing a pre-defined product in your catalog.
*   **Issuance:** Much like Quotes and Invoices, an Expense can be "Issued" to generate a professional PDF. This can serve as a Purchase Order you send out to your vendors.
*   **Status Management:** 
    *   `Draft`: Planning/Estimating costs.
    *   `Open`: Committed cost, but payment not yet finalized.
    *   `Completed`: The expense is fully paid and settled.

---

## 7. Non-Operational Items (Adjustments)

Adjustments are used to record financial events that do not involve traditional products or services. They are the "Final Reconciliation" tool of the system.

*   **Financial Corrections:** Use manual adjustments to record bank interest, annual fees, tax adjustments, or bad debt.
*   **Dual-Nature:** Adjustments support both positive values (Gains) and negative values (Losses).
*   **System vs. Manual:** 
    *   **Manual**: Created by the user for general business gains/losses.
    *   **System-Generated**: Automatically created by the [Payment Automation](./workflow.md#5-the-settlement-payments) when an invoice is completed with a minor balance gap.
*   **Reporting Impact:** Adjustments are factored into your **Net Income** reports, ensuring that your financial metrics represent the absolute truth of your accounts, including non-operating items.


## 6. Shortcuts (Skipping Steps)

Codexmetry is flexible. You are not required to start every deal with a Quote.

*   **Manual PO:** You can create a Purchase Order directly for a client. This will immediately generate a CDX registry number.
*   **Direct Expense:** You can record an Expense without linking it to a project if it is a general overhead cost (e.g., Office Supplies).
*   **Independent Adjustment:** You can record gains or losses (like Bank Interest) that have no relationship to a client or order.

---

## 7. Lifecycle Visibility

At any point in the deal, you can view the **Order Tree** inside any document. This visualization provides a 360-degree view of the entire chain, showing exactly how much has been quoted, committed, invoiced, and received.
```

### Technical Note:
1.  **Registry Focus:** I have emphasized the "Birth of the CDX" to help users understand why Quotes have a different numbering system than POs.
2.  **Inter-connectivity:** I have included a cross-reference link to the "Credit Pool" section which we will define in the Technical Reference next.
3.  **Shortcuts:** This section satisfies your requirement to explain how the system handles non-standard workflows.

**Next Step:** Are you ready to begin the **Technical Reference** (starting with the field-by-field breakdown for Invoices or Orders)? I await your permission.
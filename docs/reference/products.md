# Products Technical Reference

The Products module serves as the central catalog for all goods and services. It provides the source for document pricing and categorization, ensuring that sales data is accurately mapped to the financial engine and the correct sections of issued PDFs.

---

## 1. Product Identity

*   **Product Name** [Input]: The primary descriptive name of the item.
*   **Catalog Number** [Input]: The unique internal SKU or part number.
    *   *Integrity Constraint*: This field is strictly **Unique**. It prevents duplicate SKU entries and ensures consistent data mapping across sales.
*   **Product Image** [Input]: A visual thumbnail of the product.
    *   *Logic*: When a product is archived, the image remains on the disk to preserve the visual integrity of historical records. Updating an image on an active product automatically deletes the old physical file to prevent storage bloat.

---

## 2. Classification & Logic

*   **Category** [Input]: The grouping assigned to the product (e.g., Services, Hardware).
    *   *Reporting Ripple*: The **is_revenue** flag on the category determines if sales of this product are aggregated into the "Sales Revenue" section of the **Monthly Statement**.
*   **Document Placement** [Input]: **(Critical Logic)** This field determines where the product appears on issued PDFs (Quotes and Invoices).
    *   `Standard Line Item`: The default. Appears in the main body of the document.
    *   `Shipping (Footer)`: Items like "Freight" or "Handling." These are pulled out of the subtotal and displayed in the Shipping section of the PDF footer.
    *   `Sales Tax (Footer)`: Items like "VAT" or "State Tax." These are aggregated into the Tax section of the PDF footer.

---

## 3. Financial Data

*   **Default Unit Price** [Input]: The standard price for one unit of the product (recorded in cents).
    *   *Logic*: This value automatically pre-populates the Unit Price field when adding this product to a Quote or Purchase Order. It remains manually overridable on the individual document level to allow for custom pricing without affecting the master catalog.

---

## 4. System Products (Internal Logic)

Codexmetry utilizes specialized "System Products" that are hidden from the standard product list but are essential for accounting automation:

*   *Applied Deposit (SYS-DEP)*: A system-flagged product used as a negative line item to represent the consumption of a client's credit pool.
*   *Prepayment (PRE-PMT)*: A specific catalog identifier used to generate Deposit Request invoices. These items are restricted to single-line documents to maintain ledger integrity.

---

## 5. Metadata & Auditing

*   **Active Status (is_active)** [System]: A boolean flag used for soft-deletion.
    *   *Integrity Note*: System products cannot be archived. Standard products can be archived to remove them from new document selection while maintaining links to existing orders.
*   **Audit Mixin**: Captures **Created By/At** and **Updated By/At** metadata.
*   **Activity Log**: Displays the chronological record of changes, including user identity and the modified fields.
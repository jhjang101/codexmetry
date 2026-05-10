# Initial Setup & Configuration

Once the Codexmetry environment is deployed, an Administrator must configure the system's identity and master data. This ensures that all generated documents and financial reports reflect the unique requirements of your business.

---

## 1. Company Identity & Branding

Navigate to [**Settings**](../reference/settings.md) to establish the identity of your business. These fields are used to populate the headers and footers of all issued PDFs (Quotes, Invoices, and Expenses).

- **Company Name & Logo:** Your official business name and brand.

- **Addresses:**
  - *Office Address*: Your primary physical location.
  - *Payable Address*: Where clients should mail checks.
  - *Shipping Address*: Where vendors should deliver items.
- **Banking (Wire Transfer):** Provide your Bank Name, SWIFT, Routing, and Account numbers to ensure payment instructions are included on Invoices.

---

## 2. System Logic & Defaults

Configure the core behavioral rules of the application under **System Defaults**:

- **Invoice Threshold:** The maximum remaining balance at which an Invoice will automatically move to "Completed" status.
- **Doc Padding:** Determines the length of the [sequential portion](../reference/settings.md#b-document-padding-yyqsssv) of your document IDs (e.g., Padding of 3 results in `CDX-2620011`).
- **Net Days (Invoices):** Set the default payment terms that automatically populate new documents.
- **Quote Expiry (Days):** Set the default validity period for new Quotes and automatically calculate the expiration date.
- **Default document Terms:** Standard terms that automatically populate the "Terms & Notes" section of PDFs (Quotes, Invoices, and Expenses).

---

## 3. Defining Categories (Lookups)

Lookup tables categorize your data for accurate reporting. Configure these to match your business and industry requirements:

- **PO Types:** (Recommended) Used to distinguish different order types or sales channels.
- **Product Categories:**
  - *Revenue Flag*: If checked, sales of products in this category will be aggregated into the **Sales Revenue** section of your [financial reports](../reference/reports.md).
- **Expense Categories:**
  - *COGS vs. OPEX*: Mark categories as **COGS** (Cost of Goods Sold) for direct costs or leave unmarked for **OPEX** (Operating Expenses). This allows the system to calculate **Gross Profit** accurately.
- **Payment Types:** (Required) Define your accepted methods (e.g., Credit Card, Wire Transfer, Check).
- **Adjustment Categories:** (Required) Define non-operating events (e.g., Bank Interest, Processing Fee).
- **Shipping Carriers:** Define the shipping providers used for fulfillment and tracking.

---

## 4. Building the Catalog (Products)

The Product Catalog serves as the system of record for your Sales documents.

- **Catalog Number:** Your internal SKU or part number.
- **Default Unit Price:** Pre-populates Quotes and Purchase Orders, but can be overridden when creating or editing documents.
- **Document Placement:** **(Critical)**
  - `Standard Line Item`: Standard goods or services.
  - `Shipping (Footer)`: Items assigned to this placement will appear in the "Shipping" section on PDFs.
  - `Sales Tax (Footer)`: Items assigned to this placement will appear in the "Sales Tax" section on PDFs.

---

## 5. Establishing the Accounts (Clients & Vendors)

Before creating orders, you must define your external relationships.

- **Account Labels:** Use a unique and descriptive label for Client and Vendor (e.g., "General Electric-Billing").
- **Company Address:** Provide the shipping or billing address for the account. This is used to populate the "Bill To" or "Vendor" sections on PDFs.
- **Personnel & Contacts:** Each account can contain multiple contacts. The system automatically identifies the **Primary Contact** (the topmost record) and display in the dropdown options when creating or editing documents.
- **Lifecycle Awareness:** The Client view provides immediate visibility into whether an account has open POs or unpaid Invoices, guiding your daily priority. *(TODO)*

# Settings Technical Reference

The Settings module serves as the configuration engine for the application. it manages the global identity of the business, establishes behavioral defaults for system automation, and provides the administration tools for user access and categorization lookups.

---

## 1. Company Metadata (Singleton)

Codexmetry utilizes a singleton data pattern (ID: 1) for system settings, ensuring a single, authoritative configuration for the entire environment.

### A. Identity & Branding
*   **Company Name & Logo** [Input]: The official branding used in the sidebar and document headers.
    *   *File Logic*: Uploading a new logo automatically triggers a physical file cleanup of the previous asset to prevent storage bloat.
*   **Addresses** [Input]: Three distinct blocks (Office, Payable, Shipping) used *"As-is"* to populate different address sections of issued PDFs.
*   **Timezone** [Input]: Defines the `office_tz` used by the system to calculate the "Business Today" date for all new documents.

### B. Banking & Remittance
*   **Wire Transfer Details** [Input]: Includes Bank Name, SWIFT, Routing, and Account numbers.
    *   *Logic*: These fields are dynamically injected into the footer of all issued Invoices to provide clear payment instructions to clients.

---

## 2. System Logic & Defaults

This section defines the automated logic of the application. These settings determine how documents are identified, how they behave upon creation, and the logic used to settle balances.

### A. Financial Automation
*   **Invoice Threshold** [Input]: The maximum remaining balance (in cents) at which the system considers an invoice "fully paid."
    *   *Ripple*: If an invoice balance falls below this value, the system automatically triggers the `Completed` status and generates a **System Write-off** to reconcile the ledger.

### B. Document Padding (YYQSSSV)
<div style="padding-left: 1em;">
Codexmetry uses a document numbering standard designed to balance sequential density with business obfuscation. The length of sequence is controlled by the <strong>Document Padding</strong> setting.
</div>

#### The Identifier Structure

<div style="padding-left: 1em;">
Every generated ID (e.g., `CDX-2620011`) is composed of five logical segments following the prefix:  
</div>

1. **Document Prefix**: Identifies the record type:
    *   `CDX-`: Order Registry (Immutable anchor)
    *   `Q-`: Quotes (Proposals)
    *   `I-`: Invoices (Fulfillment)
    *   `E-`: Expenses (Costs)
    *   `P-`: Payments (Settlement)
    *   `A-`: Adjustments (Corrections)
2. **Year (YY)**: The last two digits of the current business year.  
3. **Quarter/Stage (Q)**: A single-digit indicator of the document's temporal state:
    *   `1-4`: **Standard Quarters**. Matches the fiscal quarter of the year.  
    *   `5-8`: **Overflow Stages**. Triggered if a quarter exceeds its sequence capacity.
    *   `9`: **Emergency Reserve**. Used if standard and overflow stages are exhausted.
4.  **Sequence (SSS)**: The chronological number of the document within its current stage. The length (padding) is defined by the **Document Padding** setting.
5.  **Checksum (V)**: A final forensic digit calculated using a **Sum-of-Digits Mod 10** algorithm to prevent data entry errors.

#### Strategic Benefits & Constraints
*   **Obfuscation**: Incorporating the Year and Quarter hides your total business volume from external parties.
*   **Sequence Density**: The system acts as a "gap-filler." If a low number is skipped manually, the engine will suggest it next to ensure numbering density.
*   **Persistence**: Changing padding affects **new records only**.
!!! Info "Operational Note"
    Updating padding mid-year disrupts chronological sorting. It is a best practice to only update this setting on **January 1st**.

### C. Transactional Defaults
<div style="padding-left: 1em;">
These settings ensure consistency across the document lifecycle and reduce manual data entry.
</div>

*   **Net Days (Invoices)**: The default payment term assigned to new documents. Used to calculate the **Due Date** on the printed PDF.
*   **Quote Expiry (Days)**: The standard validity period for proposals.
*   **Default Document Terms**: Standard legal text or instructions for Quotes, Invoices, and Expenses.
    *   *Visibility Logic*: To maintain a clean data-entry interface, these terms are **hidden** during the primary Add/Edit modes.
    *   *Override Workflow*: Terms become visible and manually overridable only within the **Print Preview** screen. The final version is saved to the record only when the document is "Issued."

---

## 3. User Management & Security

The User Management suite handles account lifecycle and enforces Role-Based Access Control (RBAC).

### A. Access Roles
*   **Admin**: The system superuser. Has unrestricted access to all modules, including **Settings**, and **Maintenance**.
*   **User**: The primary operational role. Can create and edit standard business documents (Quotes, POs, Invoices, etc.) but is restricted from accessing the Settings and Maintenance.
*   **Viewer**: An audit-only role. Has read-only access across the entire system but cannot create, modify, or delete any data.

### B. Integrity Protections
*   **Destructive Actions**: The ability to **Archive** (Soft-delete) any document or master data record is strictly reserved for the **Admin** role. This prevents the unauthorized removal of transaction evidence from the live system.
*   **Root Account Protection**: The primary administrator account (marked `is_root`) is system-protected. It cannot be disabled, its role cannot be changed, and its password is managed exclusively via the environment configuration (`.env`).

---

## 4. Lookup Table (Lookups)

Lookups provide the categorization required for accurate data grouping and financial reporting. Codexmetry utilizes a categorization table to provide a standardized administration interface.

### A. Behavioral Logic Ripples
<div style="padding-left: 1em;">
Entries in Lookup tables drive specific system behaviors and reporting classifications:
</div>

*   **PO Types**: Used to segment the Order Registry by sales channel or contract type (e.g., "Service Contract" vs. "Government PO").
*   **Product Categories**:
    *   *Reporting Impact*: Each category carries an **is_revenue** flag. If enabled, all products within this category are aggregated into the "Sales Revenue" line of the Performance Statement.
*   **Expense Categories**:
    *   *Reporting Impact*: Each category carries an **is_cogs** flag. This determines if an expense is treated as a direct cost (Cost of Goods Sold) or indirect overhead (OPEX), directly affecting the **Gross Profit** metric.
*   **Payment Types**: Required for the **Cash Flow Summary**. These categories allow the business to analyze liquidity by source (e.g., "How much of our cash came via Wire Transfer vs. Credit Card?").
*   **Adjustment Categories**: Includes both manual categories (e.g., Bank Interest, Processing Fees) and the system-protected "Write-off" category used for automated balance reconciliation.
*   **Shipping Carriers**: Selection of a carrier within an Invoice dynamically enables the **Ship Date** and **Tracking Number** fields.

### B. The Reactivation Pattern (Integrity Guard)
<div style="padding-left: 1em;">
To preserve the integrity of historical records, lookups use a <strong>Reactivation Pattern</strong> instead of standard duplication:
</div>
*   *Logic*: If a user attempts to add a category that was previously archived (soft-deleted), the system automatically identifies the existing record and reactivates it (`is_active = True`).
*   *Benefit*: This prevents the creation of duplicate IDs and ensures that historical documents using that category remain correctly linked and searchable.

---

## 5. Metadata Auditing
*   **Activity Log**: All changes to the company configuration are recorded under the permanent label **"Company Configuration"**. This provides professional clarity in the Audit Log, distinguishing global system changes from individual transaction updates.
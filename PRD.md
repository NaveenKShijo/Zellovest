# Product Context: AI-Native Procurement Intelligence Platform

I am designing an AI/ML-enabled procurement intelligence platform for mid-market DTC and omnichannel businesses. The platform is intended to help procurement teams understand, control, and optimize company-wide software and vendor spending by connecting financial transactions, SaaS usage, contracts, invoices, purchase orders, and vendor documents into one unified system.

The system should not merely act as a dashboard. Its goal is to become an intelligent procurement operating layer that continuously detects inefficient spending, identifies contractual/commercial issues, prepares procurement teams for renewals and negotiations, and allows users to investigate the entire procurement data landscape through a conversational AI interface.

The initial scalability target is approximately **500–1,000 concurrent/active users** per deployment, running on an architecture designed as a dedicated **single-tenant system** (deployed per customer/organization or VPC).

---

# 1. Target Customer

The primary target customer is a mid-market software technology companies, generally in the range of approximately **$10M–$50M annual revenue**, with substantial spending across software, vendors, and corporate cards.

Typical characteristics:

* Significant SaaS/vendor spend.
* Corporate cards used by employees across departments.
* Multiple SaaS subscriptions and vendor relationships.
* Contracts, invoices, POs, amendments, and other procurement documents scattered across cloud drives and other systems.
* Procurement teams that currently depend heavily on spreadsheets, manual document review, fragmented systems, and delayed information.
* A procurement organization that needs to reduce unnecessary spend, detect commercial leakage, improve contract compliance, reclaim unused licenses, and prepare better vendor negotiations.
* Heightened focus on strict data privacy, compliance, and security that benefits directly from an isolated, single-tenant deployment boundary.

Typical decision-makers/users include:

* VP of Procurement
* Head of Procurement
* Procurement Manager
* Strategic Sourcing Manager
* Procurement Analyst
* AP / Accounts Payable personnel
* Finance stakeholders
* IT/SaaS management stakeholders

The core organizational problem is that procurement information is fragmented across financial systems, identity/usage systems, documents, contracts, invoices, and vendor communications. This makes it difficult to understand the complete financial and operational relationship with each vendor.

---

# 2. Core Problem

Procurement teams often see different pieces of the same vendor relationship in different places:

```text
Corporate Card
      +
Contracts
      +
Purchase Orders
      +
Invoices
      +
License Data
      +
Usage Data
      +
Vendor Documents
      +
Renewal Terms

```

These are often analyzed independently.

The platform's goal is to unify these sources and create a **vendor-level and procurement-level intelligence layer**.

For example, instead of analyzing an invoice independently, the system should understand:

```text
Vendor
 ├── Contract
 ├── Contract amendments
 ├── Purchase Orders
 ├── Invoices
 ├── Card Transactions
 ├── Licenses
 ├── License Usage
 ├── Renewal Terms
 ├── Historical Spend
 └── Vendor Documents

```

This creates a **Vendor 360 / Procurement 360** view.

The platform should help answer questions such as:

* Where are we spending money unnecessarily?
* Which employees are purchasing software outside approved procurement channels?
* Which software licenses are unused?
* Which invoices do not comply with contractual terms?
* Which contracts are approaching renewal?
* What leverage do we have during renewal negotiations?
* What does our contract with a vendor actually say?
* Why was a particular invoice flagged?
* Which approved internal tools overlap with an unapproved SaaS product?
* How much potential savings or avoided spend can procurement identify?

---

# 3. Major Data Sources

The initial data sources are:

### A. Corporate card transactions

Primary source:

**Ramp Developer API**

Potential ingestion mechanisms:

* REST/API integration
* Webhooks
* Scheduled synchronization
* Incremental synchronization

These transactions are used to identify potentially unmanaged or inefficient SaaS spending, especially recurring software subscriptions purchased directly by employees using corporate cards.

---

### B. SaaS/license usage

Primary source:

**Okta**

This data provides information about application usage and user activity.

It is primarily used to determine:

* License utilization
* Last activity
* Inactive users
* Potential zombie licenses
* Potentially reclaimable seats
* Cost associated with unused licenses

---

### C. Procurement/vendor documents

Potential sources include:

* Google Drive
* Amazon S3
* Dropbox
* Other cloud storage systems
* Manual upload as a fallback

Documents may include:

* Contracts
* Contract amendments
* Invoices
* Purchase orders
* Agreements
* Vendor policies
* Supporting procurement documents
* Other vendor-related documents

---

# 4. Data Ingestion Architecture

The platform should support multiple ingestion mechanisms:

```text
External Sources
      │
      ├── APIs
      │   ├── Webhooks
      │   └── Scheduled synchronization
      │
      ├── File integrations
      │   ├── Google Drive
      │   ├── S3
      │   ├── Dropbox
      │   └── Other cloud storage
      │
      └── Manual upload

```

Manual upload should exist as a fallback when automated integrations are unavailable.

The ingestion layer should normalize external data into the deployment’s internal canonical data model.

---

# 5. Document Intelligence Pipeline

The platform needs to ingest many different types of PDFs/documents.

Documents are not all processed the same way.

### Structured PDFs

For predictable tables or stable templates:

```text
PDF
 ↓
Python parser / pdfplumber / table extraction
 ↓
Structured data

```

### Unstructured or semi-structured invoices

Use document-understanding models that examine the document and map extracted information into a predefined schema.

### Scanned/image-based documents

Use OCR/document intelligence services such as:

* Google Cloud Document AI
* AWS Textract
* Azure AI Document Intelligence

---

# 6. Document Router

The intended architecture is:

```text
                    Documents
                        │
                        ▼
                 Document Router
                        │
             ┌──────────┴──────────┐
             │                     │
     Known stable template    Variable layout
             │                     │
             ▼                     ▼
     Python extraction        Document AI / LLM
             │                     │
             └──────────┬──────────┘
                        ▼
                  Common Schema
                        │
                        ▼
                    Validation
                        │
                        ▼
                     Database

```

The goal is to avoid unnecessarily using expensive AI models for documents that can be extracted reliably with deterministic methods.

---

# 7. Detailed Document Processing Pipeline

For example:

```text
Google Drive
     │
     ▼
File Ingestion
     │
     ▼
Cloud Object Storage (Isolated Instance Bucket)
     │
     ▼
Document AI
     │
     ├── OCR
     ├── Form parsing
     ├── Table extraction
     ├── Custom extraction
     └── Invoice parsing
     │
     ▼
Text + Layout + Tables
+ Key-Value pairs
+ Confidence Scores
     │
     ▼
Document Classifier
     │
     ├── Invoice
     ├── Purchase Order
     └── Contract
     │
     ▼
Schema Mapping
     │
     ▼
Validation
     │
     ├── High confidence
     │        ↓
     │     Database
     │
     └── Low confidence
              ↓
        Human Review
              ↓
         Correction
              ↓
          Database

```

Human-in-the-loop review is important for low-confidence extractions.

---

# 8. Data Provenance and Explainability

Every important extracted field should retain provenance.

For example:

```json
{
  "field": "renewal_date",
  "value": "2027-04-15",
  "confidence": 0.97,
  "source_document": "salesforce_contract.pdf",
  "page": 14,
  "bounding_box": "...",
  "extraction_method": "document_ai",
  "extracted_at": "..."
}

```

This enables the AI system to answer:

> "Salesforce automatically renews on April 15."

while allowing the user to navigate to:

**Source → Contract → Page 14**

This is a key enterprise trust and auditability requirement.

---

# 9. Contract-to-Invoice Compliance / AP Audit Engine

One of the core product features is an automated reconciliation system that determines whether invoices comply with the commercial terms agreed with vendors.

The system should connect:

```text
Vendor
 │
 ├── Contract
 │     └── Agreed pricing / commercial terms
 │
 ├── Contract Amendments
 │
 ├── Purchase Orders
 │
 ├── Invoices
 │
 └── Card Transactions

```

The purpose is to move from document-level analysis to **vendor-level commercial intelligence**.

---

# 10. Contract Extraction → Operational Database

The contract document should be treated as the original legal source.

However, the system should extract the contractual terms once and store them in a structured operational database.

For example:

```text
Contract PDF
     │
     ▼
Document AI / OCR / LLM
     │
     ▼
Extract contractual terms
     │
     ▼
Human verification where necessary
     │
     ▼
Structured Contract Database

```

Examples of extracted terms:

```text
Vendor
Product/service
Agreed unit price
Currency
Unit of measurement
Quantity limits
Discounts
Taxes
Payment terms
Freight terms
Price escalation
Effective date
Expiration date
Renewal date
Termination notice
Renewal conditions

```

The system should not ask an LLM to reread a 50-page contract every time an invoice arrives.

Instead:

**Document AI/LLM interprets the contract → structured terms are persisted → deterministic reconciliation uses those terms.**

---

# 11. Contract Versioning and Amendments

Contract terms must be versioned rather than overwritten.

For example:

```text
contract_id | product | price | effective_from | effective_to
------------|---------|-------|----------------|------------
C001        | A       | 100   | 2026-01-01     | 2026-06-30
C001        | A       | 110   | 2026-07-01     | 2026-12-31

```

Contract amendments may modify previous terms.

Therefore, the system should maintain an auditable relationship between:

```text
Original Contract
      ↓
Amendment 1
      ↓
Amendment 2
      ↓
Renewal
      ↓
Price Revision

```

Historical terms must not be destroyed because they may be needed to explain why a historical invoice was valid or invalid.

---

# 12. Reconciliation Engine

When a new invoice arrives:

```text
New Invoice
     │
     ▼
Invoice Extraction
     │
     ▼
Identify Vendor
     │
     ▼
Identify Product / Service
     │
     ▼
Find Applicable Contract
     │
     ▼
Find Applicable Contract Version
     │
     ▼
Retrieve Structured Terms
     │
     ▼
Apply Rules
     │
     ▼
Compare Invoice vs Contract
     │
     ▼
Reconciliation Result

```

Rules may include:

* Price rules
* Quantity rules
* Date rules
* Discount rules
* Tax rules
* Payment-term rules
* Freight rules
* Contract-specific conditions

Example:

```text
Contract price = $120/user
Invoice price  = $140/user

Variance = +16.7%

→ Exception

```

The reconciliation engine itself should be primarily deterministic.

---

# 13. Procurement Investigation Agent

When the deterministic reconciliation engine detects an exception, the platform should have an AI **Procurement Investigation Agent**.

Example:

```text
Invoice #INV-23891
Discrepancy = $4,800

```

A simple system might display:

```text
Contract price: $120/user
Invoice price: $140/user
Variance: +16.7%

```

The Investigation Agent should go further and investigate the cause.

It can inspect:

```text
Invoice
   ↓
Contract
   ↓
Purchase Order
   ↓
Previous invoices
   ↓
Card transactions
   ↓
Vendor history
   ↓
Contract amendments
   ↓
Renewal terms

```

It should produce a detailed, evidence-based explanation such as:

> The invoice is charging $140/user instead of the contracted $120/user. The contract signed in March specifies $120/user until March 2027. A July 14 amendment increases the price to $140 for 20 additional seats. However, the invoice applies the new price to 35 seats. The remaining 15 seats appear to be outside the amendment.

The agent should provide citations/evidence for its claims and distinguish:

* Confirmed facts
* Calculated values
* Possible explanations
* Areas requiring human review

The agent should investigate rather than autonomously approve financial decisions.

---

# 14. Maverick / Unmanaged SaaS Spend Detection

Another major product capability is identifying **maverick spending through corporate card transactions**.

The problem:

Employees can independently subscribe to SaaS tools using corporate cards without going through procurement.

Some of these tools may:

* Duplicate existing enterprise software
* Create unnecessary recurring expenses
* Bypass negotiated procurement agreements
* Increase software sprawl
* Increase total SaaS costs

The system should distinguish genuine business expenses such as:

```text
Travel
Meals
Transportation
Office expenses

```

from recurring SaaS subscriptions that may warrant procurement intervention.

---

# 15. Stage 1 — Unsupervised Transaction Clustering

The first stage is ML-based detection.

The question is:

> "Is this transaction an unmanaged recurring software subscription that warrants procurement intervention, or is it a normal business expense?"

Potential features include:

* Transaction cadence
* Recurrence interval
* Dollar magnitude
* Merchant category
* Merchant/domain
* Transaction frequency
* Historical behavior
* Employee behavior patterns

Example:

```text
$20 → Cursor.sh
every ~30 days
recurring
SaaS merchant

```

The unsupervised ML system identifies it as a likely recurring SaaS subscription.

This is primarily an **ML/analytical system**, not an autonomous agent.

---

# 16. Stage 2 — Context Resolution

After identifying a suspicious/unmanaged SaaS subscription, the system needs to understand what the merchant/software actually does.

For example:

```text
Cursor
   ↓
AI-assisted code editor
   ↓
Code completion
Code generation
Refactoring
Developer productivity

```

Context resolution may use:

* Merchant/domain metadata
* External vendor information
* Web/company information
* Internal vendor records
* AI-generated capability descriptions

The objective is to create a semantic representation of the tool's capabilities.

---

# 17. Stage 3 — Vector Embedding Retrieval

The capability description is embedded into a vector representation and compared with the organization's **approved/contracted software catalog**.

Example:

```text
Unmanaged Tool
     │
     ▼
Capability description
     │
     ▼
Embedding
     │
     ▼
Vector similarity search
     │
     ▼
Approved software catalog

```

Example:

```text
Cursor
    ↓
Embedding
    ↓
Cosine similarity
    ↓
GitHub Copilot Enterprise = 0.91

```

The system can then determine:

> The company already has an enterprise agreement for a tool with overlapping capabilities.

This enables an operational recommendation such as:

> Notify the employee that an approved internally contracted tool already exists.

Potential integrations may include:

* Slack
* Microsoft Teams
* Internal procurement workflow

A possible outcome is a one-click path to the approved software.

This capability should not be confused with document RAG. Both use embeddings/vector retrieval, but they serve different purposes:

### Document RAG

Retrieves relevant document passages.

### Software capability matching

Retrieves semantically similar software/products based on capabilities.

---

# 18. Zombie License Detection

Another major feature is identifying licenses/seats that have been purchased but are not being meaningfully used.

Primary source:

**Okta / application usage data**

The first implementation is intended to be primarily **rule-based/analytical**, not agentic.

Example logic:

```text
License
   ↓
Last activity
   ↓
Usage frequency
   ↓
Utilization
   ↓
Inactive threshold
   ↓
Potential zombie license

```

Example:

```text
Purchased licenses: 500
Active users: 391
Inactive licenses: 109

```

The system should calculate:

* Utilization rate
* Number of inactive seats
* Cost of inactive seats
* Potential recoverable spend
* Potential savings

Agents may later help **investigate why licenses are inactive**, but the basic detection itself should remain deterministic.

---

# 19. Renewal Intelligence / Renewal Agent

The platform should continuously monitor contract and vendor renewal events.

The document-processing layer extracts information such as:

```text
Vendor
Contract start
Contract end
Renewal date
Auto-renewal
Notice period
Price escalation
Termination clause
Payment terms

```

The extracted information is stored in the database.

A scheduled renewal process identifies upcoming renewals, for example:

```text
120 days before renewal
90 days before renewal
60 days before renewal
30 days before renewal

```

The **Renewal Agent** then investigates the commercial context.

It may consider:

```text
Contract
+
Spend
+
License usage
+
Utilization
+
Invoice history
+
Previous negotiations
+
Vendor performance
+
Contract clauses

```

Example output:

### Adobe Renewal Preparation

```text
Current annual spend: $94,200
Renewal date: December 14
Current utilization: 61%
Unused licenses: 23
Spend increased: 18% YoY
Contract permits reduction at renewal
Previous negotiated discount: 12%

```

The agent may prepare:

```text
Potential procurement actions:

1. Remove unused licenses.
2. Request pricing for a longer-term commitment.
3. Ask vendor to maintain current unit pricing.
4. Confirm the contractual termination/notice deadline.

```

The agent **prepares the recommendation**.

The procurement professional retains decision-making authority over the actual negotiation and financial commitment.

---

# 20. Negotiation Copilot

The Renewal Agent also acts as a negotiation preparation/copilot layer.

A procurement user should be able to ask:

> "Prepare me for the Salesforce renewal."

The system should combine:

```text
Contract terms
+
Current spend
+
Historical spend
+
License utilization
+
Unused licenses
+
Previous invoices
+
Previous negotiations
+
Vendor performance
+
Contractual leverage

```

It may generate:

* Current commercial position
* Renewal timeline
* Utilization situation
* Potential savings opportunities
* Contractual constraints
* Negotiation questions
* Relevant historical information
* Supporting evidence

It should cite the underlying sources for important claims.

It is a **copilot/preparation system**, not an autonomous negotiator.

---

# 21. RAG for Vendor Research

RAG is intended to allow procurement users to research vendors and their contractual/policy information.

Documents may include:

* Contracts
* Vendor agreements
* Amendments
* Policies
* Procurement documents
* Invoices
* Other vendor-related documents

Example questions:

> "What is our renewal notice period for Adobe?"

> "What does the contract say about price increases?"

> "What are our termination rights?"

> "Which amendment changed the seat pricing?"

The system should retrieve relevant document chunks and provide:

* Answer
* Source document
* Page/section
* Relevant passage/citation

The vector store contains metadata such as:

```json
{
  "vendor_id": "...",
  "document_id": "...",
  "document_type": "contract",
  "page": 14,
  "section": "Renewal Terms"
}

```

Because each deployment is a single-tenant instance, all vectors reside exclusively in that organization’s isolated vector index/collection.

---

# 22. Ask AI

The product should contain an **Ask AI** interface that functions as a natural-language procurement analyst.

The objective is not merely to build a chatbot that retrieves documents.

Ask AI should be able to reason over:

```text
Structured procurement data
+
Analytics
+
ML outputs
+
Contracts
+
Invoices
+
Vendor documents
+
License data
+
Transaction data
+
RAG
+
Procurement agents

```

Conceptually:

```text
                         ASK AI
                            │
                    Intent / Planning
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
      Data/SQL           RAG/Search       Agent Tools
        Tools               Tools             │
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                      LLM Reasoning
                            │
                            ▼
                    Answer + Evidence

```

---

# 23. Ask AI: Questions It Should Support

### Spend

```text
How much did we spend on SaaS last quarter?

What are our top vendors by spend?

Which vendors increased their spend by more than 20%?

Which employees have recurring unmanaged SaaS subscriptions?

```

### Contracts

```text
Which contracts renew in the next 90 days?

Which vendors have automatic renewal?

What are the price escalation clauses?

What is the termination notice period for Vendor X?

```

### Invoices

```text
Which invoices have reconciliation exceptions?

Why was this invoice flagged?

What is the total value of invoice discrepancies this quarter?

```

### Licenses

```text
How many unused Salesforce licenses do we have?

How much are our zombie licenses costing us?

Which SaaS applications have the lowest utilization?

```

### Maverick spend

```text
Which unmanaged SaaS tools were detected this month?

Which unapproved tools appear to overlap with existing enterprise software?

Which departments have the highest unmanaged SaaS spend?

```

### Vendor intelligence

```text
Give me a complete overview of Adobe.

What is our annual spend with Adobe?

When does the contract renew?

How many licenses are unused?

What are the current contract terms?

What invoice discrepancies have we found?

What should procurement investigate before renewal?

```

### Cross-domain reasoning

Ask AI should also answer questions requiring multiple systems:

> "Why did our SaaS spend increase this quarter?"

It may combine:

```text
SQL
+
Transactions
+
Maverick-spend ML
+
License utilization
+
Invoices
+
Contracts
+
RAG

```

and produce a synthesized explanation.

---

# 24. Ask AI Action Capabilities

Ask AI should eventually support both **read tools** and **action tools**.

### Read tools

Examples:

```text
Search contracts
Search invoices
Search vendors
Get vendor spend
Get license utilization
Find renewals
Investigate reconciliation exception
Search documents
Search vendor policies
Calculate spend
Calculate savings

```

### Low-risk action tools

Examples:

```text
Create procurement task
Create review task
Generate report
Create renewal reminder
Prepare negotiation brief
Start human review workflow

```

### High-risk actions

These should require explicit human confirmation:

```text
Approve invoice
Cancel contract
Remove licenses
Modify contract terms
Change purchase order
Send external vendor communication
Commit financial spend

```

The system should preserve human control over consequential financial/procurement decisions.

---

# 25. MCP Architecture and Server Requirements

The product will use **Model Context Protocol (MCP)** as the controlled capability interface between the Agentic Reasoning Service and the systems from which it needs procurement information or into which it may take actions.

MCP is used here as a protocol boundary, not as a replacement for the database, RAG layer, ML pipelines, integrations, or deterministic business logic. The Agentic Reasoning Service is the MCP host/client; MCP servers expose narrowly scoped tools and, where useful, resources or prompt capabilities. Current MCP SDK documentation describes clients and servers negotiating protocol capabilities and supports local stdio plus remote Streamable HTTP transports; legacy HTTP+SSE exists for compatibility with older deployments.

## 25.1 Number of MCP Servers

The initial product architecture defines **three logical MCP servers**:

```text
                         AGENTIC REASONING SERVICE
                         FastAPI + LLM Host + MCP Client
                                      │
                     ┌────────────────┼────────────────┐
                     │                │                │
                     ▼                ▼                ▼
              ┌────────────┐  ┌────────────┐  ┌────────────┐
              │ MCP SERVER │  │ MCP SERVER │  │ MCP SERVER │
              │     1      │  │     2      │  │     3      │
              │ Procurement│  │ Document   │  │ External   │
              │ Intelligence│ │ Knowledge  │  │ Systems    │
              └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
                    │                │                │
                    ▼                ▼                ▼
              PostgreSQL       Vector DB / S3     ERP / Slack /
              + analytics      + provenance       Email / Actions
```

These are **logical capability boundaries**. They may be deployed as three independently running services/processes, or initially as separate modules/processes inside one deployment if operational simplicity is more important. The interface contract remains three distinct MCP servers even if the first deployment packages them together.

The three-server split is based on three materially different responsibilities:

1. **Procurement Intelligence MCP Server** — controlled access to structured procurement data, calculations, deterministic reconciliation results, and ML outputs.
2. **Document Knowledge MCP Server** — controlled access to documents, semantic retrieval, document passages, and provenance.
3. **External Systems MCP Server** — controlled access to external applications and side-effecting actions such as procurement tasks, Slack messages, email, and ERP workflows.

This division avoids giving one general-purpose server broad access to the entire environment and makes permissions, monitoring, testing, and failure isolation easier to reason about.

## 25.2 MCP Server 1 — Procurement Intelligence

### Requirement

Expose safe, domain-level access to the structured procurement system and analytical outputs without allowing the LLM to issue unrestricted SQL or directly manipulate the production database.

### Why it is required

The Agentic Reasoning Service must answer questions about spend, vendors, contracts, invoices, licenses, renewals, reconciliation exceptions, and ML detections. Those answers require authoritative structured data and deterministic calculations.

The server therefore becomes the **business-data tool boundary** between the agent and PostgreSQL/analytics.

### Primary data dependencies

```text
PostgreSQL
   │
   ├── Vendors
   ├── Contracts
   ├── Contract Versions
   ├── Invoices
   ├── Purchase Orders
   ├── Transactions
   ├── Licenses
   ├── Usage
   └── Renewal data

Analytics / ML Outputs
   │
   ├── Maverick SaaS detection
   ├── License utilization
   ├── Spend trends
   └── Reconciliation exceptions
```

### Initial tool set

```text
get_vendor()
get_contract()
get_invoice()
get_purchase_order()
get_vendor_spend()
get_license_usage()
find_renewals()
get_reconciliation_exception()
compare_invoice_contract()
get_maverick_spend()
get_spend_trend()
calculate_spend()
calculate_savings()
```

Tools must expose **business-level operations**, not generic database primitives such as `execute_sql()`.

### Requirements

* Read operations should be strongly preferred for Ask AI.
* Tool schemas must be explicit and validated.
* All results must include enough metadata to support evidence and auditability.
* Financial calculations must come from deterministic application services, not LLM arithmetic.
* The server must apply authorization and tenant checks before accessing PostgreSQL.
* The server should enforce pagination, row limits, timeouts, and query complexity limits.
* Destructive database operations must not be exposed through this server.

## 25.3 MCP Server 2 — Document Knowledge

### Requirement

Expose controlled access to the document intelligence and RAG layer so the agent can search, retrieve, and cite procurement evidence without unrestricted object-store or vector-database access.

### Why it is required

Procurement investigations depend on contracts, amendments, invoices, purchase orders, vendor policies, and source documents. The agent needs semantic retrieval plus exact provenance so that answers can be traced back to the original evidence.

### Primary data dependencies

```text
Object Storage (S3/GCS/Azure Blob)
             │
             ▼
     Document Processing
             │
             ▼
      Text + Layout + Tables
             │
             ▼
        Vector Store
             │
             ▼
    Provenance / Metadata
```

### Initial tool set

```text
search_documents()
search_contracts()
search_invoices()
search_vendor_policies()
search_document_chunks()
get_document()
get_document_page()
get_document_section()
get_source_provenance()
```

### Requirements

* Retrieval must support filtering by vendor, document type, document ID, date, and other tenant-local metadata.
* Retrieval results should return source document, page/section, and provenance metadata whenever available.
* The server must not expose arbitrary object-store browsing to the LLM.
* The server must not allow cross-tenant vector retrieval.
* Document retrieval should distinguish source content from model-generated summaries.
* Important claims returned to the reasoning service should carry evidence references.

## 25.4 MCP Server 3 — External Systems and Actions

### Requirement

Provide a controlled integration boundary for reading external systems and executing procurement workflow actions, while preventing direct LLM access to ERP, Slack, email, or other external credentials.

### Why it is required

The procurement agent eventually needs to move from analysis into operational workflows such as creating review tasks, preparing renewal workflows, notifying employees, and interacting with enterprise systems. Those operations can have real-world side effects and therefore require a dedicated security boundary.

### Potential dependencies

```text
ERP / Finance Systems
       │
Slack / Microsoft Teams
       │
Email
       │
Procurement Workflow Systems
       │
Other approved enterprise APIs
```

### Initial tool set

```text
lookup_external_vendor()
search_external_system()
create_procurement_task()
create_review_task()
create_renewal_reminder()
prepare_renewal_brief()
start_human_review_workflow()
send_slack_message()
send_email()
submit_procurement_workflow()
```

### Risk classes

```text
READ-ONLY
  lookup_external_vendor()
  search_external_system()

LOW-RISK WRITE
  create_procurement_task()
  create_review_task()
  create_renewal_reminder()
  start_human_review_workflow()

HIGH-RISK / CONSEQUENT
  approve_invoice()
  cancel_contract()
  modify_contract_terms()
  change_purchase_order()
  send_external_vendor_communication()
  commit_financial_spend()
```

High-risk operations must require explicit human confirmation. The agent can prepare the action, show the user the proposed parameters and evidence, and then execute only after confirmation.

### External-system sandbox / dry-run requirement

Where an external API supports it, actions should support a **dry-run/preview mode** that returns the exact intended operation without committing the change. This is particularly useful for testing and for human approval workflows.

## 25.5 Agentic Reasoning Service as MCP Host/Client

The Agentic Reasoning Service is responsible for coordinating the three MCP servers.

```text
User Question
     │
     ▼
Intent Classification / Planning
     │
     ▼
Tool Selection
     │
     ├──────────────► MCP-1 Procurement Intelligence
     │
     ├──────────────► MCP-2 Document Knowledge
     │
     └──────────────► MCP-3 External Systems
     │
     ▼
Evidence / Tool Results
     │
     ▼
LLM Reasoning / Synthesis
     │
     ▼
Answer + Evidence + Proposed Actions
     │
     ▼
Human Confirmation for consequential actions
```

The MCP client should maintain one logical connection/session per MCP server where the deployment model supports it, discover server capabilities and tools, validate tool inputs, enforce timeouts, and attach correlation identifiers to calls. MCP client implementations negotiate protocol and server capabilities during initialization.

The reasoning service must not treat a successful tool response as permission to ignore application authorization. Authorization remains an underlying service responsibility.

## 25.6 MCP Transport Requirements

The transport choice depends on where the server runs:

```text
LOCAL / DEVELOPMENT
Agentic Reasoning Service
        │
      stdio
        │
      MCP Server
```

```text
DEPLOYED / PRODUCTION
Agentic Reasoning Service
        │
  Streamable HTTP
        │
   MCP Server
```

The current MCP SDK documentation supports stdio for subprocess-based local communication and Streamable HTTP for deployed HTTP connections. Older HTTP+SSE transport is retained for backwards compatibility rather than being the preferred protocol for new deployments.

Therefore, product diagrams should not describe **SSE as the default production MCP transport**. The UI may still use SSE for streaming Ask AI responses from the FastAPI application, while the MCP client-to-server transport should normally use Streamable HTTP in production.

## 25.7 MCP Tool Contract Requirements

Every tool should define:

```text
Tool name
Description
Input JSON schema
Output schema
Required authorization scope
Allowed roles
Tenant boundary
Read/write classification
Risk classification
Timeout
Idempotency behavior
Evidence/provenance behavior
Audit event type
```

Example:

```json
{
  "name": "get_vendor_spend",
  "description": "Return authoritative spend totals for one vendor and time range.",
  "inputSchema": {
    "vendor_id": "string",
    "start_date": "date",
    "end_date": "date"
  },
  "risk": "read_only",
  "authorization": "procurement.spend.read",
  "tenant_scoped": true
}
```

## 25.8 MCP Failure Handling

The Agentic Reasoning Service must handle MCP failures explicitly.

Requirements:

* Tool timeout must produce a controlled error rather than fabricated data.
* A failed MCP server must not cause the LLM to infer that data does not exist.
* The UI should distinguish unavailable data from a confirmed zero result.
* Retries must be bounded and preferably limited to idempotent operations.
* External action tools must use idempotency keys where duplicate execution could create financial or operational problems.
* MCP request/response latency must be observable per server and tool.
* Circuit breakers should prevent a failing external integration from cascading into the whole agent system.

## 25.9 MCP Observability and Audit

Each MCP invocation should produce an auditable event containing at least:

```text
correlation_id
request_id
tenant_id
user_id / service_identity
mcp_server
mcp_tool
tool_version
risk_class
authorization_result
start_time
latency
success / failure
error_class
result_size
```

Sensitive request arguments and returned document contents should be redacted or hashed according to the platform's logging policy.

## 25.10 MCP Deployment Model

For each dedicated customer environment:

```text
Customer Deployment
│
├── Agentic Reasoning Service
│    └── MCP Client
│
├── MCP Server 1 — Procurement Intelligence
│    └── PostgreSQL / analytics / ML outputs
│
├── MCP Server 2 — Document Knowledge
│    └── Vector Store / Object Storage / Provenance
│
└── MCP Server 3 — External Systems
     └── ERP / Slack / Email / Workflow APIs
```

MCP servers should be independently restartable and deployable, but the initial implementation may package them inside one customer deployment to reduce operational overhead. A later deployment can move them to independently scaled services without changing the logical tool contracts.

## 25.11 MCP Non-Goals

MCP should **not** be used to:

* Replace PostgreSQL.
* Replace the RAG pipeline.
* Replace deterministic reconciliation logic.
* Replace Celery/Redis background jobs.
* Give the LLM unrestricted SQL access.
* Give the LLM unrestricted access to object storage.
* Bypass RBAC or tenant isolation.
* Automatically approve financial decisions.

MCP is the controlled **interface layer** between agentic reasoning and enterprise capabilities.

## 25.12 MCP Acceptance Criteria

The initial MCP implementation is complete when:

1. Exactly three logical MCP servers are available to the Agentic Reasoning Service.
2. MCP Server 1 provides authoritative procurement/analytics tools without unrestricted SQL execution.
3. MCP Server 2 provides document retrieval with vendor/document/page provenance.
4. MCP Server 3 provides controlled external-system access with explicit risk classes.
5. All MCP requests are tenant-scoped and server-authorized.
6. High-risk actions require explicit human confirmation.
7. Production MCP connections use Streamable HTTP; stdio is supported for local development/testing.
8. Tool schemas, timeouts, audit events, and error handling are implemented consistently.
9. An unavailable MCP server cannot cause the model to fabricate missing information.
10. The architecture supports replacing or independently scaling an MCP server without changing the product's core business data model.

# 26. AI vs Deterministic Logic

A major architectural principle of the product is:

## Use deterministic systems for things that should be deterministic.

Examples:

```text
Invoice reconciliation
Contract price comparison
License inactivity detection
Spend calculations
Renewal date calculations
Variance calculations
Financial totals
Authorization
Permissions & Role-Based Access Control (RBAC)

```

## Use AI/agents where investigation and synthesis are valuable.

Examples:

```text
Investigating why an invoice is anomalous
Preparing renewal intelligence
Preparing negotiation briefs
Researching vendor information
Explaining complex procurement situations
Connecting evidence across multiple sources
Natural-language interaction

```

The product should not make something "agentic" merely for the sake of using AI.

---

# 27. Proposed Backend Architecture

The deployment target scale is roughly 500–1,000 active users for an individual customer environment.

The system uses a small number of well-defined backend services rather than immediately creating dozens of microservices. The AI layer is separated from the operational and data-access layers through a controlled MCP tool boundary.

A possible architecture is:

```text
                         React / Next.js
                              │
                              ▼
                    API Gateway / Ingress
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              Procurement APIs    Ask AI / SSE API
                    │                   │
                    │                   ▼
                    │        Agentic Reasoning Service
                    │        FastAPI + LLM Host + MCP Client
                    │                   │
                    │          ┌────────┼────────┐
                    │          │        │        │
                    │          ▼        ▼        ▼
                    │       MCP-1    MCP-2    MCP-3
                    │       Data &   Document External
                    │       Analytics Knowledge Systems
                    │          │        │        │
                    │          ▼        ▼        ▼
                    │       Postgres  Vector   ERP/Slack/
                    │                  DB/S3    Email/etc.
                    │
                    └──────────┬────────────────────────────┐
                               ▼                            │
                         Async Job Platform                │
                           Redis + Celery                   │
                               │                            │
                  ┌────────────┼────────────┐               │
                  ▼            ▼            ▼               │
              ML Workers   Document     Integration         │
                           Workers       Workers             │
                  │            │            │               │
                  └────────────┼────────────┘               │
                               ▼                            │
                    Data / Intelligence Stores              │
               PostgreSQL + Object Store + Vector Store     │
```

The **Agentic Reasoning Service** is the MCP host/client. It should own conversation state, intent interpretation, planning, tool selection, tool-call orchestration, model interaction, streaming to the UI, and answer synthesis. It should not directly access PostgreSQL, the vector store, object storage, ERP, Slack, or email.

The three MCP servers provide the controlled capability boundary described later in this document.

Potential backend technology choices:

* React / Next.js for frontend.
* Python / FastAPI for backend APIs and the Agentic Reasoning Service.
* Python MCP SDK or another official MCP SDK for MCP client/server implementation.
* Dedicated PostgreSQL instance as operational/OLTP database.
* Dedicated Redis for caching and asynchronous queues.
* Celery or equivalent workers for background processing.
* Dedicated S3/GCS/Azure Blob bucket for source documents.
* Vector database or PostgreSQL with `pgvector` for semantic retrieval.
* Document AI/OCR services for difficult documents.
* LLMs for extraction, reasoning, summarization, and agent workflows.

# 28. Single-Tenant Architecture and Security Model

The platform follows a **dedicated single-tenant deployment architecture**. Each customer organization operates within its own completely isolated compute, data storage, and retrieval boundaries (e.g., dedicated database, dedicated object storage container/bucket, and dedicated vector store or namespace).

The fundamental entity hierarchy within an instance is:

```text
Organization (Deployment Instance)
 │
 ├── Users & Roles (RBAC)
 ├── Vendors
 ├── Contracts
 ├── Invoices
 ├── Purchase Orders
 ├── Transactions
 ├── Licenses
 ├── Usage
 └── Documents
```

Security and isolation guarantees:

1. **Physical and Logical Isolation:** No customer data is co-mingled in shared tables or shared vector databases. This eliminates risks associated with cross-tenant data leaks or missing where-clause vulnerabilities.
2. **Access Control (RBAC):** Within the organization, tools and APIs enforce granular user roles (e.g., `user_id`, `role`, `departmental_permissions`).
3. **Dedicated Encryption & Keys:** Each instance can use organization-managed encryption keys (KMS) for data at rest (PostgreSQL, Object Storage, Vector Store) and TLS for data in transit.
4. **Tool Enforcement:** The LLM is never trusted to enforce security or authorization. All data access is strictly governed by the underlying API, MCP server, and database access policies.
5. **MCP Server Isolation:** Each MCP server runs with a narrow service identity and only the minimum data-source permissions required for its declared tools.
6. **Tenant Context Propagation:** Every MCP request must carry an authenticated, server-verifiable tenant/deployment context. The MCP server must not rely on the LLM to supply or preserve tenant boundaries correctly.
7. **Action Authorization:** Read-only tools and side-effecting tools must be distinguishable. High-risk tools require explicit human confirmation before execution.
8. **Auditability:** Every tool invocation should be logged with tenant, actor, server, tool, parameters or a safe parameter hash, result status, authorization decision, latency, and correlation ID, subject to sensitive-data logging rules.

For remote MCP deployments, production systems should use the current MCP HTTP transport and an authenticated service-to-service channel. Legacy HTTP+SSE support may be retained only when interoperability with an older server requires it. The current MCP SDK documentation identifies Streamable HTTP as the production transport and SSE as an older transport kept for compatibility.

For any externally reachable MCP endpoint, MCP authorization/security controls must be treated as part of the deployment boundary. MCP documentation specifies authorization discovery and token validation requirements for protected servers, including restricting tokens to the intended resource server.

# 29. Core Design Principles

The system should follow these principles:

### 1. Evidence-first AI

Important AI claims should be traceable back to source data or documents.

### 2. Deterministic financial logic

Financial calculations and compliance decisions should not depend on an LLM hallucinating an answer.

### 3. Human-in-the-loop

Low-confidence document extraction and consequential procurement actions should allow human verification.

### 4. Versioned commercial truth

Contract amendments and changing commercial terms must preserve historical states rather than overwrite them.

### 5. Unified vendor identity

Transactions, contracts, invoices, POs, licenses, and documents referring to the same vendor should resolve to a common vendor entity.

### 6. Separation of ingestion, intelligence, and presentation

Data ingestion should be independent from the application/API layer and should support asynchronous processing.

### 7. AI tools instead of unrestricted database access

The agent should interact with procurement capabilities through controlled tools exposed by the MCP layer. MCP servers should provide domain-scoped capabilities rather than generic infrastructure primitives.

Agents should interact through controlled tools such as:

```text
get_vendor()
get_contract()
get_invoice()
get_vendor_spend()
get_license_usage()
find_renewals()
compare_invoice_contract()
search_documents()
create_task()

```

rather than being given unrestricted database access.

### 8. Single-tenant data sovereignty

Customer data, documents, and embeddings must remain strictly isolated within that customer's deployment boundary, making enterprise compliance and auditing straightforward.

---

# 30. Expected Business Outcomes

The intended business outcomes are:

### Spend optimization

Reduce unnecessary and unmanaged SaaS spending.

### Maverick-spend reduction

Identify employee-purchased software that bypasses procurement and determine whether an existing approved tool can replace it.

### License optimization

Identify inactive/zombie licenses and quantify potentially recoverable spend.

### Contract compliance

Detect invoice and commercial discrepancies before they result in unnecessary payments.

### Renewal preparedness

Provide procurement teams with advance visibility into upcoming renewals.

### Negotiation leverage

Give procurement teams evidence-based information about:

* Spend
* Usage
* Contract terms
* Unused seats
* Historical pricing
* Vendor performance
* Renewal conditions

### Operational efficiency

Reduce manual time spent searching:

```text
Contracts
Invoices
Spreadsheets
Vendor documents
Card transactions
License reports

```

### Procurement intelligence

Provide a unified view of the economic relationship between the company and each vendor.

### Explainability and auditability

Every important financial/procurement recommendation should be supported by source evidence.

---

# 31. Product Vision

The long-term vision is to create an **AI-native procurement intelligence platform** where procurement teams do not need to manually navigate multiple disconnected systems to understand vendors and company spending.

Instead, they should be able to ask:

> "What is happening with this vendor?"

and the platform should be capable of combining:

```text
Spend
+
Contracts
+
Invoices
+
Purchase Orders
+
Card transactions
+
License usage
+
Historical data
+
Vendor documents
+
ML insights
+
AI investigation

```

to provide an evidence-backed answer.

The product should evolve from:

```text
Data collection
      ↓
Reporting
      ↓
Detection
      ↓
Investigation
      ↓
Recommendation
      ↓
Human-approved action

```

rather than jumping directly to autonomous financial decision-making.

---

# 32. When advising on this product

When proposing architecture, technologies, ML approaches, AI models, agent designs, database schemas, APIs, infrastructure, or UX, preserve the following fundamental distinction:

```text
                 PROCUREMENT INTELLIGENCE PLATFORM

          ┌──────────────────────┴─────────────────────┐
          │                                            │
          ▼                                            ▼
    Deterministic / ML                           Generative / Agentic
        Systems                                      Systems
          │                                            │
          ├── Reconciliation                          ├── Ask AI
          ├── Maverick spend detection                 ├── Renewal Agent
          ├── Zombie-license detection                 ├── Negotiation Copilot
          ├── Spend calculations                       ├── Investigation Agent
          └── Contract rule evaluation                 └── Vendor research / RAG

```

Do not unnecessarily turn deterministic financial logic into agentic workflows.

The core value proposition is the combination of:

**Unified procurement data + structured commercial knowledge + ML detection + document intelligence + RAG + agentic investigation + human-controlled action.**

When suggesting improvements, optimize for:

* Reliability
* Explainability
* Auditability
* Security & strict single-tenant data isolation
* Simple, reproducible deployment patterns (e.g., Helm/Terraform/Docker Compose per customer)
* Cost efficiency
* Scalability (500–1,000 active users per instance)
* Procurement usefulness
* Human oversight
* Clear separation between factual evidence and AI-generated interpretation.

# Appendix A. Consolidated Functional Requirements

The following requirements summarize the product capabilities with the MCP layer included.

## A.1 Data and ingestion

* Integrate Ramp Developer API for corporate card transactions.
* Integrate Okta for application/license usage data.
* Integrate Google Drive, S3, Dropbox, and manual upload for procurement documents.
* Normalize incoming data into the canonical model for the dedicated customer deployment.
* Support asynchronous ingestion, incremental synchronization, and webhooks where available.

## A.2 Document intelligence

* Route stable table-based documents to deterministic extraction where reliable.
* Route variable/unstructured/scanned documents to Document AI/OCR/LLM processing.
* Classify documents as invoices, purchase orders, contracts, or other vendor documents.
* Extract structured terms and preserve provenance.
* Support human review for low-confidence extraction.

## A.3 Procurement intelligence

* Maintain unified vendor identity across transactions, contracts, invoices, POs, licenses, and documents.
* Maintain contract versions and amendment lineage.
* Reconcile invoices against applicable contract versions deterministically.
* Detect maverick SaaS spend using ML/analytical methods.
* Match unmanaged software capabilities against approved software using embeddings/vector retrieval.
* Detect zombie licenses using utilization data and rules.
* Track upcoming renewals and renewal notice periods.

## A.4 Agentic capabilities

* Investigate reconciliation exceptions using structured data plus documents.
* Prepare renewal intelligence.
* Prepare negotiation briefs.
* Research vendors and contractual policies with RAG.
* Support cross-domain Ask AI questions.
* Produce answers with evidence and clear distinction between confirmed facts, calculations, possible explanations, and human-review areas.

## A.5 MCP requirements

* Provide exactly three logical MCP servers in the initial architecture.
* Keep MCP Server 1 focused on structured procurement intelligence.
* Keep MCP Server 2 focused on document knowledge and provenance.
* Keep MCP Server 3 focused on external integrations and actions.
* Make all server tools tenant-scoped and authorization-aware.
* Prevent arbitrary SQL, raw object-store browsing, and direct external credential access by the LLM.
* Require human confirmation for consequential financial/procurement actions.
* Use Streamable HTTP for production MCP server connections and stdio for local development/testing.
* Record auditable tool-call metadata.

## A.6 Non-functional requirements

* 500–1,000 active users per dedicated customer environment.
* Strict single-tenant isolation.
* Evidence-first responses for material procurement claims.
* Deterministic financial calculations.
* Bounded retries and graceful degradation for failed integrations.
* Observable MCP tool latency and failures.
* Reproducible deployment using Docker/Helm/Terraform or equivalent.
* Cost-efficient use of document AI and LLM inference.
* Human oversight for low-confidence extraction and high-risk actions.



# Appendix B. MCP Protocol Reference

The MCP-specific architecture in this PRD uses the current Model Context Protocol client/server model. The Agentic Reasoning Service acts as the host/client and connects to each logical MCP server. The design uses stdio for local development/testing and Streamable HTTP for production service-to-service communication. Legacy HTTP+SSE may be supported for interoperability with older MCP servers but is not the default for new production deployments.

The protocol reference used during preparation was the official Model Context Protocol SDK and authorization documentation available on September 25, 2026.


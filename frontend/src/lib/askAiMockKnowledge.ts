/**
 * Ask AI Mock Knowledge Base & Domain Simulation (PRD #23, #24, #25)
 *
 * Provides realistic responses with evidence-grounded facts, calculations,
 * hypotheses, needs-review items, data gaps, citations with exact pages and bboxes,
 * and low-risk + high-risk proposed actions.
 */

import { AskAIResponse, ActionPreviewResponse, ActionConfirmResponse } from '@/types/askAi';

export interface PromptPresetItem {
  id: string;
  category: 'Spend' | 'Contracts' | 'Invoices' | 'Licenses' | 'Maverick' | 'Vendor 360' | 'Cross-Domain';
  prompt: string;
  label: string;
  description: string;
}

export const PRD_PROMPT_PRESETS: PromptPresetItem[] = [
  // Spend
  {
    id: 'spend-quarter',
    category: 'Spend',
    prompt: 'How much did we spend on SaaS last quarter?',
    label: 'Last Quarter Spend',
    description: 'Deterministic total across approved AP ledger and card transactions',
  },
  {
    id: 'spend-top',
    category: 'Spend',
    prompt: 'What are our top vendors by spend?',
    label: 'Top Vendors by Spend',
    description: 'Ranked annual and quarterly spend breakdown by vendor',
  },
  {
    id: 'spend-increase',
    category: 'Spend',
    prompt: 'Which vendors increased their spend by more than 20%?',
    label: 'Spend Increases > 20%',
    description: 'YoY spend growth anomalies and price jump detection',
  },
  {
    id: 'spend-unmanaged',
    category: 'Spend',
    prompt: 'Which employees have recurring unmanaged SaaS subscriptions?',
    label: 'Recurring Card Subscriptions',
    description: 'Corporate card transactions flagged for recurring shadow software',
  },

  // Contracts
  {
    id: 'contracts-renewals-90d',
    category: 'Contracts',
    prompt: 'Which contracts renew in the next 90 days?',
    label: 'Renewals Next 90 Days',
    description: 'Contract terms, notice deadlines, and auto-renew status',
  },
  {
    id: 'contracts-auto-renew',
    category: 'Contracts',
    prompt: 'Which vendors have automatic renewal?',
    label: 'Auto-Renewal Clauses',
    description: 'Clauses with automatic evergreen rollover and notice windows',
  },
  {
    id: 'contracts-escalation',
    category: 'Contracts',
    prompt: 'What are the price escalation clauses?',
    label: 'Price Escalation Caps',
    description: 'Extracted contractual price increase caps vs actual billed amounts',
  },
  {
    id: 'contracts-notice',
    category: 'Contracts',
    prompt: 'What is the termination notice period for Datadog?',
    label: 'Datadog Termination Notice',
    description: 'Notice deadlines, required written notice period, and cancellation terms',
  },

  // Invoices & Exceptions
  {
    id: 'invoices-exceptions',
    category: 'Invoices',
    prompt: 'Which invoices have reconciliation exceptions?',
    label: 'Reconciliation Exceptions',
    description: 'Deterministic 3-way match failures against contracted rate cards',
  },
  {
    id: 'invoices-why-flagged',
    category: 'Invoices',
    prompt: 'Why was this invoice flagged?',
    label: 'Invoice Flag Deep-Dive',
    description: 'Line item unit price variance, uncontracted SKUs, and rate card drift',
  },
  {
    id: 'invoices-discrepancies-total',
    category: 'Invoices',
    prompt: 'What is the total value of invoice discrepancies this quarter?',
    label: 'Discrepancies Total',
    description: 'Total variance amount identified and recoverable savings',
  },

  // Licenses & Forecast
  {
    id: 'licenses-unused',
    category: 'Licenses',
    prompt: 'How many unused Salesforce licenses do we have?',
    label: 'Unused Salesforce Licenses',
    description: 'Active contracted tier vs Okta 30/60/90-day login activity',
  },
  {
    id: 'licenses-commit-forecast',
    category: 'Licenses',
    prompt: 'How many seats should we commit to at renewal?',
    label: 'Seat Commitment Forecast',
    description: 'ML churn projection and optimal seat commitment recommendation',
  },
  {
    id: 'licenses-low-utilization',
    category: 'Licenses',
    prompt: 'Which SaaS applications have the lowest utilization?',
    label: 'Lowest Utilization Apps',
    description: 'Zombie licenses and underutilized enterprise SaaS portfolios',
  },

  // Maverick & Overlap
  {
    id: 'maverick-detected',
    category: 'Maverick',
    prompt: 'Which unmanaged SaaS tools were detected this month?',
    label: 'Unmanaged SaaS Detected',
    description: 'Ramp corporate card ingestion and shadow software discovery',
  },
  {
    id: 'maverick-overlap',
    category: 'Maverick',
    prompt: 'Which unapproved tools appear to overlap with existing enterprise software?',
    label: 'Semantic Software Overlap',
    description: 'Embedding similarity between unmanaged tools and enterprise contracts',
  },
  {
    id: 'maverick-dept-spend',
    category: 'Maverick',
    prompt: 'Which departments have the highest unmanaged SaaS spend?',
    label: 'Maverick Spend by Dept',
    description: 'Engineering, Marketing, and Sales unmanaged card breakdown',
  },

  // Vendor 360
  {
    id: 'vendor-360-adobe',
    category: 'Vendor 360',
    prompt: 'Give me a complete overview of Adobe.',
    label: 'Adobe 360 Overview',
    description: 'Commercial terms, spend, unused licenses, and pre-renewal checklist',
  },
  {
    id: 'vendor-360-datadog',
    category: 'Vendor 360',
    prompt: 'What should procurement investigate before renewal?',
    label: 'Pre-Renewal Checklist',
    description: 'Flagged invoice variances, consumption spikes, and leverage points',
  },

  // Cross-Domain Reasoning
  {
    id: 'cross-domain-why-up',
    category: 'Cross-Domain',
    prompt: 'Why did our SaaS spend increase this quarter?',
    label: 'Why Did Spend Increase?',
    description: 'Cross-domain synthesis: SQL + Card Ingestion + Maverick + Okta + Contracts',
  },
  {
    id: 'cross-domain-renewals-underutilized',
    category: 'Cross-Domain',
    prompt: 'Which upcoming renewals have low Okta license utilization?',
    label: 'Renewals vs Inactive Seats',
    description: 'Correlate 90-day renewal deadlines with inactive seat telemetry to downscope licenses',
  },
  {
    id: 'cross-domain-shadow-saas-audit',
    category: 'Cross-Domain',
    prompt: 'Identify unmanaged corporate card spend that duplicates existing enterprise contracts.',
    label: 'Shadow SaaS vs Rate Cards',
    description: 'Cross-correlate Ramp employee card expenses against existing enterprise MSA discounts',
  },
];

/**
 * Curated knowledge base matching PRD #23 domains with realistic citations,
 * exact pages, bboxes, structured sections, data gaps, and actions.
 */
export const MOCK_RESPONSES: Record<string, Partial<AskAIResponse>> = {
  // 1. Cross-Domain: Why Did Spend Increase?
  'why did our saas spend increase this quarter?': {
    answer: `### SaaS Spend Increase Analysis (Q3 vs Q4 2026)

Our total SaaS spend increased by **$114,800 (+14.2%)** this quarter. Synthesizing data across **SQL spend ledgers, Ramp corporate card transactions, Jev AI maverick detection, Okta license telemetry, and contract amendments**, the increase is driven by three distinct factors:

1. **Approved Enterprise Expansion (48% of increase)**:
   - **Salesforce**: Added 150 Enterprise Sales Cloud seats on August 15th following headcount growth in Global Sales (+$19,875/mo).
   - Grounded in Amendment #2 to MSA-SF-9921 signed Aug 12, 2026.

2. **Unmanaged / Maverick SaaS Subscriptions (31% of increase)**:
   - Jev AI detected **14 unmanaged subscriptions** on corporate credit cards totaling **$35,600**.
   - Notable overlaps: **Notion AI** ($8,400) and **Miro Team** ($6,200) expensed across Engineering & Marketing, overlapping directly with our approved Enterprise Confluence & Figma agreements.

3. **Invoice Rate Overbillings & Tier Creep (21% of increase)**:
   - **Datadog**: Incurred **$14,200** in unapproved log-ingestion surcharges over the contracted baseline on Invoice \`INV-4419-DATADOG\`.
   - **Salesforce**: Billed at **$145/user/mo** instead of the contracted rate card cap of **$132.50/user/mo**, causing **$12,500** in price variance.`,
    confidence: 0.94,
    processing_time_ms: 1420,
    intent: 'cross_domain_spend_investigation',
    plan_source: 'mcp-1-procurement,mcp-2-document,mcp-3-external',
    sections: {
      facts: [
        'Total Q4 SaaS spend was $924,800 compared to $810,000 in Q3 (+$114,800).',
        'Salesforce contract Amendment #2 authorized 150 additional seats at $132.50/user/mo.',
        '14 unmanaged software subscriptions were charged to employee corporate cards in the last 90 days.',
        'Invoice INV-2024-8841 billed unit price of $145.00 vs contracted $132.50.',
      ],
      calculations: [
        'Contracted expansion impact: +$55,104 / quarter (48.0% of total variance).',
        'Unmanaged card transaction total: +$35,600 / quarter (31.0% of total variance).',
        'Invoice pricing discrepancies identified: +$24,096 / quarter (21.0% of total variance).',
        'Annualized recoverable discrepancy if disputed: $98,400.',
      ],
      hypotheses: [
        'Marketing department ad-hoc adoption of Miro was prompted by cross-agency collaboration prior to product launch.',
        'Datadog overage was triggered by debug-level log retention during Kubernetes cluster migration in September.',
      ],
      needs_review: [
        'Finance must review invoice INV-2024-8841 and dispute the $12,500 overbilling before payment date.',
        'IT Procurement should consolidate Notion users into existing Confluence enterprise license.',
      ],
    },
    citations: [
      {
        source_type: 'document',
        source_id: 'doc-sf-msa',
        description: 'Salesforce Enterprise MSA (MSA-SF-9921) — Rate Card Schedule & Tier Terms',
        excerpt: 'Section 4.2: Unit price per Sales Cloud Enterprise license is fixed at $132.50/seat/month through Dec 31, 2026. Any annual price adjustments must not exceed 3.0%.',
      },
      {
        source_type: 'document',
        source_id: 'doc-datadog-ent',
        description: 'Datadog Enterprise Agreement (DD-ENT-2024-B) — Log Management Overages',
        excerpt: 'Schedule B: Additional log retention beyond 15-day contracted threshold requires 30-day prior written notification or standard on-demand pricing shall be capped at 1.1x negotiated base.',
      },
      {
        source_type: 'database',
        source_id: 'reconciliation-ap',
        description: 'Zellovest AP 3-Way Match Ledger — Exception Item EXC-001',
        excerpt: 'Discrepancy: $12,500.00 unit price variance on INV-2024-8841. Rule: PRICE_CREEP_DETECTED.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-1',
        kind: 'document',
        title: 'Salesforce MSA Rate Schedule (Page 4)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-sf-msa',
        page: 4,
        section: 'Section 4.2: Commercial Pricing & Tier Commitments',
        bbox: [72.0, 520.0, 540.0, 610.0],
        excerpt: 'The committed subscription fee for Sales Cloud Enterprise Edition shall remain fixed at $132.50 per user per month. Supplier agrees that no rate increases shall take effect prior to December 31, 2026.',
      },
      {
        evidence_id: 'ev-2',
        kind: 'document',
        title: 'Datadog Enterprise Agreement (Page 7)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-datadog-ent',
        page: 7,
        section: 'Schedule B.3: Usage Overage Ceilings',
        bbox: [68.0, 310.0, 520.0, 415.0],
        excerpt: 'Customer may consume auxiliary ingestion capacity provided supplier does not bill exceeding standard contracted tiers without mutual email confirmation.',
      },
      {
        evidence_id: 'ev-3',
        kind: 'structured',
        title: 'Ramp Transaction Feed — Unmanaged Subscriptions',
        tool: 'get_card_transactions',
        server: 'mcp-1-procurement',
        source_id: 'ramp-card-sync',
        excerpt: '14 recurring charges identified matching software merchant category (Notion, Miro, Loom, Otter.ai). Total: $35,600.00.',
      },
    ],
    data_gaps: [
      {
        tool: 'get_aws_marketplace_spend',
        server: 'mcp-3-external',
        code: 'integration_unconfigured',
        message: 'AWS Marketplace direct billing connector is not configured. Cloud SaaS pass-through spend is omitted from this calculation (this is UNAVAILABLE DATA, not confirmed zero spend).',
        retryable: false,
      },
    ],
    proposed_actions: [
      {
        action_id: 'act-001',
        tool: 'create_review_task',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Create procurement review task: Dispute $12,500 Salesforce overbilling on INV-2024-8841',
        arguments: {
          vendor: 'Salesforce, Inc.',
          invoice_id: 'inv-8841',
          variance_amount: 12500,
          due_date: '2026-11-30',
        },
        idempotency_key: 'task-dispute-sf-8841',
        requires_confirmation: false,
        executed: false,
      },
      {
        action_id: 'act-002',
        tool: 'approve_invoice',
        server: 'mcp-3-external',
        risk_class: 'high_risk',
        description: 'Approve invoice INV-2024-8841 and accept $12,500 variance override',
        arguments: {
          invoice_id: 'inv-8841',
          override_reason: 'Accept rate bump per VP verbal approval',
          amount: 145000,
        },
        idempotency_key: 'act-approve-inv-8841',
        requires_confirmation: true,
        dry_run_by_default: true,
        executed: false,
        preview: {
          summary: 'Override 3-way match block and release $145,000 payment to Salesforce.',
          impact: 'Waives legal right to claw back $12,500 price variance under Section 4.2.',
          target_entity: 'Invoice INV-2024-8841',
          financial_impact: 145000,
          reversible: false,
          warnings: [
            'Irreversible payment authorization.',
            'Discrepancy of $12,500 exceeds 5% threshold.',
            'Contract MSA-SF-9921 locks rate at $132.50.',
          ],
        },
      },
    ],
    tool_calls: [
      {
        tool: 'query_spend_ledger',
        server: 'mcp-1-procurement',
        arguments: { period: 'Q3-Q4-2026' },
        success: true,
        latency_ms: 120,
      },
      {
        tool: 'detect_maverick_spend',
        server: 'mcp-1-procurement',
        arguments: { lookback_days: 90 },
        success: true,
        latency_ms: 310,
      },
      {
        tool: 'search_contracts',
        server: 'mcp-2-document',
        arguments: { query: 'price escalation and rate card' },
        success: true,
        latency_ms: 240,
      },
      {
        tool: 'reconcile_invoices',
        server: 'mcp-1-procurement',
        arguments: { status: 'flagged' },
        success: true,
        latency_ms: 180,
      },
    ],
  },

  // 2. Spend: How much did we spend on SaaS last quarter?
  'how much did we spend on saas last quarter?': {
    answer: `### SaaS Spend Breakdown — Q3 2026

During **Q3 2026 (July 1 – September 30)**, total verified SaaS expenditure across all sources was **$810,000**:

- **Centralized AP Invoices**: **$774,400** (95.6%) across 28 approved vendor contracts.
- **Corporate Card Transactions (Ramp)**: **$35,600** (4.4%) across 42 unmanaged or decentralized tool subscriptions.
- **Top 3 Categories**:
  1. *CRM & Revenue Operations*: $298,125 (36.8%)
  2. *Cloud Observability & Security*: $214,000 (26.4%)
  3. *Collaboration & Developer Tools*: $148,200 (18.3%)

*Audit Note: 100% of AP invoices have been reconciled against signed contract terms.*`,
    confidence: 0.98,
    processing_time_ms: 820,
    intent: 'spend_summary',
    sections: {
      facts: [
        'Total Q3 2026 spend was $810,000.00 across 28 managed vendors.',
        'AP Ledger recorded $774,400 across 48 processed invoices.',
        'Corporate card transactions contributed $35,600 in decentralized SaaS spend.',
      ],
      calculations: [
        'Average monthly SaaS run-rate: $270,000/month.',
        'Decentralized card spend represents 4.40% of total SaaS footprint.',
        'QoQ spend increased by 8.2% compared to Q2 ($748,500).',
      ],
      hypotheses: [
        'Decentralized card spend could be reduced by ~40% by migrating unmanaged tools to enterprise tier single sign-on.',
      ],
      needs_review: [
        '4 new software vendors appeared on corporate cards with recurring monthly frequency.',
      ],
    },
    citations: [
      {
        source_type: 'database',
        source_id: 'ap-ledger-q3',
        description: 'AP Ledger & General Ledger GL-5200 (Software & SaaS)',
        excerpt: 'Quarterly aggregation for 2026-Q3: Net payments settled $774,400.00.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-10',
        kind: 'structured',
        title: 'GL-5200 Q3 SaaS Ledger Aggregation',
        tool: 'get_vendor_spend',
        server: 'mcp-1-procurement',
        excerpt: 'Total spend $810,000 across 28 vendor entities. Zero unmapped transactions.',
      },
    ],
    data_gaps: [],
    proposed_actions: [
      {
        action_id: 'act-rep-q3',
        tool: 'generate_report',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Generate Executive Q3 SaaS Spend PDF Report',
        arguments: { quarter: 'Q3-2026', format: 'pdf' },
        idempotency_key: 'report-q3-spend',
        requires_confirmation: false,
        executed: false,
      },
    ],
  },

  // 3. Licenses: How many seats to commit at renewal?
  'how many seats should we commit to at renewal?': {
    answer: `### SaaS Seat Commitment Forecast & Recommendation

Based on **Okta 90-day login activity, historical employee churn rates, and growth projections**, here is the optimal renewal commitment:

| Metric | Salesforce | Datadog Hosts | Figma Enterprise |
| :--- | :--- | :--- | :--- |
| **Current Contracted Seats** | **1,000** | **250** | **180** |
| **Active 30-day Users** | **780** | **195** | **142** |
| **Inactive > 90 days** | **145** (14.5%) | **32** (12.8%) | **26** (14.4%) |
| **Projected Headcount Delta (Q1)** | **+35** | **+15** | **+8** |
| **Recommended Renewal Commitment** | **850 seats** | **215 hosts** | **150 seats** |
| **Estimated Annual Savings** | **$238,500** | **$33,600** | **$16,200** |

#### Key Recommendation:
Commit to **850 seats** for Salesforce (down from 1,000). Section 6.1 of the Salesforce MSA permits downsizing up to 15% at annual renewal without penalty.`,
    confidence: 0.92,
    processing_time_ms: 1100,
    intent: 'license_seat_forecast',
    sections: {
      facts: [
        'Currently paying for 1,000 Salesforce seats at $132.50/seat/month ($1,590,000/yr).',
        'Okta identity directory reports 780 active 30-day logins and 145 users with 0 logins in 90+ days.',
        'Salesforce renewal date is December 31, 2026 with a 30-day notice window.',
      ],
      calculations: [
        'Unused license waste: 145 seats * $132.50 * 12 = $230,550 annual idle cost.',
        'Downsizing to 850 committed seats yields net savings of $238,500/yr while retaining 70 buffer seats.',
        'Utilization rate across all seats: 78.0%.',
      ],
      hypotheses: [
        'Sales operations team reorganized in Q2, resulting in unassigned SDR seats that were never deprovisioned in Okta.',
      ],
      needs_review: [
        'Confirm with VP of Sales whether planned hiring for EMEA expansion will require more than 35 seats in Q1.',
      ],
    },
    citations: [
      {
        source_type: 'document',
        source_id: 'doc-sf-msa',
        description: 'Salesforce Enterprise MSA (MSA-SF-9921) — Section 6.1 Downsizing Provisions',
        excerpt: 'Section 6.1: Customer may adjust committed user count downward by up to 15% effective at each Contract Anniversary by providing written notice at least 30 days prior to renewal.',
      },
      {
        source_type: 'database',
        source_id: 'okta-telemetry',
        description: 'Okta Application Telemetry — 90-day Inactive User Audit',
        excerpt: '145 active accounts have last_login_timestamp > 90 days ago.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-sf-seat-doc',
        kind: 'document',
        title: 'Salesforce MSA Section 6.1 Downsizing (Page 6)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-sf-msa',
        page: 6,
        section: 'Section 6.1: Renewal Adjustment & Downsizing Thresholds',
        bbox: [72.0, 410.0, 520.0, 500.0],
        excerpt: 'Customer may adjust committed user count downward by up to 15% effective at each Contract Anniversary by providing written notice at least 30 days prior to renewal.',
      },
    ],
    data_gaps: [
      {
        tool: 'get_google_workspace_activity',
        server: 'mcp-3-external',
        code: 'permission_denied',
        message: 'Google Workspace app audit token lacks directory.read scope. Google accounts cannot be cross-referenced (UNAVAILABLE DATA, not 0 churn).',
        retryable: false,
      },
    ],
    proposed_actions: [
      {
        action_id: 'act-brief-sf',
        tool: 'prepare_negotiation_brief',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Prepare negotiation brief for Salesforce renewal targeting 850 seats',
        arguments: {
          vendor: 'Salesforce, Inc.',
          contract_id: 'cnt-sf-2025',
          target_seats: 850,
          projected_savings: 238500,
        },
        idempotency_key: 'brief-sf-renewal-850',
        requires_confirmation: false,
        executed: false,
      },
      {
        action_id: 'act-commit-seats',
        tool: 'commit_financial_spend',
        server: 'mcp-3-external',
        risk_class: 'high_risk',
        description: 'Formally commit renewal spend of $1,351,500 (850 seats) for Salesforce 2027',
        arguments: {
          vendor_id: 'ven-salesforce',
          committed_seats: 850,
          annual_spend: 1351500,
          currency: 'USD',
        },
        idempotency_key: 'commit-sf-850-seats',
        requires_confirmation: true,
        dry_run_by_default: true,
        executed: false,
        preview: {
          summary: 'Locks 850 committed seats for 12 months with Salesforce Inc.',
          impact: 'Reduces committed annual spend by $238,500. Exceeding 850 seats during term incurs list price ($160/seat/mo).',
          target_entity: 'Contract MSA-SF-9921',
          financial_impact: 1351500,
          reversible: false,
          warnings: [
            'Binding financial commitment of $1.35M.',
            'Cannot be reduced after execution until Dec 2027.',
          ],
        },
      },
    ],
  },

  // 4. Contracts: Termination notice period for Datadog
  'what is the termination notice period for datadog?': {
    answer: `### Datadog Contract Termination & Notice Terms

Under Enterprise Agreement **DD-ENT-2024-B**, the termination and renewal terms are structured as follows:

- **Notice Period**: **45 days** prior written notice required before the renewal date.
- **Contract Renewal Date**: **December 15, 2026**.
- **Notice Deadline**: **October 31, 2026** (🚨 **Active Window — 10 days remaining**).
- **Auto-Renewal Clause**: **Yes**, automatically renews for successive 12-month periods at list rates if notice is not given in writing to \`contracts@datadoghq.com\`.
- **Termination for Convenience**: Allowed at anniversary date only; early termination incurs 50% of remaining committed fees.`,
    confidence: 0.99,
    processing_time_ms: 710,
    intent: 'contract_notice_period',
    sections: {
      facts: [
        'Contract DD-ENT-2024-B Section 8.2 specifies 45 calendar days written notice.',
        'Renewal date is December 15, 2026.',
        'Notice deadline is October 31, 2026.',
        'Notice must be delivered via email to contracts@datadoghq.com with copy to legal@.',
      ],
      calculations: [
        'Days until contract renewal: 55 days.',
        'Days until non-renewal notice deadline: 10 days remaining.',
        'Annual contract value at risk of auto-renewal: $184,000.',
      ],
      hypotheses: [
        'Vendor account executive has not reached out for renewal discussions to let auto-renewal clause trigger.',
      ],
      needs_review: [
        'Legal / Procurement must issue formal intention notice prior to October 31 to protect negotiation leverage.',
      ],
    },
    citations: [
      {
        source_type: 'document',
        source_id: 'doc-datadog-ent',
        description: 'Datadog Enterprise Agreement (DD-ENT-2024-B) — Section 8.2 Term and Termination',
        excerpt: 'Section 8.2: Either party may terminate this Agreement at the end of the then-current Term by providing written notice to the other party at least forty-five (45) days prior to the expiration of such Term.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-dd-notice',
        kind: 'document',
        title: 'Datadog Master Agreement Section 8.2 (Page 5)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-datadog-ent',
        page: 5,
        section: 'Section 8.2: Renewal and Notice Requirements',
        bbox: [72.0, 240.0, 520.0, 360.0],
        excerpt: 'Either party may terminate this Agreement at the end of the then-current Term by providing written notice to the other party at least forty-five (45) days prior to the expiration of such Term.',
      },
    ],
    data_gaps: [],
    proposed_actions: [
      {
        action_id: 'act-dd-reminder',
        tool: 'create_renewal_reminder',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Set renewal deadline reminder for Datadog on October 25, 2026',
        arguments: {
          vendor: 'Datadog, Inc.',
          deadline_date: '2026-10-31',
          reminder_date: '2026-10-25',
          assigned_to: 'Procurement Lead',
        },
        idempotency_key: 'remind-dd-notice-45d',
        requires_confirmation: false,
        executed: false,
      },
      {
        action_id: 'act-dd-cancel',
        tool: 'cancel_contract',
        server: 'mcp-3-external',
        risk_class: 'high_risk',
        description: 'Issue official Non-Renewal Notice letter to Datadog, Inc. terminating DD-ENT-2024-B',
        arguments: {
          vendor_id: 'ven-datadog',
          contract_number: 'DD-ENT-2024-B',
          recipient_email: 'contracts@datadoghq.com',
          effective_date: '2026-12-15',
        },
        idempotency_key: 'cancel-datadog-notice',
        requires_confirmation: true,
        dry_run_by_default: true,
        executed: false,
        preview: {
          summary: 'Sends formal notice of non-renewal to Datadog contracts desk.',
          impact: 'Terminates services on Dec 15, 2026. Service will shut down unless a new order is executed.',
          target_entity: 'Datadog Agreement DD-ENT-2024-B',
          financial_impact: 184000,
          reversible: false,
          warnings: [
            'Irreversible contractual notification.',
            'Requires immediate replacement monitoring tooling if not renewed.',
          ],
        },
      },
    ],
  },

  // 5. Invoices: Which invoices have reconciliation exceptions?
  'which invoices have reconciliation exceptions?': {
    answer: `### AP Audit & Invoices with Reconciliation Exceptions

Our deterministic 3-way match engine identified **3 high-severity exception invoices** totaling **$34,250 in disputed variance**:

1. **Salesforce, Inc.** — Invoice \`INV-2024-8841\`
   - **Discrepancy**: **+$12,500.00 (+9.4%)**
   - **Rule Flag**: \`PRICE_CREEP\` — Billed at $145.00/user/mo vs contracted $132.50.
   - **Status**: 🔴 Open / Payment Blocked.

2. **Datadog, Inc.** — Invoice \`INV-4419-DATADOG\`
   - **Discrepancy**: **+$14,200.00 (+26.2%)**
   - **Rule Flag**: \`QUANTITY_TIER_MISMATCH\` — 250 host tier exceeded with uncontracted on-demand surge charges.
   - **Status**: 🔴 Open / Under Investigation.

3. **Adobe Systems** — Invoice \`INV-2026-9021\`
   - **Discrepancy**: **+$7,550.00 (+14.8%)**
   - **Rule Flag**: \`UNCONTRACTED_SKU\` — Billed 15 seats of "Creative Cloud Generative Credits" not present in MSA Schedule A.
   - **Status**: 🟡 Review Pending.

*Confirmed Zero Notice: 142 other invoices this quarter had 0 discrepancies and passed 3-way matching.*`,
    confidence: 0.97,
    processing_time_ms: 880,
    intent: 'invoice_reconciliation_audit',
    sections: {
      facts: [
        '3 invoices are currently blocked in AP exceptions ledger.',
        'Total disputed variance is $34,250.00 out of $1,428,500 invoiced.',
        '142 invoices passed reconciliation with 0 discrepancies (Clean Rate: 88.8%).',
      ],
      calculations: [
        'Total invoice exception value: $34,250.00.',
        'Recoverable savings rate: 2.4% of total quarterly AP volume.',
        'Average discrepancy resolution time: 4.2 business days.',
      ],
      hypotheses: [
        'Adobe SKU addition may have been initiated via self-service team admin portal without procurement approval.',
      ],
      needs_review: [
        'Dispute letters must be transmitted for INV-2024-8841 and INV-4419 prior to Net-30 payment due dates.',
      ],
    },
    citations: [
      {
        source_type: 'database',
        source_id: 'ap-exceptions',
        description: 'AP Reconciliation Audit Store — Active Discrepancy Ledger',
        excerpt: '3 active discrepancies detected: INV-8841, INV-4419, INV-9021. Total variance $34,250.00.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-inv-list',
        kind: 'structured',
        title: 'Reconciliation Audit Records',
        tool: 'investigate_reconciliation_exception',
        server: 'mcp-1-procurement',
        excerpt: '3 invoices flagged for rule violations. Clean rate 88.8%.',
      },
    ],
    data_gaps: [],
    proposed_actions: [
      {
        action_id: 'act-disp-all',
        tool: 'create_procurement_task',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Create AP batch dispute task for $34,250 total variance across 3 vendors',
        arguments: { count: 3, total_variance: 34250 },
        idempotency_key: 'task-ap-disputes-batch',
        requires_confirmation: false,
        executed: false,
      },
    ],
  },

  // 6. Vendor 360: Adobe
  'give me a complete overview of adobe.': {
    answer: `### Vendor 360 Overview: Adobe Systems

| Domain | Status & Verified Metrics |
| :--- | :--- |
| **Annual Spend** | **$186,000 / year** (Net-30 terms) |
| **Active Contracts** | Enterprise Term License Agreement (\`ETLA-ADB-2024\`) |
| **Term Duration** | May 1, 2024 – April 30, 2027 (18 months remaining) |
| **License Utilization** | **110 / 150 Creative Cloud All Apps** assigned (73.3% utilization) |
| **Inactive Seats** | **28 seats idle > 60 days** ($34,720 annual waste) |
| **Recent Invoices** | \`INV-2026-9021\` ($58,550) — Flagged with $7,550 uncontracted SKU variance |
| **Maverick Spend** | $4,800 on card transactions for standalone Acrobat Pro licenses |

#### Procurement Investigation Summary:
Procurement should reclaim the **28 unused Creative Cloud seats** and reassign them to the employees currently paying for standalone Acrobat Pro subscriptions on corporate cards, yielding **$39,520 in combined savings**.`,
    confidence: 0.95,
    processing_time_ms: 1250,
    intent: 'vendor_360_overview',
    sections: {
      facts: [
        'Contract ETLA-ADB-2024 is active through April 30, 2027.',
        '150 Creative Cloud All Apps seats are contracted at $103.33/seat/mo.',
        'Okta reports 28 accounts have had 0 active logins across all Adobe Creative Cloud apps in > 60 days.',
        'Invoice INV-2026-9021 contains an uncontracted $7,550 line item.',
      ],
      calculations: [
        'Idle seat cost: 28 * $103.33 * 12 = $34,718.88/year.',
        'Standalone card spend on Acrobat: $4,800.00/year across 8 cards.',
        'Total addressable consolidation savings: $39,518.88/year.',
      ],
      hypotheses: [
        'Departments purchasing standalone Acrobat were unaware our enterprise ETLA already includes Acrobat Pro entitlement.',
      ],
      needs_review: [
        'Notify internal IT to deprovision 28 idle seats and reallocate them to Acrobat cardholders.',
      ],
    },
    citations: [
      {
        source_type: 'document',
        source_id: 'doc-adobe-etla',
        description: 'Adobe Enterprise Agreement (ETLA-ADB-2024) — Schedule A License Commitments',
        excerpt: 'Schedule A: 150 Enterprise Named User Licenses for Creative Cloud All Apps. Includes Acrobat Pro DC, Photoshop, Illustrator, Premiere Pro.',
      },
    ],
    evidence: [
      {
        evidence_id: 'ev-adb-1',
        kind: 'document',
        title: 'Adobe ETLA Agreement Schedule A (Page 2)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-adobe-etla',
        page: 2,
        section: 'Schedule A: Included Enterprise Applications',
        bbox: [72.0, 180.0, 520.0, 310.0],
        excerpt: 'Named User Licenses for Creative Cloud All Apps includes Acrobat Pro DC enterprise edition with cloud document services.',
      },
    ],
    data_gaps: [],
    proposed_actions: [
      {
        action_id: 'act-adb-review',
        tool: 'create_review_task',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: 'Initiate Adobe seat reallocation workflow for 28 idle users',
        arguments: { vendor: 'Adobe', idle_seats: 28 },
        idempotency_key: 'task-adb-reallocate-28',
        requires_confirmation: false,
        executed: false,
      },
      {
        action_id: 'act-adb-remove',
        tool: 'remove_licenses',
        server: 'mcp-3-external',
        risk_class: 'high_risk',
        description: 'Deprovision and de-license 28 idle Adobe users from Okta directory',
        arguments: {
          vendor_id: 'ven-adobe',
          seat_count: 28,
          target_app: 'Adobe Creative Cloud',
        },
        idempotency_key: 'deprovision-adobe-28-users',
        requires_confirmation: true,
        dry_run_by_default: true,
        executed: false,
        preview: {
          summary: 'Revokes Adobe Creative Cloud licenses for 28 employee Okta accounts.',
          impact: 'Users lose access to Adobe apps upon next SSO refresh. Frees up 28 license pools.',
          target_entity: 'Okta Application: Adobe Creative Cloud',
          financial_impact: 34720,
          reversible: true,
          warnings: [
            'Immediate user session termination.',
            'Impacts users in Marketing and Design groups.',
          ],
        },
      },
    ],
  },
};

/**
 * Get or synthesize a realistic response for any question.
 */
export function getMockAnswer(question: string, vendorId?: string): AskAIResponse {
  const normalized = question.trim().toLowerCase();

  for (const [key, val] of Object.entries(MOCK_RESPONSES)) {
    if (normalized.includes(key) || key.includes(normalized)) {
      return {
        answer: val.answer ?? 'Answer not available.',
        conversation_id: crypto.randomUUID(),
        citations: val.citations ?? [],
        confidence: val.confidence ?? 0.9,
        processing_time_ms: val.processing_time_ms ?? 950,
        evidence: val.evidence ?? [],
        proposed_actions: val.proposed_actions ?? [],
        data_gaps: val.data_gaps ?? [],
        sections: val.sections ?? { facts: [], calculations: [], hypotheses: [], needs_review: [] },
        tool_calls: val.tool_calls ?? [],
        intent: val.intent ?? 'general_procurement_query',
        plan_source: val.plan_source ?? 'mcp-1,mcp-2',
        generated_at: new Date().toISOString(),
      };
    }
  }

  // Fallback realistic synthesis based on prompt category
  const vendorName = vendorId ? vendorId.replace(/^ven-/, '').toUpperCase() : 'our SaaS suppliers';
  return {
    answer: `### Analysis for: "${question}"

Synthesizing verified records for **${vendorName}** across procurement contracts, transaction ledgers, and live telemetry:

- **Commercial Record**: All active contracts have been reconciled with latest signed amendments.
- **Spend & Invoicing**: Current billing matches contracted rate cards with no unreviewed exceptions outstanding.
- **License Health**: Telemetry indicates stable utilization across active business units.`,
    conversation_id: crypto.randomUUID(),
    citations: [
      {
        source_type: 'document',
        source_id: 'doc-sf-msa',
        description: 'Procurement Master Service Agreement — Commercial Schedule',
        excerpt: 'Standard terms governed by master agreement rate schedule and annual review cycles.',
      },
    ],
    confidence: 0.88,
    processing_time_ms: 840,
    evidence: [
      {
        evidence_id: 'ev-fallback-1',
        kind: 'document',
        title: 'Master Service Agreement (Page 1)',
        tool: 'search_contracts',
        server: 'mcp-2-document',
        document_id: 'doc-sf-msa',
        page: 1,
        section: 'General Provisions',
        bbox: [72.0, 100.0, 520.0, 200.0],
        excerpt: 'Agreement entered into between Customer and Supplier subject to terms set forth herein.',
      },
    ],
    sections: {
      facts: [
        `Grounded in indexed agreements for ${vendorName}.`,
        'All line items verified against current active version in procurement ledger.',
      ],
      calculations: [
        'Zero unreconciled pricing variances detected.',
      ],
      hypotheses: [
        'Future renewals may benefit from multi-year commitment discounting.',
      ],
      needs_review: [
        'Confirm upcoming budget allocation prior to next fiscal cycle.',
      ],
    },
    data_gaps: [
      {
        tool: 'external_benchmark_pricing',
        server: 'mcp-3-external',
        code: 'unavailable',
        message: 'External peer price benchmark database is not connected. Market percentile is UNAVAILABLE (distinct from confirmed zero).',
        retryable: false,
      },
    ],
    proposed_actions: [
      {
        action_id: `act-${Date.now()}`,
        tool: 'create_review_task',
        server: 'mcp-3-external',
        risk_class: 'low_risk',
        description: `Schedule quarterly procurement review for ${vendorName}`,
        arguments: { vendor: vendorName },
        idempotency_key: `review-${Date.now()}`,
        requires_confirmation: false,
        executed: false,
      },
    ],
    tool_calls: [
      {
        tool: 'search_contracts',
        server: 'mcp-2-document',
        arguments: { query: question },
        success: true,
        latency_ms: 190,
      },
      {
        tool: 'calculate_spend',
        server: 'mcp-1-procurement',
        arguments: { vendor_id: vendorId },
        success: true,
        latency_ms: 140,
      },
    ],
    intent: 'general_inquiry',
    generated_at: new Date().toISOString(),
  };
}

/**
 * Perform a mock dry-run preview for high-risk actions.
 */
export function getMockActionPreview(toolName: string, arguments_: Record<string, any>): ActionPreviewResponse {
  let summary = `Execute ${toolName} with supplied parameters`;
  let impact = 'Modifies system state or sends external communications.';
  let financialImpact: number | null = null;
  const warnings: string[] = ['This operation requires explicit human authorization.'];

  if (toolName === 'approve_invoice') {
    summary = `Override 3-way match exceptions and release payment for Invoice ${arguments_.invoice_id ?? 'INV-UNKNOWN'}`;
    impact = 'Authorizes disbursement of funds. Waives contractual price creep dispute rights.';
    financialImpact = arguments_.amount ?? 145000;
    warnings.push('Discrepancy exceeds standard 5% variance threshold.', 'Payment cannot be clawed back automatically.');
  } else if (toolName === 'cancel_contract') {
    summary = `Issue formal contract termination notice for ${arguments_.contract_number ?? 'Contract'}`;
    impact = 'Terminates vendor relationship on effective date. Cancels all associated software licenses.';
    financialImpact = arguments_.annual_spend ?? 184000;
    warnings.push('Irreversible written notice to vendor legal department.', 'Requires replacement solution before cutover date.');
  } else if (toolName === 'remove_licenses') {
    summary = `Deprovision and de-license ${arguments_.seat_count ?? 28} users from ${arguments_.target_app ?? 'SaaS Application'}`;
    impact = 'Users will lose application access on next SSO session refresh.';
    financialImpact = 34720;
    warnings.push('May interrupt active workflows for employees.');
  } else if (toolName === 'commit_financial_spend') {
    summary = `Commit binding financial spend of $${Number(arguments_.annual_spend ?? 1351500).toLocaleString()} for ${arguments_.committed_seats ?? 850} seats`;
    impact = 'Executes annual commercial order with supplier under fixed terms.';
    financialImpact = arguments_.annual_spend ?? 1351500;
    warnings.push('Legally binding enterprise order.', 'Early reduction incurs 100% liquidated damages.');
  }

  return {
    tool: toolName,
    server: 'mcp-3-external',
    risk_class: 'high_risk',
    requires_confirmation: true,
    arguments: arguments_,
    preview: {
      summary,
      impact,
      target_entity: String(arguments_.invoice_id || arguments_.contract_number || arguments_.vendor_id || toolName),
      financial_impact: financialImpact,
      reversible: toolName === 'remove_licenses',
      parameters_diff: {
        status: { before: 'PENDING_CONFIRMATION', after: 'CONFIRMED_EXECUTED' },
        audit_state: { before: 'UNVERIFIED', after: 'HUMAN_AUTHORIZED' },
      },
      warnings,
    },
  };
}

/**
 * Perform a mock confirmation of a high-risk action.
 */
export function getMockActionConfirm(toolName: string, arguments_: Record<string, any>, note?: string): ActionConfirmResponse {
  return {
    tool: toolName,
    server: 'mcp-3-external',
    risk_class: 'high_risk',
    success: true,
    result: {
      status: 'EXECUTED',
      execution_timestamp: new Date().toISOString(),
      confirmation_note: note || 'Authorized via Ask AI human confirmation modal.',
      audit_record_id: `aud-${crypto.randomUUID().slice(0, 8)}`,
      parameters: arguments_,
    },
    expires_at: null,
    conversation_id: crypto.randomUUID(),
  };
}

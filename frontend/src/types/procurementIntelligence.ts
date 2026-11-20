// ---------------------------------------------------------------------------
// Procurement Intelligence & Negotiation Types
// ---------------------------------------------------------------------------

// Urgency countdown badge for renewal timelines
export type RenewalBadgeUrgency = '30d' | '60d' | '90d' | '120d' | 'future';

// 1. AP Audit & Continuous Pre-Payment Reconciliation
export interface APAuditKPIs {
  unbilled_exposure_total: number;
  open_exceptions_count: number;
  duplicate_billing_detected_total: number;
  rate_variance_detected_total: number;
  pending_audit_reviews_count: number;
}

export type ExceptionType =
  | 'RATE_VARIANCE'
  | 'DUPLICATE_INVOICE'
  | 'MISSING_CONTRACT'
  | 'UNAUTHORIZED_SPEND'
  | 'QUANTITY_MISMATCH'
  | 'PAYMENT_TERMS_DISCREPANCY';

export type ExceptionSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface ReconciliationItem {
  id: string;
  invoice_id: string;
  invoice_number: string;
  vendor_id: string;
  vendor_name: string;
  contract_id?: string | null;
  contract_number?: string | null;
  exception_type: ExceptionType;
  severity: ExceptionSeverity;
  amount_in_dispute: number;
  confidence_score: number;
  flagged_at: string;
  status: 'OPEN' | 'INVESTIGATING' | 'RESOLVED' | 'DISMISSED';
  evidence_excerpt?: string | null;
  rule_id: string;
  assigned_to?: string | null;
}

// 2. Off-Contract & Maverick Spend Intelligence
export interface MaverickSpendKPIs {
  maverick_spend_total: number;
  maverick_transaction_count: number;
  active_card_purchases_count: number;
  shadow_it_vendors_count: number;
}

export interface MaverickAlertItem {
  id: string;
  card_transaction_id: string;
  vendor_id?: string | null;
  merchant_name: string;
  category: string;
  amount: number;
  transaction_date: string;
  cardholder_name: string;
  department: string;
  is_shadow_it: boolean;
  has_contract: boolean;
  risk_score: number;
  potential_savings_amount: number;
  status: 'FLAGGED' | 'RESOLVED' | 'APPROVED';
}

// 3. SaaS Utilization & Predictive Seat Forecasting
export interface SaaSSeatForecast {
  month: string;
  actual_active_seats: number | null;
  predicted_active_seats: number;
  lower_bound: number;
  upper_bound: number;
  allocated_seats: number;
  contracted_min_commitment: number;
}

export interface SaaSUtilizationItem {
  vendor_id: string;
  vendor_name: string;
  app_name: string;
  icon_url?: string;
  purchased_seats: number;
  active_seats_30d: number;
  inactive_seats_30d: number;
  inactive_seats_60d: number;
  inactive_seats_90d: number;
  utilizationRatePct: number;
  seat_cost_monthly: number;
  annual_waste_spend: number;
  license_tier: string;
  forecast: SaaSSeatForecast[];
  recommended_downsize_seats: number;
  recommended_renewal_seats: number;
}

// 4. Commercial Renewal Intelligence & Negotiation Agent
export interface UpcomingRenewal {
  id: string;
  contractId: string;
  contractNumber: string;
  vendorId: string;
  vendorName: string;
  productName: string;
  annualSpend: number;
  spendYoYPct: number;
  renewalDate: string;
  daysUntilRenewal: number;
  badge: RenewalBadgeUrgency;
  autoRenew: boolean;
  noticePeriodDays: number;
  noticeDeadlineDate: string;
  daysUntilNoticeDeadline: number;
  isNoticeWindowActive: boolean;
  utilizationPct?: number;
  assignedOwner: string;
  status: 'unreviewed' | 'investigating' | 'agent_preparing' | 'negotiation_ready' | 'renewed';
  keyLeveragePoints: string[];
}

export interface RawUpcomingRenewalResponse {
  id: string;
  contract_id: string;
  contract_number: string;
  vendor_id: string;
  vendor_name: string;
  product_name: string;
  annual_spend: number;
  spend_yoy_pct: number;
  renewal_date: string;
  days_until_renewal: number;
  badge: RenewalBadgeUrgency;
  auto_renew: boolean;
  notice_period_days: number;
  notice_deadline_date: string;
  days_until_notice_deadline: number;
  is_notice_window_active: boolean;
  utilization_pct: number;
  assigned_owner: string;
  status: 'unreviewed' | 'investigating' | 'agent_preparing' | 'negotiation_ready' | 'renewed';
  key_leverage_points: string[];
}

export interface ClauseCitation {
  clause_type: string;
  summary: string;
  document_id?: string | null;
  filename?: string | null;
  page?: number | null;
  section?: string | null;
  verbatim_excerpt?: string | null;
}

export interface NegotiationBriefResponse {
  vendor_id: string;
  vendor_name: string;
  current_spend: number;
  contract_terms: Record<string, unknown>;
  utilization_data: Record<string, unknown>;
  leverage_points: string[];
  recommended_actions: string[];
  talking_points: string[];
  risk_factors: string[];
  contractual_clauses: ClauseCitation[];
  executive_summary?: string;
  clause_citations?: ClauseCitation[];
  generated_at: string;
}

export interface RenewalReminderRequest {
  contract_id: string;
  vendor_id: string;
  remind_days_before_notice?: number;
  notes?: string;
}

export interface RenewalReminderResponse {
  reminder_id: string;
  contract_id: string;
  vendor_name: string;
  notice_deadline_date: string;
  remind_date: string;
  days_until_notice: number;
  status: string;
  message: string;
}

export interface RenewalReminderItem {
  id: string;
  contract_id: string;
  contract_number: string;
  vendor_name: string;
  remind_date: string;
  notice_deadline_date: string;
  days_until_notice: number;
  status: string;
  urgency: string;
}

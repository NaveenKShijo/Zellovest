/**
 * Procurement Intelligence & Optimization TypeScript Data Contracts
 * 
 * Supports:
 * 1. AP Audit & Reconciliation (Deterministic rule engine exceptions)
 * 2. Maverick Spend & Semantic Overlap (Jev-powered decision engine)
 * 3. SaaS Utilization & Predictive Seat Forecasting (ML churn survival models)
 * 4. Commercial Renewal Intelligence & Countdown Timelines
 */

// ==========================================
// 1. AP Audit & Reconciliation Types
// ==========================================

export type ExceptionRuleType =
  | 'price'
  | 'quantity'
  | 'discount'
  | 'tax'
  | 'freight'
  | 'date'
  | 'missing_po'
  | 'payment_term';

export type AuditSeverity = 'high' | 'medium' | 'low';

export type AuditExceptionStatus = 'open' | 'acknowledged' | 'resolved' | 'dismissed';

export interface LineItemComparison {
  id: string;
  lineNumber: number;
  productCode: string;
  description: string;
  billedUnitPrice: number;
  contractedUnitPrice: number;
  billedQuantity: number;
  tierMinQuantity?: number | null;
  tierMaxQuantity?: number | null;
  varianceAmount: number;
  extendedVarianceAmount?: number;
  variancePct: number;
  rule: ExceptionRuleType;
  explanation: string;
}

export interface ReconciliationItem {
  id: string;
  invoiceId: string;
  invoiceNumber: string;
  vendorId: string;
  vendorName: string;
  invoiceDate: string;
  dueDate: string;
  totalAmount: number;
  currency: string;
  discrepancyAmount: number;
  primaryRule: ExceptionRuleType;
  ruleLabel: string;
  severity: AuditSeverity;
  status: AuditExceptionStatus;
  contractId: string;
  contractNumber: string;
  contractTitle: string;
  poNumber?: string | null;
  poId?: string | null;
  detectedAt: string;
  resolvedAt?: string | null;
  investigationReason: string;
  lineItemsComparison: LineItemComparison[];
}

export interface APAuditKPIs {
  totalInvoicedAmount: number;
  flaggedDiscrepancyAmount: number;
  totalInvoicesCount: number;
  cleanInvoicesCount: number;
  exceptionInvoicesCount: number;
  unreconciledInvoicesCount: number;
  cleanRatePct: number;
}

// ==========================================
// 2. Maverick Spend & Software Overlap Types (Jev-powered)
// ==========================================

export interface JevDecisionScores {
  isSaasScore: number; // e.g. 0.96 calibrated probability
  warrantsReviewScore: number; // e.g. 0.91 calibrated probability
}

export interface SoftwareOverlap {
  unmanagedTool: string;
  unmanagedCategory: string;
  approvedAlternative: string;
  approvedContractId: string;
  approvedVendorName: string;
  cosineSimilarity: number; // e.g. 0.91
  sharedCapabilities: string[];
  recommendedAction: string;
  employeeEmail: string;
  employeeName: string;
  annualizedSavingsOpportunity: number;
}

export interface MaverickAlertItem {
  id: string;
  transactionId: string;
  merchantName: string;
  amount: number;
  currency: string;
  cadenceDays: number; // ~30d
  cadenceDescription: string;
  cardLast4: string;
  employeeId: string;
  employeeName: string;
  employeeEmail: string;
  department: string;
  transactionDate: string;
  jevScores: JevDecisionScores;
  status: 'open' | 'notified' | 'migrated' | 'dismissed';
  overlap: SoftwareOverlap;
}

export interface MaverickSpendKPIs {
  totalUnmanagedSpend: number;
  activeAlertsCount: number;
  potentialAnnualSavings: number;
  avgOverlapSimilarity: number;
}

// ==========================================
// 3. SaaS Utilization & Predictive Seat Forecasting
// ==========================================

export interface DepartmentSeatRetention {
  department: string;
  currentSeats: number;
  recommendedSeats: number;
  retentionProbability: number;
  historicalChurnRate: number;
  projectedDecayCurve: Array<{
    day: number;
    retentionRate: number;
    projectedSeats: number;
  }>;
}

export interface SeatForecastScenario {
  label: string;
  seats: number;
  confidenceInterval: string;
  shelfwareSavings: number;
  trueupRisk: number;
}

export interface SeatForecastData {
  vendorId: string;
  vendorName: string;
  productName: string;
  currentCommitmentSeats: number;
  recommendedCommitmentSeats: number;
  overallConfidence: number; // e.g. 0.95 (95% CI)
  shelfwareAnnualWaste: number;
  trueupRiskAmount: number;
  netAnnualSavingsEstimate: number;
  contractUnitCost: number;
  renewalDate: string;
  scenarios: {
    conservative: SeatForecastScenario; // higher seats, zero true-up risk
    recommended: SeatForecastScenario; // optimal balance
    aggressive: SeatForecastScenario; // maximum shelfware cuts
  };
  departmentCurves: DepartmentSeatRetention[];
}

export interface SaaSUtilizationItem {
  id: string;
  vendorId: string;
  vendorName: string;
  appCode: string;
  purchasedSeats: number;
  activeLogins: number;
  utilizationRatePct: number;
  contractedUnitCost: number;
  annualSpend: number;
  inactive30dSeats: number;
  inactive60dSeats: number;
  inactive90dSeats: number;
  recoverableSpendAnnual: number;
  forecast: SeatForecastData;
}

// ==========================================
// 4. Renewal Timeline & Negotiation Agent Types
// ==========================================

export type RenewalBadgeUrgency = '30d' | '60d' | '90d' | '120d' | 'future';

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
  utilizationPct: number;
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
  vendor_id: string;
  vendor_name: string;
  notice_deadline_date: string;
  remind_date: string;
  days_until_notice: number;
  status: string;
  notes?: string | null;
  created_at: string;
}

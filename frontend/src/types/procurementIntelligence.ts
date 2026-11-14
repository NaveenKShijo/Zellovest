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
// 4. Renewal Timeline Types (prep for Renewal Agent)
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
  spendYoYPct: number; // e.g. +14.2% or -5.1%
  renewalDate: string;
  daysUntilRenewal: number;
  badge: RenewalBadgeUrgency;
  autoRenew: boolean;
  noticePeriodDays: number;
  noticeDeadlineDate: string;
  daysUntilNoticeDeadline: number;
  isNoticeWindowActive: boolean; // within notice period countdown
  utilizationPct: number;
  assignedOwner: string;
  status: 'unreviewed' | 'investigating' | 'agent_preparing' | 'negotiation_ready' | 'renewed';
  keyLeveragePoints: string[];
}

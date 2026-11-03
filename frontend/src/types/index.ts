/**
 * TypeScript Data Contracts for Zellovest Frontend
 *
 * Think of this file like Pydantic models in FastAPI:
 * It enforces static schema validation across UI components,
 * API requests, and global application state.
 */

// ==========================================
// 1. Navigation & Route Types
// ==========================================

export interface NavItem {
  id: string;
  label: string;
  href: string;
  iconName: string; // Identifier for SVG icon rendering
  badge?: string | number; // e.g., "3 New" or 12 pending invoices
  badgeVariant?: 'default' | 'warning' | 'danger' | 'info';
  description?: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

// Breadcrumb node for the navigation trail
export interface BreadcrumbItem {
  label: string;
  href?: string;
  isCurrent?: boolean;
}

// ==========================================
// 2. Authentication & User Session Types
// ==========================================

/**
 * Single-Tenant Enterprise Roles defined in the Zellovest PRD:
 * - VP of Procurement / Head of Procurement
 * - Procurement Manager
 * - AP / Accounts Payable Auditor
 * - Finance Stakeholder
 * - IT & SaaS Administrator
 */
export type UserRole = 'Procurement Team Member' | 'procurement_member';

export interface UserSession {
  id: string; // user id (users.id)
  name: string;
  email: string;
  role: UserRole;
  department: string;
  avatarUrl?: string;
  organizationName: string; // Single-tenant organization boundary
  accessToken?: string; // Custom JWT from POST /api/v1/auth/login|demo
  refreshToken?: string; // Long-lived refresh JWT for rotating access tokens
  expiresAt?: number; // Access token expiry (epoch ms)
  isDemo?: boolean; // sandbox session: explores, cannot invite
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  tenant_id: string;
  is_demo?: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  /** Rotating refresh JWT; absent for legacy responses. */
  refresh_token?: string | null;
  user: AuthUser;
}

export interface InviteResponse {
  email: string;
  invite_token: string;
  expires_at: string;
}

export interface InviteStatus {
  email: string;
  expires_at: string;
}

/**
 * Authentication state driven by the custom email/password backend
 * (POST /api/v1/auth/login|/me — HS256 JWT, PBKDF2 passwords).
 * Invite-only onboarding: accounts are created by the seed script or by
 * claiming an invite link — there is no public signup.
 * - login(email, password): verify credentials, persist JWT session.
 * - loginDemo(): one-click sandbox entry (no credentials), persist session.
 * - acceptInvite(token, name, password): claim an invite, persist session.
 * - logout(): clears the local session (stateless JWT, nothing to revoke).
 */
export interface AuthContextType {
  user: UserSession | null;
  isAuthenticated: boolean;
  isLoading: boolean; // session restore in progress (on app mount)
  isLoggingIn: boolean; // login/demo/invite-accept in progress
  error: string | null; // last authentication error, if any
  login: (email: string, password: string) => Promise<boolean>;
  loginDemo: () => Promise<boolean>;
  acceptInvite: (token: string, name: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  clearError: () => void;
  /** Resolve a valid access token, silently refreshing if near expiry. */
  getValidAccessToken: () => Promise<string | null>;
}

// ==========================================
// 3. Layout State Types
// ==========================================

export interface LayoutContextType {
  isSidebarCollapsed: boolean;
  isMobileSidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleMobileSidebar: () => void;
  closeMobileSidebar: () => void;
}

// ==========================================
// 4. Notifications & Alert Types
// ==========================================

export type NotificationType = 'success' | 'error' | 'warning' | 'info';

export interface ToastNotification {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  durationMs?: number; // Auto-dismiss time (default 4500ms)
  action?: {
    label: string;
    onClick: () => void;
  };
}

export interface SystemAlert {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  dismissible?: boolean;
  timestamp: string;
  action?: {
    label: string;
    href: string;
  };
}

export interface ToastContextType {
  toasts: ToastNotification[];
  alerts: SystemAlert[];
  notify: {
    success: (title: string, message?: string, action?: ToastNotification['action']) => string;
    error: (title: string, message?: string, action?: ToastNotification['action']) => string;
    warning: (title: string, message?: string, action?: ToastNotification['action']) => string;
    info: (title: string, message?: string, action?: ToastNotification['action']) => string;
  };
  removeToast: (id: string) => void;
  addAlert: (alert: Omit<SystemAlert, 'id' | 'timestamp'>) => string;
  dismissAlert: (id: string) => void;
}

// ==========================================
// 5. Vendor Management Types
// ==========================================

export type VendorStatus = 'compliant' | 'variance_flagged' | 'up_for_renewal' | 'maverick_detected' | 'inactive';
export type VendorCategory = 'CRM & Sales' | 'Design & Prototyping' | 'Cloud Infrastructure' | 'Productivity & Messaging' | 'Development Tools' | 'HR & Finance' | 'Marketing & Analytics' | 'Security & Compliance' | 'Other';

export interface Vendor {
  id: string;
  canonicalName: string;
  domain?: string;
  primaryContact?: {
    name: string;
    email: string;
    phone?: string;
  };
  paymentTerms: 'net_30' | 'net_45' | 'net_60' | 'custom';
  customPaymentTerms?: string;
  categories: VendorCategory[];
  annualSpend: number;
  currency: string;
  status: VendorStatus;
  contractCount: number;
  invoiceCount: number;
  transactionCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface VendorListParams {
  page?: number;
  pageSize?: number;
  search?: string;
  categories?: VendorCategory[];
  statuses?: VendorStatus[];
  minSpend?: number;
  maxSpend?: number;
  sortBy?: 'canonicalName' | 'annualSpend' | 'createdAt' | 'updatedAt';
  sortOrder?: 'asc' | 'desc';
}

export interface VendorListResponse {
  vendors: Vendor[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

// Contract versioning per PRD #11
export interface Contract {
  id: string;
  vendorId: string;
  product: string;
  unitPrice: number;
  currency: string;
  unitOfMeasurement: 'per_user' | 'per_seat' | 'per_month' | 'per_year' | 'usage_based' | 'flat';
  quantity?: number;
  effectiveFrom: string;
  effectiveTo?: string;
  version: number;
  amendmentOfId?: string;
  status: 'active' | 'expired' | 'superseded' | 'draft';
  paymentTerms?: string;
  priceEscalation?: number;
  renewalDate?: string;
  autoRenewal?: boolean;
  noticePeriodDays?: number;
  pdfUrl?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Invoice {
  id: string;
  vendorId: string;
  contractId?: string;
  invoiceNumber: string;
  amount: number;
  currency: string;
  status: 'pending' | 'approved' | 'paid' | 'rejected' | 'flagged';
  variance?: number;
  varianceReason?: string;
  invoiceDate: string;
  dueDate: string;
  paidDate?: string;
  pdfUrl?: string;
  lineItems?: InvoiceLineItem[];
  createdAt: string;
  updatedAt: string;
}

export interface InvoiceLineItem {
  id: string;
  description: string;
  quantity: number;
  unitPrice: number;
  total: number;
}

export interface CardTransaction {
  id: string;
  vendorId?: string;
  merchantName: string;
  amount: number;
  currency: string;
  transactionDate: string;
  cardLast4: string;
  employeeName?: string;
  department?: string;
  category: 'saas_subscription' | 'travel' | 'meals' | 'office_expenses' | 'other';
  isRecurring: boolean;
  recurrenceInterval?: number;
  confidenceScore?: number;
  matchedVendorId?: string;
  createdAt: string;
}

// Document Upload Types
export type DocumentType = 'contract' | 'invoice' | 'purchase_order' | 'amendment' | 'vendor_policy' | 'other';
export type UploadStatus = 'queued' | 'uploading' | 'processing' | 'completed' | 'error';

// ==========================================
// 5b. Document Explorer Types (GET /api/v1/documents — real GCS pipeline data)
// ==========================================
// Mirrors zellovest_ingestion.schemas.documents (snake_case wire).

/** Derived explorer pill state (upload lease status + extraction confidence). */
export type DocumentStatus = 'processing' | 'extracted' | 'review_needed' | 'failed';

/** One explorer inventory row: uploads lease + extraction artifact summary + vendor tag. */
export interface DocumentRecord {
  id: string;
  tenant_id: string;
  filename: string;
  /** Pipeline doc type: contract | amendment | purchase_order | invoice | policy | other */
  document_type: string;
  document_type_confidence: number | null;
  classification_method: string | null;
  status: DocumentStatus;
  /** Raw lease status: pending | staged | processing | completed | failed */
  upload_status: string;
  vendor_id: string | null;
  vendor_name: string | null;
  gcs_key: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  error: string | null;
  has_artifact: boolean;
  artifact_gcs_key: string | null;
  route: string | null;
  file_type: string | null;
  extraction_method: string | null;
  extraction_confidence: number | null;
  text_chars: number | null;
  uploaded_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  documents: DocumentRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface DocumentListParams {
  document_type?: string;
  /** Comma-separated doc types for merged tabs, e.g. "policy,other". */
  document_types?: string;
  status?: DocumentStatus;
  vendor_id?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

/** Full extraction payload persisted at artifacts/{tenant}/{upload}/extraction.json. */
export interface ExtractionEntity {
  field: string;
  value: string | number | null;
  confidence: number;
  page: number;
  bounding_box?: number[];
  extraction_method?: string;
}

export interface ExtractionPagePayload {
  page_number: number;
  text: string;
  text_blocks?: Array<{ text: string; bbox: number[]; confidence: number }>;
  tables?: Array<{ data: unknown; bbox: number[] }>;
  images?: Array<{ bbox: number[]; xref?: number }>;
}

export interface DocumentArtifact {
  schema_version: number;
  tenant_id: string;
  upload_id: string | null;
  source_gcs_key: string;
  filename: string;
  triage: {
    file_type: string;
    route: string;
    confidence: number;
    detection_method: string;
    has_images: boolean;
  };
  extraction: {
    route: string;
    file_type: string;
    extraction_method: string;
    extraction_confidence: number;
    full_text: string;
    pages: ExtractionPagePayload[];
    entities: ExtractionEntity[];
    tables: Array<{ data: unknown; bbox?: number[] }>;
  };
  classification: {
    document_type: string;
    confidence: number;
    method: string;
    note?: string;
  };
  provenance?: Record<string, unknown>;
  entity_provenance?: Array<Record<string, unknown>>;
  created_at: string;
}

/** Explorer detail: list row, artifact, review state, and typed structured data. */
export interface DocumentDetail extends DocumentRecord {
  classification: Record<string, unknown> | null;
  artifact: DocumentArtifact | null;
  review: ContractReviewRecord | null;
  structured_data: Record<string, unknown> | null;
}

/** Structured extraction waiting for human verification, or its commit receipt. */
export interface ContractReviewRecord {
  status: 'pending' | 'committed' | string;
  document_type?: string;
  confidence_threshold?: number;
  field_confidence?: Record<string, number>;
  data?: Record<string, unknown>;
  verified_data?: Record<string, unknown>;
  reason?: string;
  created_at?: string;
  reviewed_at?: string;
  reviewer_id?: string;
  reviewer_email?: string;
  contract_id?: string;
  term_version_ids?: string[];
}

/** Corrected commercial fields posted by a reviewer before ledger commit. */
export interface ContractReviewCommitRequest {
  contract_number: string;
  vendor_name: string;
  title: string | null;
  start_date: string;
  end_date: string | null;
  renewal_date: string | null;
  notice_period_days: number | null;
  auto_renew: boolean;
  termination_clause: string | null;
  terms: Array<{
    product_code: string;
    description: string;
    unit_price: number;
    currency: string;
    uom: string;
    qty_min: number | null;
    qty_max: number | null;
    discount_pct: number | null;
    effective_from: string;
    effective_to: string | null;
    escalation_pct: number | null;
    payment_terms: string;
    freight_terms: string;
    tax_rule: string;
  }>;
}

export interface ContractReviewCommitResponse {
  document_id: string;
  contract_id: string;
  term_version_ids: string[];
  review_status: 'committed';
  reviewed_at: string;
}

/** Short-lived signed GET URL (inline preview + download). */
export interface DocumentFileResponse {
  document_id: string;
  url: string;
  expires_at: string;
}

export interface UploadFile {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  vendorId?: string;
  status: UploadStatus;
  progress: number;
  error?: string;
  documentId?: string;
  // Backend lease id from POST /uploads/init (set once minted).
  // Presence means server-side state exists → cancel via DELETE.
  uploadId?: string;
  createdAt: string;
}

export interface UploadQueueState {
  files: UploadFile[];
  addFile: (file: File, vendorId?: string) => string;
  removeFile: (id: string) => void;
  retryFile: (id: string) => void;
  clearCompleted: () => void;
}

export interface Document {
  id: string;
  vendorId: string;
  documentType: DocumentType;
  fileName: string;
  fileSize: number;
  mimeType: string;
  pageCount?: number;
  extractionStatus: 'pending' | 'processing' | 'completed' | 'failed' | 'needs_review';
  extractionConfidence?: number;
  extractedData?: Record<string, unknown>;
  provenance?: DocumentProvenance;
  storageUrl: string;
  uploadedBy: string;
  uploadedAt: string;
}

export interface DocumentProvenance {
  field: string;
  value: unknown;
  confidence: number;
  sourceDocument: string;
  page: number;
  boundingBox?: string;
  extractionMethod: 'python_parser' | 'document_ai' | 'llm' | 'ocr';
  extractedAt: string;
}

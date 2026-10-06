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
export type UserRole = 'Procurement Team Member';

export interface UserSession {
  id: string; // OIDC Subject (sub)
  name: string;
  email: string;
  role: UserRole;
  department: string;
  avatarUrl?: string;
  organizationName: string; // Single-tenant organization boundary
  accessToken?: string; // Bearer token from WSO2 for API authorization
  idToken?: string; // OIDC ID token (sent as id_token_hint at logout)
  expiresAt?: number; // Access token expiry (epoch ms)
}

/**
 * Authentication state driven by WSO2 Identity Server (OIDC).
 * - startLogin(): redirect to WSO2 hosted login (Authorization Code + PKCE).
 * - completeLogin(): called by /auth/callback to exchange the code for tokens;
 *   resolves to true when a session was established, false on failure.
 * - logout(): clears the local session and invokes WSO2 RP-initiated logout.
 */
export interface AuthContextType {
  user: UserSession | null;
  isAuthenticated: boolean;
  isLoading: boolean; // session restore in progress (on app mount)
  isLoggingIn: boolean; // token exchange in progress (on callback)
  error: string | null; // last authentication error, if any
  startLogin: () => Promise<void>;
  completeLogin: (code: string, state: string | null) => Promise<boolean>;
  logout: () => Promise<void>;
  clearError: () => void;
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

export interface UploadFile {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  documentType: DocumentType;
  vendorId?: string;
  status: UploadStatus;
  progress: number;
  error?: string;
  documentId?: string;
  createdAt: string;
}

export interface UploadQueueState {
  files: UploadFile[];
  addFile: (file: File, documentType: DocumentType, vendorId?: string) => string;
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

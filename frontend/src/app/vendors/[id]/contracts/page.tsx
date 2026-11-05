'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { Contract, ContractHistory, VendorContractLine } from '@/types';
import { useApi } from '@/lib/api';
import { ContractTable } from '@/components/vendors/ContractTable';

function toContract(row: VendorContractLine): Contract {
  const units: Record<string, Contract['unitOfMeasurement']> = {
    user: 'per_user', seat: 'per_seat', month: 'per_month', year: 'per_year',
    usage: 'usage_based', flat: 'flat',
  };
  return {
    id: row.id,
    contractId: row.contract_id,
    vendorId: row.vendor_id,
    product: row.product,
    unitPrice: Number(row.unit_price),
    currency: row.currency,
    unitOfMeasurement: units[(row.uom || '').toLowerCase()] || 'flat',
    quantity: row.quantity === null ? undefined : Number(row.quantity),
    effectiveFrom: row.effective_from,
    effectiveTo: row.effective_to || undefined,
    version: row.version,
    amendmentOfId: row.amendment_of_id || undefined,
    status: row.status === 'active' ? 'active' : 'expired',
    paymentTerms: row.payment_terms || undefined,
    priceEscalation: row.price_escalation === null ? undefined : Number(row.price_escalation),
    renewalDate: row.renewal_date || undefined,
    autoRenewal: row.auto_renewal ?? undefined,
    noticePeriodDays: row.notice_period_days ?? undefined,
    pdfUrl: row.source_upload_id ? `/documents/${row.source_upload_id}` : undefined,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export default function VendorContractsPage() {
  const params = useParams();
  const vendorId = params.id as string;
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ContractHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    apiRef.current.contracts.listByVendor(vendorId)
      .then((rows) => { if (active) setContracts(rows.map(toContract)); })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : 'Unable to load contracts.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [vendorId]);

  const openHistory = async (contract: Contract) => {
    if (!contract.contractId) return;
    setHistoryLoading(true);
    setHistory(null);
    setError(null);
    try {
      setHistory(await apiRef.current.contracts.history(contract.contractId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load contract history.');
    } finally {
      setHistoryLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
        Contracts ({contracts.length})
      </h2>
      {error && <p role="alert" style={{ color: 'var(--color-danger)' }}>{error}</p>}
      <ContractTable contracts={contracts} isLoading={loading} onViewContract={openHistory} />
      {historyLoading && <p style={{ color: 'var(--text-secondary)' }}>Loading version history…</p>}
      {history && (
        <section aria-label="Contract version history" style={{ padding: 20, border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-surface)' }}>
          <h3 style={{ margin: '0 0 4px', color: 'var(--text-primary)' }}>
            {history.contract_number} · {history.vendor_name}
          </h3>
          <p style={{ margin: '0 0 18px', color: 'var(--text-secondary)', fontSize: 13 }}>
            {history.versions.length} source-backed version{history.versions.length === 1 ? '' : 's'}
          </p>
          <ol style={{ margin: 0, paddingLeft: 22, display: 'grid', gap: 16 }}>
            {history.versions.map((version) => (
              <li key={version.id}>
                <strong style={{ color: 'var(--text-primary)' }}>
                  v{version.version_no} · {version.change_type.replace('_', ' ')}
                </strong>
                <span style={{ marginLeft: 8, color: 'var(--text-secondary)', fontSize: 12 }}>
                  Effective {version.effective_from}{version.effective_to ? ` to ${version.effective_to}` : ' onward'}
                  {version.parent_version_no ? ` · follows v${version.parent_version_no}` : ''}
                </span>
                {version.source_upload_id && (
                  <a href={`/documents/${version.source_upload_id}`} style={{ display: 'block', marginTop: 4, color: 'var(--color-brand)', fontSize: 12 }}>
                    Source: {version.source_filename || 'open uploaded document'}
                  </a>
                )}
                <ul style={{ marginTop: 8, display: 'grid', gap: 5, color: 'var(--text-secondary)', fontSize: 12 }}>
                  {version.terms.map((term) => (
                    <li key={term.id}>
                      {term.description || term.product_code || 'Contract line'} — {term.currency} {Number(term.unit_price).toFixed(2)}{term.uom ? ` / ${term.uom}` : ''}
                      {term.effective_to ? ` (${term.effective_from} to ${term.effective_to})` : ` (${term.effective_from} onward)`}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

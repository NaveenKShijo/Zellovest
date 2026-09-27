'use client';

import React, { useState, useEffect } from 'react';
import { VendorCategory, VendorStatus, VendorListParams } from '@/types';

const CATEGORY_OPTIONS: VendorCategory[] = [
  'CRM & Sales',
  'Design & Prototyping',
  'Cloud Infrastructure',
  'Productivity & Messaging',
  'Development Tools',
  'HR & Finance',
  'Marketing & Analytics',
  'Security & Compliance',
  'Other',
];

const STATUS_OPTIONS: VendorStatus[] = [
  'compliant',
  'variance_flagged',
  'up_for_renewal',
  'maverick_detected',
  'inactive',
];

const STATUS_LABELS: Record<VendorStatus, string> = {
  compliant: 'Compliant',
  variance_flagged: 'Variance Flagged',
  up_for_renewal: 'Up for Renewal',
  maverick_detected: 'Maverick Detected',
  inactive: 'Inactive',
};

export interface VendorFiltersProps {
  initialParams?: VendorListParams;
  onChange: (params: VendorListParams) => void;
  totalCount?: number;
}

export function VendorFilters({ initialParams, onChange, totalCount }: VendorFiltersProps) {
  const [search, setSearch] = useState(initialParams?.search || '');
  const [categories, setCategories] = useState<VendorCategory[]>(initialParams?.categories || []);
  const [statuses, setStatuses] = useState<VendorStatus[]>(initialParams?.statuses || []);
  const [minSpend, setMinSpend] = useState<string>(initialParams?.minSpend?.toString() || '');
  const [maxSpend, setMaxSpend] = useState<string>(initialParams?.maxSpend?.toString() || '');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const debouncedSearch = useDebounce(search, 300);

  useEffect(() => {
    onChange({
      search: debouncedSearch,
      categories: categories.length > 0 ? categories : undefined,
      statuses: statuses.length > 0 ? statuses : undefined,
      minSpend: minSpend ? parseFloat(minSpend) : undefined,
      maxSpend: maxSpend ? parseFloat(maxSpend) : undefined,
    });
  }, [debouncedSearch, categories, statuses, minSpend, maxSpend, onChange]);

  const hasActiveFilters = categories.length > 0 || statuses.length > 0 || minSpend || maxSpend;

  const clearFilters = () => {
    setSearch('');
    setCategories([]);
    setStatuses([]);
    setMinSpend('');
    setMaxSpend('');
    onChange({});
  };

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <h2 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>Filters</h2>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            style={{
              fontSize: '12px',
              color: 'var(--color-brand)',
              fontWeight: 600,
              padding: '4px 8px',
              borderRadius: 'var(--radius-sm)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-subtle)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Clear all
          </button>
        )}
      </div>

      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div style={{ flex: 1, minWidth: '240px' }}>
          <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Search vendors
          </label>
          <div style={{ position: 'relative' }}>
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--text-muted)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, domain..."
              style={{
                width: '100%',
                padding: '10px 12px 10px 40px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-app)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--color-brand)')}
              onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
            />
          </div>
        </div>

        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '10px 16px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-app)',
            color: 'var(--text-secondary)',
            fontSize: '13px',
            fontWeight: 500,
            alignSelf: 'flex-end',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-brand)')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
        >
          {showAdvanced ? '▲' : '▼'} Advanced
        </button>
      </div>

      {showAdvanced && (
        <div style={{ animation: 'slideDown var(--transition-normal) ease-out' }}>
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '16px' }}>
            <div style={{ flex: 1, minWidth: '200px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                Categories
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {CATEGORY_OPTIONS.map((cat) => {
                  const isSelected = categories.includes(cat);
                  const colors = {
                    'CRM & Sales': { bg: 'var(--color-brand-subtle)', text: 'var(--color-brand)' },
                    'Design & Prototyping': { bg: '#F5E6FA', text: '#8B5E9E' },
                    'Cloud Infrastructure': { bg: '#E8F0FE', text: '#3A6BCC' },
                    'Productivity & Messaging': { bg: '#E6F4EA', text: '#2E7D32' },
                    'Development Tools': { bg: '#F3E8FD', text: '#7B4FD6' },
                    'HR & Finance': { bg: '#FFF3E0', text: '#E67E22' },
                    'Marketing & Analytics': { bg: '#FCE4EC', text: '#C2185B' },
                    'Security & Compliance': { bg: '#E8EAF6', text: '#3F51B5' },
                    'Other': { bg: 'var(--border-subtle)', text: 'var(--text-muted)' },
                  }[cat];
                  return (
                    <button
                      key={cat}
                      onClick={() => setCategories((prev) => (isSelected ? prev.filter((c) => c !== cat) : [...prev, cat]))}
                      style={{
                        fontSize: '11px',
                        fontWeight: 600,
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-full)',
                        backgroundColor: isSelected ? colors.bg : 'var(--bg-app)',
                        color: isSelected ? colors.text : 'var(--text-secondary)',
                        border: isSelected ? `1px solid ${colors.text}` : '1px solid var(--border-subtle)',
                        transition: 'all var(--transition-fast)',
                      }}
                    >
                      {cat}
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ flex: 1, minWidth: '200px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                Status
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {STATUS_OPTIONS.map((status) => {
                  const isSelected = statuses.includes(status);
                  const variant = {
                    compliant: 'success',
                    variance_flagged: 'danger',
                    up_for_renewal: 'warning',
                    maverick_detected: 'info',
                    inactive: 'default',
                  }[status];
                  return (
                    <button
                      key={status}
                      onClick={() => setStatuses((prev) => (isSelected ? prev.filter((s) => s !== status) : [...prev, status]))}
                      style={{
                        fontSize: '11px',
                        fontWeight: 600,
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-full)',
                        backgroundColor: isSelected ? `var(--color-${variant}-subtle)` : 'var(--bg-app)',
                        color: isSelected ? `var(--color-${variant})` : 'var(--text-secondary)',
                        border: isSelected ? `1px solid var(--color-${variant}-border)` : '1px solid var(--border-subtle)',
                        transition: 'all var(--transition-fast)',
                      }}
                    >
                      {STATUS_LABELS[status]}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '160px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                Min Annual Spend ($)
              </label>
              <input
                type="number"
                value={minSpend}
                onChange={(e) => setMinSpend(e.target.value)}
                placeholder="0"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  backgroundColor: 'var(--bg-app)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
                onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--color-brand)')}
                onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
              />
            </div>
            <div style={{ flex: 1, minWidth: '160px' }}>
              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
                Max Annual Spend ($)
              </label>
              <input
                type="number"
                value={maxSpend}
                onChange={(e) => setMaxSpend(e.target.value)}
                placeholder="No limit"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  backgroundColor: 'var(--bg-app)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
                onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--color-brand)')}
                onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
              />
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
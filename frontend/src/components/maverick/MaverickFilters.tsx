'use client';

import React from 'react';

interface MaverickFiltersProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedDepartment: string;
  onDepartmentChange: (dept: string) => void;
  minOverlapThreshold: number;
  onOverlapThresholdChange: (thresh: number) => void;
  selectedStatus: string;
  onStatusChange: (status: string) => void;
}

export function MaverickFilters({
  searchQuery,
  onSearchChange,
  selectedDepartment,
  onDepartmentChange,
  minOverlapThreshold,
  onOverlapThresholdChange,
  selectedStatus,
  onStatusChange,
}: MaverickFiltersProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '12px',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: '#FFFFFF',
        padding: '14px 18px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      {/* Search Input */}
      <div style={{ position: 'relative', minWidth: '260px', flex: '1 1 260px' }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Filter by unmanaged tool, employee, or cardholder..."
          style={{
            width: '100%',
            padding: '9px 12px 9px 36px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-strong)',
            backgroundColor: 'var(--bg-app)',
            fontSize: '13px',
            color: 'var(--text-primary)',
          }}
        />
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            position: 'absolute',
            left: '12px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--text-muted)',
          }}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        {/* Department Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="dept-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Department:
          </label>
          <select
            id="dept-filter"
            value={selectedDepartment}
            onChange={(e) => onDepartmentChange(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              fontSize: '12.5px',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            <option value="all">All Departments</option>
            <option value="Engineering">Engineering</option>
            <option value="Product Management">Product Management</option>
            <option value="Marketing">Marketing</option>
            <option value="Sales">Sales</option>
            <option value="Quality Assurance">Quality Assurance</option>
          </select>
        </div>

        {/* Overlap Similarity Threshold */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="overlap-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Semantic Match:
          </label>
          <select
            id="overlap-filter"
            value={minOverlapThreshold}
            onChange={(e) => onOverlapThresholdChange(Number(e.target.value))}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              fontSize: '12.5px',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            <option value={0}>Any Match (&gt; 0%)</option>
            <option value={0.80}>High Match (&ge; 80%)</option>
            <option value={0.85}>Very High (&ge; 85%)</option>
            <option value={0.90}>Near Duplicate (&ge; 90%)</option>
          </select>
        </div>

        {/* Status Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="mav-status-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Status:
          </label>
          <select
            id="mav-status-filter"
            value={selectedStatus}
            onChange={(e) => onStatusChange(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              fontSize: '12.5px',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            <option value="all">All Statuses</option>
            <option value="open">Open (Action Needed)</option>
            <option value="notified">Employee Notified</option>
            <option value="migrated">Migrated</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </div>
      </div>
    </div>
  );
}

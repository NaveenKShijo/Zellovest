'use client';

import React, { useState } from 'react';
import { AnswerSections } from '@/types/askAi';

interface AnswerSectionsViewProps {
  sections?: AnswerSections;
}

/**
 * AnswerSectionsView: Distinguishes Facts vs Calculations vs Hypotheses vs Needs Review
 * per PRD Requirements (Module M8 Evidence First Architecture)
 */
export const AnswerSectionsView: React.FC<AnswerSectionsViewProps> = ({ sections }) => {
  if (!sections) return null;

  const { facts = [], calculations = [], hypotheses = [], needs_review = [] } = sections;
  const totalItems = facts.length + calculations.length + hypotheses.length + needs_review.length;

  if (totalItems === 0) return null;

  const [activeTab, setActiveTab] = useState<'all' | 'facts' | 'calculations' | 'hypotheses' | 'needs_review'>('all');

  return (
    <div
      style={{
        marginTop: '14px',
        border: '1px solid #e7e1eb',
        borderRadius: '12px',
        backgroundColor: '#faf8fb',
        overflow: 'hidden',
      }}
    >
      {/* Header and Filter Tabs */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '8px',
          padding: '8px 12px',
          backgroundColor: '#f2ecf3',
          borderBottom: '1px solid #e4dce8',
        }}
      >
        <span
          style={{
            fontSize: '11px',
            fontWeight: 750,
            color: '#65475a',
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}
        >
          Grounding Breakdown · {totalItems} items
        </span>

        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          <TabButton
            active={activeTab === 'all'}
            onClick={() => setActiveTab('all')}
            label="All"
            count={totalItems}
          />
          {facts.length > 0 && (
            <TabButton
              active={activeTab === 'facts'}
              onClick={() => setActiveTab('facts')}
              label="Facts"
              count={facts.length}
              dotColor="#2e7d32"
            />
          )}
          {calculations.length > 0 && (
            <TabButton
              active={activeTab === 'calculations'}
              onClick={() => setActiveTab('calculations')}
              label="Calculations"
              count={calculations.length}
              dotColor="#7b1fa2"
            />
          )}
          {hypotheses.length > 0 && (
            <TabButton
              active={activeTab === 'hypotheses'}
              onClick={() => setActiveTab('hypotheses')}
              label="Hypotheses"
              count={hypotheses.length}
              dotColor="#e65100"
            />
          )}
          {needs_review.length > 0 && (
            <TabButton
              active={activeTab === 'needs_review'}
              onClick={() => setActiveTab('needs_review')}
              label="Needs Review"
              count={needs_review.length}
              dotColor="#c62828"
            />
          )}
        </div>
      </div>

      {/* Content Groups */}
      <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {(activeTab === 'all' || activeTab === 'facts') && facts.length > 0 && (
          <SectionGroup
            title="Confirmed Facts (Observed in Ingested Data)"
            badgeText="Verified"
            badgeBg="#e8f5e9"
            badgeColor="#2e7d32"
            badgeBorder="#c8e6c9"
            items={facts}
          />
        )}

        {(activeTab === 'all' || activeTab === 'calculations') && calculations.length > 0 && (
          <SectionGroup
            title="Deterministic Calculations & Variances"
            badgeText="Calculated"
            badgeBg="#f3e5f5"
            badgeColor="#6a1b9a"
            badgeBorder="#e1bee7"
            items={calculations}
          />
        )}

        {(activeTab === 'all' || activeTab === 'hypotheses') && hypotheses.length > 0 && (
          <SectionGroup
            title="AI Inferences & Hypotheses"
            badgeText="Hypothesis"
            badgeBg="#fff3e0"
            badgeColor="#e65100"
            badgeBorder="#ffe0b2"
            items={hypotheses}
          />
        )}

        {(activeTab === 'all' || activeTab === 'needs_review') && needs_review.length > 0 && (
          <SectionGroup
            title="Items Requiring Human Verification"
            badgeText="Action Required"
            badgeBg="#ffebee"
            badgeColor="#c62828"
            badgeBorder="#ffcdd2"
            items={needs_review}
          />
        )}
      </div>
    </div>
  );
};

const TabButton: React.FC<{
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  dotColor?: string;
}> = ({ active, onClick, label, count, dotColor }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      padding: '3px 8px',
      fontSize: '11px',
      fontWeight: 650,
      borderRadius: '6px',
      border: active ? '1px solid #7d4463' : '1px solid #dfd8e3',
      backgroundColor: active ? '#7d4463' : '#fff',
      color: active ? '#fff' : '#554f5f',
      cursor: 'pointer',
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px',
      transition: 'all 120ms ease',
    }}
  >
    {dotColor && (
      <span
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: active ? '#fff' : dotColor,
        }}
      />
    )}
    <span>{label}</span>
    <span
      style={{
        fontSize: '10px',
        opacity: active ? 0.9 : 0.7,
      }}
    >
      ({count})
    </span>
  </button>
);

const SectionGroup: React.FC<{
  title: string;
  badgeText: string;
  badgeBg: string;
  badgeColor: string;
  badgeBorder: string;
  items: string[];
}> = ({ title, badgeText, badgeBg, badgeColor, badgeBorder, items }) => (
  <div
    style={{
      backgroundColor: '#fff',
      border: '1px solid #ebe5ef',
      borderRadius: '8px',
      padding: '10px 12px',
    }}
  >
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '8px',
        marginBottom: '6px',
      }}
    >
      <span style={{ fontSize: '12px', fontWeight: 700, color: '#332e3d' }}>{title}</span>
      <span
        style={{
          fontSize: '10px',
          fontWeight: 700,
          padding: '2px 6px',
          borderRadius: '4px',
          backgroundColor: badgeBg,
          color: badgeColor,
          border: `1px solid ${badgeBorder}`,
        }}
      >
        {badgeText}
      </span>
    </div>
    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#4d4857', lineHeight: 1.55 }}>
      {items.map((item, idx) => (
        <li key={idx} style={{ margin: '3px 0' }}>
          {item}
        </li>
      ))}
    </ul>
  </div>
);

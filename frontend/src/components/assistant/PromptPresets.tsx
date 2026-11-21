'use client';

import React, { useState } from 'react';
import { PRD_PROMPT_PRESETS, PromptPresetItem } from '@/lib/askAiMockKnowledge';

interface PromptPresetsProps {
  onSelectPrompt: (prompt: string) => void;
  isAsking?: boolean;
}

const CATEGORIES: Array<PromptPresetItem['category']> = [
  'Cross-Domain',
  'Spend',
  'Contracts',
  'Invoices',
  'Licenses',
  'Maverick',
  'Vendor 360',
];

/**
 * PromptPresets: Full Coverage of PRD #23 Inquiries
 *
 * Provides ready-to-run questions categorized across all procurement domains.
 * Generous real estate, clear spacing, and modern relaxing cards layout.
 */
export const PromptPresets: React.FC<PromptPresetsProps> = ({ onSelectPrompt, isAsking }) => {
  const [selectedCategory, setSelectedCategory] = useState<PromptPresetItem['category']>('Cross-Domain');

  const filteredPrompts = PRD_PROMPT_PRESETS.filter((p) => p.category === selectedCategory);

  return (
    <div
      style={{
        marginTop: '14px',
        width: '100%',
        maxWidth: '1020px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '18px',
      }}
    >
      {/* Category Filter Pills */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '8px',
          width: '100%',
          padding: '4px 8px',
        }}
      >
        {CATEGORIES.map((cat) => {
          const isSelected = cat === selectedCategory;
          return (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              style={{
                padding: '7px 16px',
                borderRadius: '999px',
                fontSize: '12.5px',
                fontWeight: isSelected ? 750 : 600,
                border: isSelected ? '1px solid var(--color-brand, #8a526f)' : '1px solid #e2dbe4',
                backgroundColor: isSelected ? '#8a526f' : '#ffffff',
                color: isSelected ? '#ffffff' : '#575160',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                boxShadow: isSelected ? '0 2px 8px rgba(138, 82, 111, 0.25)' : 'none',
                transition: 'all 140ms ease',
              }}
              onMouseEnter={(e) => {
                if (!isSelected) {
                  e.currentTarget.style.borderColor = '#cca6bc';
                  e.currentTarget.style.backgroundColor = '#faf6f8';
                }
              }}
              onMouseLeave={(e) => {
                if (!isSelected) {
                  e.currentTarget.style.borderColor = '#e2dbe4';
                  e.currentTarget.style.backgroundColor = '#ffffff';
                }
              }}
            >
              {cat === 'Cross-Domain' ? '✦ Cross-Domain' : cat}
            </button>
          );
        })}
      </div>

      {/* Prompts Cards Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(310px, 1fr))',
          gap: '14px',
          width: '100%',
          marginTop: '4px',
        }}
      >
        {filteredPrompts.map((item) => (
          <button
            key={item.id}
            type="button"
            disabled={isAsking}
            onClick={() => onSelectPrompt(item.prompt)}
            style={{
              padding: '16px 20px',
              borderRadius: '13px',
              border: '1px solid #ede7ef',
              backgroundColor: '#ffffff',
              textAlign: 'left',
              cursor: isAsking ? 'not-allowed' : 'pointer',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '8px',
              boxShadow: '0 2px 8px rgba(45, 35, 55, 0.025)',
              transition: 'all 160ms ease',
              minHeight: '82px',
            }}
            onMouseEnter={(e) => {
              if (!isAsking) {
                e.currentTarget.style.borderColor = '#c79db3';
                e.currentTarget.style.backgroundColor = '#fdfafc';
                e.currentTarget.style.transform = 'translateY(-2px)';
                e.currentTarget.style.boxShadow = '0 6px 18px rgba(138, 82, 111, 0.09)';
              }
            }}
            onMouseLeave={(e) => {
              if (!isAsking) {
                e.currentTarget.style.borderColor = '#ede7ef';
                e.currentTarget.style.backgroundColor = '#ffffff';
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = '0 2px 8px rgba(45, 35, 55, 0.025)';
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
              <span style={{ fontSize: '13.5px', fontWeight: 750, color: '#2d2737' }}>
                {item.label}
              </span>
              <span
                style={{
                  fontSize: '13px',
                  fontWeight: 800,
                  color: 'var(--color-brand, #8a526f)',
                  marginLeft: '8px',
                }}
                aria-hidden="true"
              >
                ↗
              </span>
            </div>
            <p
              style={{
                margin: 0,
                fontSize: '12.5px',
                color: '#6c6575',
                lineHeight: 1.5,
              }}
            >
              {item.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
};

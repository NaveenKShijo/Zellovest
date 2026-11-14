'use client';

import React, { useState } from 'react';
import { SeatForecastData, SeatForecastScenario } from '@/types';

interface SeatForecastWidgetProps {
  forecast: SeatForecastData;
}

const DEPT_COLORS = ['#71091E', '#D77286', '#3D734E', '#466C82', '#AF6A20'];

export function SeatForecastWidget({ forecast }: SeatForecastWidgetProps) {
  const [selectedScenarioKey, setSelectedScenarioKey] = useState<
    'conservative' | 'recommended' | 'aggressive'
  >('recommended');
  const [activeDeptTab, setActiveDeptTab] = useState<string>('all');

  const selectedScenario: SeatForecastScenario = forecast.scenarios[selectedScenarioKey];

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(val);

  return (
    <div
      style={{
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-subtle)',
        padding: '24px',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
      }}
    >
      {/* Widget Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 700,
                textTransform: 'uppercase',
                padding: '2px 8px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--color-brand-subtle)',
                color: 'var(--color-brand)',
                border: '1px solid var(--color-brand-border)',
              }}
            >
              LightGBM Survival Analysis • Churn Forecast
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Renewal Date: <strong>{forecast.renewalDate}</strong>
            </span>
          </div>

          <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
            {forecast.productName} — Predictive Seat Commitment
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Replaces static heuristics with machine-learning survival curves modeling login frequency decay and team-specific churn.
          </p>
        </div>

        {/* Commitment Delta Badge */}
        <div
          style={{
            backgroundColor: 'var(--color-success-subtle)',
            border: '1px solid var(--color-success-border)',
            borderRadius: 'var(--radius-md)',
            padding: '10px 18px',
            textAlign: 'right',
          }}
        >
          <div style={{ fontSize: '11.5px', color: 'var(--color-success)', fontWeight: 600 }}>
            Recommended Commitment
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', justifyContent: 'flex-end', marginTop: '2px' }}>
            <span style={{ fontSize: '26px', fontWeight: 800, color: 'var(--color-success)' }}>
              {selectedScenario.seats}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              vs {forecast.currentCommitmentSeats} current
            </span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Cut <strong>{forecast.currentCommitmentSeats - selectedScenario.seats} shelfware seats</strong> ({selectedScenario.confidenceInterval})
          </div>
        </div>
      </div>

      {/* 1. SCENARIO SELECTOR CARDS */}
      <div>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '10px' }}>
          Select ML Optimization Scenario & Risk Tolerance:
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
          {(['conservative', 'recommended', 'aggressive'] as const).map((key) => {
            const sc = forecast.scenarios[key];
            const isSelected = selectedScenarioKey === key;
            return (
              <div
                key={key}
                onClick={() => setSelectedScenarioKey(key)}
                style={{
                  padding: '16px',
                  borderRadius: 'var(--radius-md)',
                  border: isSelected ? '2px solid var(--color-brand)' : '1px solid var(--border-subtle)',
                  backgroundColor: isSelected ? 'var(--bg-surface-tint)' : '#FFFFFF',
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  transition: 'all var(--transition-fast)',
                  boxShadow: isSelected ? 'var(--shadow-sm)' : 'none',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', fontWeight: 700, color: isSelected ? 'var(--color-brand)' : 'var(--text-primary)' }}>
                    {sc.label}
                  </span>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: 'var(--radius-full)',
                      backgroundColor: isSelected ? 'var(--color-brand)' : 'var(--bg-app)',
                      color: isSelected ? '#FFFFFF' : 'var(--text-secondary)',
                    }}
                  >
                    {sc.confidenceInterval}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                  <span style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)' }}>
                    {sc.seats} Seats
                  </span>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    ({sc.seats - forecast.currentCommitmentSeats} seats)
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11.5px', borderTop: '1px solid var(--border-subtle)', paddingTop: '6px' }}>
                  <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>
                    Shelfware Cut: +{formatCurrency(sc.shelfwareSavings)}
                  </span>
                  <span style={{ color: sc.trueupRisk > 0 ? 'var(--color-danger)' : 'var(--text-muted)', fontWeight: 600 }}>
                    True-up Risk: {formatCurrency(sc.trueupRisk)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. SUMMARY COMPARISON METRICS */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '14px',
          backgroundColor: 'var(--bg-app)',
          padding: '16px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Current Annual Commitment
          </span>
          <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
            {formatCurrency(forecast.currentCommitmentSeats * forecast.contractUnitCost)}
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            {forecast.currentCommitmentSeats} seats &times; {formatCurrency(forecast.contractUnitCost)}/yr
          </span>
        </div>

        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Proposed Commitment
          </span>
          <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--color-brand)', marginTop: '2px' }}>
            {formatCurrency(selectedScenario.seats * forecast.contractUnitCost)}
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            {selectedScenario.seats} seats &times; {formatCurrency(forecast.contractUnitCost)}/yr
          </span>
        </div>

        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Net Annual Savings
          </span>
          <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--color-success)', marginTop: '2px' }}>
            {formatCurrency(selectedScenario.shelfwareSavings - selectedScenario.trueupRisk)}
          </div>
          <span style={{ fontSize: '11px', color: 'var(--color-success)', fontWeight: 600 }}>
            Annual procurement ROI
          </span>
        </div>

        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Penalty Risk Assessment
          </span>
          <div style={{ fontSize: '18px', fontWeight: 700, color: selectedScenario.trueupRisk > 0 ? 'var(--color-warning)' : 'var(--color-success)', marginTop: '2px' }}>
            {selectedScenario.trueupRisk > 0 ? formatCurrency(selectedScenario.trueupRisk) : 'Zero Penalty ($0)'}
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            True-up barrier satisfied at {selectedScenario.confidenceInterval}
          </span>
        </div>
      </div>

      {/* 3. DEPARTMENT RETENTION PROBABILITY SURVIVAL CURVES (SVG) */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Department Seat Retention & Survival Curves
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Shows 90-day projected active seat survival probabilities per organizational unit.
            </p>
          </div>

          {/* Department Filter Tabs */}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              onClick={() => setActiveDeptTab('all')}
              style={{
                padding: '4px 10px',
                borderRadius: 'var(--radius-full)',
                fontSize: '11.5px',
                fontWeight: 600,
                backgroundColor: activeDeptTab === 'all' ? 'var(--color-brand)' : '#FFFFFF',
                color: activeDeptTab === 'all' ? '#FFFFFF' : 'var(--text-secondary)',
                border: '1px solid var(--border-strong)',
                cursor: 'pointer',
              }}
            >
              All Departments
            </button>
            {forecast.departmentCurves.map((dept) => (
              <button
                key={dept.department}
                onClick={() => setActiveDeptTab(dept.department)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-full)',
                  fontSize: '11.5px',
                  fontWeight: 600,
                  backgroundColor: activeDeptTab === dept.department ? 'var(--color-brand)' : '#FFFFFF',
                  color: activeDeptTab === dept.department ? '#FFFFFF' : 'var(--text-secondary)',
                  border: '1px solid var(--border-strong)',
                  cursor: 'pointer',
                }}
              >
                {dept.department}
              </button>
            ))}
          </div>
        </div>

        {/* SVG Curve Plot */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '20px',
          }}
        >
          <div style={{ width: '100%', height: '220px', position: 'relative' }}>
            <svg viewBox="0 0 700 220" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              {/* Gridlines */}
              <line x1="50" y1="20" x2="680" y2="20" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="50" y1="65" x2="680" y2="65" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="50" y1="110" x2="680" y2="110" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="50" y1="155" x2="680" y2="155" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="50" y1="200" x2="680" y2="200" stroke="#E8CED4" strokeWidth="1" />

              {/* Y Axis Labels (Probability) */}
              <text x="10" y="24" fontSize="10" fill="#9E7D84">100%</text>
              <text x="15" y="69" fontSize="10" fill="#9E7D84">90%</text>
              <text x="15" y="114" fontSize="10" fill="#9E7D84">80%</text>
              <text x="15" y="159" fontSize="10" fill="#9E7D84">70%</text>
              <text x="15" y="204" fontSize="10" fill="#9E7D84">60%</text>

              {/* Render Department Lines */}
              {forecast.departmentCurves.map((dept, idx) => {
                if (activeDeptTab !== 'all' && activeDeptTab !== dept.department) return null;
                const color = DEPT_COLORS[idx % DEPT_COLORS.length];

                // Coordinates for [Day 0, Day 30, Day 60, Day 90]
                // Y maps from 100% -> y=20 to 60% -> y=200
                const points = dept.projectedDecayCurve
                  .map((pt, i) => {
                    const x = 70 + i * 190;
                    // Formula: rate 1.0 -> 20, rate 0.6 -> 200
                    const y = 20 + ((1.0 - pt.retentionRate) / 0.4) * 180;
                    return `${x},${y}`;
                  })
                  .join(' ');

                return (
                  <g key={dept.department}>
                    <polyline
                      fill="none"
                      stroke={color}
                      strokeWidth={activeDeptTab === dept.department ? '3.5' : '2.5'}
                      points={points}
                    />
                    {dept.projectedDecayCurve.map((pt, i) => {
                      const x = 70 + i * 190;
                      const y = 20 + ((1.0 - pt.retentionRate) / 0.4) * 180;
                      return (
                        <circle
                          key={i}
                          cx={x}
                          cy={y}
                          r={activeDeptTab === dept.department ? '4.5' : '3.5'}
                          fill={color}
                          stroke="#FFFFFF"
                          strokeWidth="1.5"
                        />
                      );
                    })}
                  </g>
                );
              })}

              {/* X Axis Time Labels */}
              <text x="60" y="218" fontSize="11" fill="#6B4E55" fontWeight="600">Day 0 (Baseline)</text>
              <text x="245" y="218" fontSize="11" fill="#6B4E55" fontWeight="600">Day 30 (Cadence)</text>
              <text x="435" y="218" fontSize="11" fill="#6B4E55" fontWeight="600">Day 60 (Post-Onboarding)</text>
              <text x="620" y="218" fontSize="11" fill="#6B4E55" fontWeight="600">Day 90 (Renewal State)</text>
            </svg>
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)', fontSize: '12px' }}>
            {forecast.departmentCurves.map((dept, idx) => {
              const color = DEPT_COLORS[idx % DEPT_COLORS.length];
              return (
                <div key={dept.department} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '10px', height: '10px', borderRadius: 'var(--radius-full)', backgroundColor: color }} />
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{dept.department}:</span>
                  <span style={{ color: 'var(--text-secondary)' }}>
                    {dept.recommendedSeats} seats ({Math.round(dept.retentionProbability * 100)}% retention)
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

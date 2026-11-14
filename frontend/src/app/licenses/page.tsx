'use client';

import React, { useState } from 'react';
import { SaaSUtilizationItem } from '@/types';
import { MOCK_UTILIZATION_ITEMS } from '@/lib/mockData';
import { UtilizationTable } from '@/components/forecasting/UtilizationTable';
import { WasteCalculatorWidget } from '@/components/forecasting/WasteCalculatorWidget';
import { SeatForecastWidget } from '@/components/forecasting/SeatForecastWidget';

export default function LicensesPage() {
  const [items] = useState<SaaSUtilizationItem[]>(MOCK_UTILIZATION_ITEMS);
  const [selectedApp, setSelectedApp] = useState<SaaSUtilizationItem>(MOCK_UTILIZATION_ITEMS[0]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Page Title & Intro */}
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          SaaS Utilization & Predictive Seat Forecasting
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          ML-driven churn survival curves and penalty-aware optimization engines determine exact seat commitments for upcoming renewals, cutting shelfware without incurring true-up risk.
        </p>
      </div>

      {/* 1. SaaS Utilization Table (Purchased vs Active, 30/60/90d Inactivity) */}
      <UtilizationTable
        items={items}
        selectedAppId={selectedApp.id}
        onSelectApp={(app) => setSelectedApp(app)}
      />

      {/* 2. Interactive Waste Calculator Widget */}
      <WasteCalculatorWidget selectedApp={selectedApp} />

      {/* 3. NEW ML Forecast Widget (Recommended Commitment, Scenarios, Confidence Intervals, Retention Curves) */}
      <SeatForecastWidget forecast={selectedApp.forecast} />
    </div>
  );
}

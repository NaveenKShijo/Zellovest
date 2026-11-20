'use client';

import React from 'react';
import { ToolCall } from '@/types/askAi';

interface TelemetryChipsProps {
  intent?: string | null;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
  streamingStage?: string | null;
  processingTimeMs?: number;
}

/**
 * TelemetryChips: Visualizes live MCP execution pipeline & server boundaries
 *
 * Exposes MCP Server 1 (Procurement Intel), MCP Server 2 (Document Knowledge),
 * and MCP Server 3 (External Actions) activity per PRD #25 architecture.
 */
export const TelemetryChips: React.FC<TelemetryChipsProps> = ({
  intent,
  toolCalls = [],
  isStreaming,
  streamingStage,
  processingTimeMs,
}) => {
  if (!intent && toolCalls.length === 0 && !isStreaming) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '6px',
        margin: '8px 0 12px',
        padding: '6px 10px',
        borderRadius: '8px',
        backgroundColor: '#faf7fa',
        border: '1px solid #eee7f0',
        fontSize: '11px',
      }}
    >
      {/* Live Stage or Completed Badge */}
      {isStreaming ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            padding: '2px 7px',
            borderRadius: '999px',
            backgroundColor: '#f3e8ef',
            color: 'var(--color-brand, #8a526f)',
            fontWeight: 750,
          }}
        >
          <span
            style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: 'var(--color-brand, #8a526f)',
              animation: 'pulse 1s infinite',
            }}
          />
          <span>{streamingStage ? `Stage: ${streamingStage}` : 'Investigating…'}</span>
        </span>
      ) : (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            padding: '2px 7px',
            borderRadius: '999px',
            backgroundColor: '#e8f5e9',
            color: '#2e7d32',
            fontWeight: 750,
          }}
        >
          <span>✓</span>
          <span>MCP Host Grounded</span>
        </span>
      )}

      {/* Intent Chip */}
      {intent && (
        <span
          style={{
            color: '#655e6e',
            backgroundColor: '#fff',
            padding: '2px 7px',
            borderRadius: '5px',
            border: '1px solid #e5dfe7',
            fontWeight: 600,
          }}
        >
          Intent: <strong>{intent.replace(/_/g, ' ')}</strong>
        </span>
      )}

      {/* Latency */}
      {processingTimeMs !== undefined && (
        <span style={{ color: '#8d8794', marginLeft: 'auto', fontSize: '10.5px' }}>
          {(processingTimeMs / 1000).toFixed(2)}s elapsed
        </span>
      )}

      {/* Tool Execution Chips */}
      {toolCalls.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', width: '100%', marginTop: '4px', flexWrap: 'wrap' }}>
          <span style={{ color: '#8c8594', fontSize: '10.5px', fontWeight: 650 }}>
            MCP Tools:
          </span>
          {toolCalls.map((call, idx) => {
            const isServer1 = call.server?.includes('mcp-1') || call.server?.includes('procurement');
            const isServer2 = call.server?.includes('mcp-2') || call.server?.includes('document');
            const isServer3 = call.server?.includes('mcp-3') || call.server?.includes('external');

            let chipColor = '#5e5868';
            let chipBg = '#f1ecf4';
            if (isServer1) {
              chipColor = '#1565c0';
              chipBg = '#e3f2fd';
            } else if (isServer2) {
              chipColor = '#6a1b9a';
              chipBg = '#f3e5f5';
            } else if (isServer3) {
              chipColor = '#c62828';
              chipBg = '#ffebee';
            }

            return (
              <span
                key={`${call.tool}-${idx}`}
                style={{
                  fontSize: '10.5px',
                  fontWeight: 650,
                  fontFamily: 'Consolas, monospace',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  backgroundColor: chipBg,
                  color: chipColor,
                }}
                title={`Server: ${call.server || 'MCP'} | Success: ${call.success}`}
              >
                {call.tool}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
};

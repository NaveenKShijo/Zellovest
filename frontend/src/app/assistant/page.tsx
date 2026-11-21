'use client';

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Link from 'next/link';
import type {
  AskAICitation,
  EvidenceItem,
  ProposedAction,
  ToolCall,
  ConversationMessage,
  ConversationHistory,
  ActionPreviewResponse,
  Vendor,
} from '@/types';
import { useApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import { MarkdownRenderer } from '@/components/assistant/MarkdownRenderer';
import { AnswerSectionsView } from '@/components/assistant/AnswerSectionsView';
import { DataGapsAlert } from '@/components/assistant/DataGapsAlert';
import { CitationCard } from '@/components/assistant/CitationCard';
import { ActionCard } from '@/components/assistant/ActionCard';
import { HighRiskActionModal } from '@/components/assistant/HighRiskActionModal';
import { DocumentViewerModal } from '@/components/assistant/DocumentViewerModal';
import { ConversationSidebar } from '@/components/assistant/ConversationSidebar';
import { PromptPresets } from '@/components/assistant/PromptPresets';
import { TelemetryChips } from '@/components/assistant/TelemetryChips';
import styles from './assistant.module.css';

export default function AssistantPage() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;
  const { notify } = useToast();

  // Scope & Vendor State
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [vendorId, setVendorId] = useState('');

  // Conversation & Chat State
  const [conversations, setConversations] = useState<ConversationHistory[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(true);

  // Live SSE Streaming State
  const [streamingStage, setStreamingStage] = useState<string | null>(null);
  const [streamingIntent, setStreamingIntent] = useState<string | null>(null);
  const [streamingToolCalls, setStreamingToolCalls] = useState<ToolCall[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);

  // Document Inspection Modal State (@ exact page + bbox)
  const [isDocModalOpen, setIsDocModalOpen] = useState(false);
  const [docModalData, setDocModalData] = useState<{
    documentId: string;
    page: number;
    bbox?: number[] | null;
    title?: string;
    excerpt?: string | null;
  }>({
    documentId: '',
    page: 1,
    bbox: null,
  });

  // High-Risk Human Confirmation Modal State
  const [isHighRiskModalOpen, setIsHighRiskModalOpen] = useState(false);
  const [pendingHighRiskAction, setPendingHighRiskAction] = useState<ProposedAction | null>(null);
  const [actionPreviewData, setActionPreviewData] = useState<ActionPreviewResponse | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isExecutingAction, setIsExecutingAction] = useState(false);

  const messageEndRef = useRef<HTMLDivElement>(null);

  // 1. Initial Load: Vendors & Conversation History
  useEffect(() => {
    let cancelled = false;

    const params = new URLSearchParams(window.location.search);
    const initialPrompt = params.get('prompt');
    const initialVendor = params.get('vendorId');
    // A renewal handoff populates the composer for review before sending.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (initialPrompt) setQuestion(initialPrompt);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (initialVendor) setVendorId(initialVendor);

    // Load vendors
    apiRef.current.vendors
      .list()
      .then((res) => {
        if (!cancelled) setVendors(res.vendors ?? []);
      })
      .catch(() => {});

    // Load conversations
    apiRef.current.askAi
      .listConversations()
      .then((res) => {
        if (!cancelled && res.conversations?.length) {
          setConversations(res.conversations);
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, []);

  // 2. Auto-scroll on new messages or streaming tokens
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streamingContent, isAsking]);

  // 3. New Conversation
  const handleNewConversation = useCallback(() => {
    if (isAsking && abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setActiveConversationId(null);
    setMessages([]);
    setQuestion('');
    setStreamingContent('');
    setStreamingStage(null);
    setStreamingIntent(null);
    setStreamingToolCalls([]);
    setIsAsking(false);
  }, [isAsking]);

  // 4. Select Conversation from History
  const handleSelectConversation = useCallback(
    async (id: string) => {
      if (id === activeConversationId) return;
      if (isAsking && abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      setIsAsking(false);
      setActiveConversationId(id);

      try {
        const history = await apiRef.current.askAi.getConversation(id);
        if (history?.messages) {
          setMessages(history.messages);
        }
      } catch {
        // Fallback: look in local state
        const found = conversations.find((c) => c.conversation_id === id);
        if (found?.messages) {
          setMessages(found.messages);
        }
      }
    },
    [activeConversationId, isAsking, conversations]
  );

  // 5. Ask Question via Real-Time SSE Streaming
  const ask = async (value = question) => {
    const trimmed = value.trim();
    if (!trimmed || isAsking) return;

    setQuestion('');
    const userMsgId = crypto.randomUUID();
    const userMsg: ConversationMessage = {
      message_id: userMsgId,
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    };

    setMessages((current) => [...current, userMsg]);
    setIsAsking(true);
    setStreamingContent('');
    setStreamingStage('planning');
    setStreamingIntent(null);
    setStreamingToolCalls([]);

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    let accumulatedText = '';
    let currentIntent: string | null = null;
    let currentTools: ToolCall[] = [];
    let currentActions: ProposedAction[] = [];
    let resolvedConversationId = activeConversationId ?? crypto.randomUUID();

    try {
      const response = await api.askAi.stream(
        trimmed,
        {
          vendorId: vendorId || undefined,
          conversationId: activeConversationId || undefined,
          autoExecuteActions: true,
        },
        (event) => {
          if (event.type === 'start') {
            resolvedConversationId = event.conversation_id;
            setActiveConversationId(event.conversation_id);
          } else if (event.type === 'plan') {
            currentIntent = event.intent;
            setStreamingIntent(event.intent);
            setStreamingStage('executing_tools');
          } else if (event.type === 'tool') {
            const toolCall: ToolCall = {
              tool: event.tool,
              server: event.server,
              risk_class: event.risk_class,
              success: event.success,
              error: event.error,
            };
            currentTools = [...currentTools, toolCall];
            setStreamingToolCalls(currentTools);
          } else if (event.type === 'actions') {
            currentActions = event.proposed_actions || [];
          } else if (event.type === 'status') {
            setStreamingStage(event.stage);
          } else if (event.type === 'token') {
            accumulatedText += event.content;
            setStreamingContent(accumulatedText);
          }
        },
        abortController.signal
      );

      // Final assistant message
      const assistantMsg: ConversationMessage = {
        message_id: crypto.randomUUID(),
        role: 'assistant',
        content: response.answer || accumulatedText,
        created_at: new Date().toISOString(),
        citations: response.citations ?? [],
        evidence: response.evidence ?? [],
        proposed_actions: response.proposed_actions ?? currentActions,
        data_gaps: response.data_gaps ?? [],
        tool_calls: response.tool_calls ?? currentTools,
        sections: response.sections,
        intent: response.intent ?? currentIntent,
        confidence: response.confidence,
        processing_time_ms: response.processing_time_ms,
      };

      setMessages((current) => [...current, assistantMsg]);

      // Update conversations history list
      setConversations((current) => {
        const existingIdx = current.findIndex((c) => c.conversation_id === resolvedConversationId);
        const updatedEntry: ConversationHistory = {
          conversation_id: resolvedConversationId,
          question: trimmed,
          answer: assistantMsg.content,
          title: trimmed.slice(0, 48),
          message_count: (existingIdx >= 0 ? current[existingIdx].message_count : 0) + 2,
          created_at: new Date().toISOString(),
          last_message_at: new Date().toISOString(),
          messages: [...(existingIdx >= 0 ? current[existingIdx].messages : []), userMsg, assistantMsg],
        };

        if (existingIdx >= 0) {
          const next = [...current];
          next[existingIdx] = updatedEntry;
          return next;
        }
        return [updatedEntry, ...current];
      });
    } catch (error) {
      if (abortController.signal.aborted) {
        notify.info('Stream Stopped', 'AI response generation was stopped.');
        return;
      }
      const message = error instanceof Error ? error.message : 'Could not answer this question.';
      setMessages((current) => [
        ...current,
        {
          message_id: crypto.randomUUID(),
          role: 'assistant',
          content: message,
          created_at: new Date().toISOString(),
          error: true,
        },
      ]);
    } finally {
      setIsAsking(false);
      setStreamingContent('');
      setStreamingStage(null);
      abortControllerRef.current = null;
    }
  };

  const stopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const submitQuestion = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void ask();
  };

  const onQuestionKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  };

  // 6. Action Handlers: Low-Risk Inline Execution
  const handleExecuteLowRisk = async (action: ProposedAction) => {
    try {
      const confirmRes = await api.askAi.confirmAction(action.tool, action.arguments, {
        idempotencyKey: action.idempotency_key,
        conversationId: activeConversationId || undefined,
        note: 'Executed inline low-risk action from Ask AI',
      });

      if (confirmRes.success) {
        notify.success('Action Executed', `${action.tool.replace(/_/g, ' ')} completed successfully.`);
        // Mark action executed in message state
        setMessages((current) =>
          current.map((msg) => ({
            ...msg,
            proposed_actions: msg.proposed_actions?.map((act) =>
              act.action_id === action.action_id ? { ...act, executed: true, result: confirmRes.result } : act
            ),
          }))
        );
      } else {
        throw new Error(confirmRes.error || 'Execution failed');
      }
    } catch (err) {
      notify.error('Action Failed', err instanceof Error ? err.message : 'Execution failed');
    }
  };

  // 7. Action Handlers: High-Risk Human Confirmation Trigger & Modal
  const handleRequestHighRiskConfirm = async (action: ProposedAction) => {
    setPendingHighRiskAction(action);
    setIsHighRiskModalOpen(true);
    setIsLoadingPreview(true);

    try {
      const preview = await api.askAi.previewAction(action.tool, action.arguments);
      setActionPreviewData(preview);
    } catch {
      // Preview fallback already provided in action.preview
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const handleConfirmHighRisk = async (note: string) => {
    if (!pendingHighRiskAction) return;
    setIsExecutingAction(true);

    try {
      const confirmRes = await api.askAi.confirmAction(
        pendingHighRiskAction.tool,
        pendingHighRiskAction.arguments,
        {
          idempotencyKey: pendingHighRiskAction.idempotency_key,
          conversationId: activeConversationId || undefined,
          note,
        }
      );

      if (confirmRes.success) {
        notify.success(
          'Action Authorized & Executed',
          `Successfully authorized ${pendingHighRiskAction.tool.replace(/_/g, ' ')}.`
        );

        setMessages((current) =>
          current.map((msg) => ({
            ...msg,
            proposed_actions: msg.proposed_actions?.map((act) =>
              act.action_id === pendingHighRiskAction.action_id
                ? { ...act, executed: true, result: confirmRes.result }
                : act
            ),
          }))
        );

        setIsHighRiskModalOpen(false);
        setPendingHighRiskAction(null);
      } else {
        throw new Error(confirmRes.error || 'Confirmation failed');
      }
    } catch (err) {
      notify.error('Authorization Error', err instanceof Error ? err.message : 'Action failed');
      throw err;
    } finally {
      setIsExecutingAction(false);
    }
  };

  // 8. Citation Click Handler: Opens Exact Page & BBox Highlight Modal
  const handleOpenDocument = (
    documentId: string,
    page: number,
    bbox?: number[] | null,
    title?: string,
    excerpt?: string | null
  ) => {
    setDocModalData({
      documentId,
      page,
      bbox: bbox ?? null,
      title: title || 'Procurement Document',
      excerpt: excerpt ?? null,
    });
    setIsDocModalOpen(true);
  };

  return (
    <div className={styles.page}>
      {/* Top Page Header */}
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>AGENTIC AI PROCUREMENT REASONING</div>
          <h1 className={styles.title}>“Ask AI” Conversational Workspace</h1>
          <p className={styles.subtitle}>
            Multi-system intelligence across Spend, Contracts, Invoices, Okta Licenses, and Maverick SaaS.
            Evidence-grounded with strict human-in-the-loop governance.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <div className={styles.indexBadge}>
            <span style={{ color: '#2e7d32' }}>●</span>
            <span>MCP Protocol Active (MCP-1, MCP-2, MCP-3)</span>
          </div>
        </div>
      </header>

      {/* Scope Bar */}
      <div className={styles.scopeBar}>
        <div className={styles.scopeBarLeft}>
          <button
            type="button"
            className={styles.historyToggleBtn}
            onClick={() => setIsHistoryOpen((open) => !open)}
            title={isHistoryOpen ? 'Hide History' : 'Show History'}
          >
            <span>{isHistoryOpen ? '◀ Hide History' : '▶ History'}</span>
            {conversations.length > 0 && (
              <span
                style={{
                  backgroundColor: '#eee7f0',
                  padding: '1px 6px',
                  borderRadius: '999px',
                  fontSize: '11px',
                }}
              >
                {conversations.length}
              </span>
            )}
          </button>

          <label htmlFor="vendor-scope">Vendor Scope:</label>
          <select
            id="vendor-scope"
            value={vendorId}
            onChange={(event) => setVendorId(event.target.value)}
          >
            <option value="">All enterprise suppliers</option>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.canonicalName}
              </option>
            ))}
          </select>
          <span className={styles.scopeHint}>
            Context is injected into tool planning and document retrieval.
          </span>
        </div>

        <div className={styles.scopeBarRight}>
          <button
            type="button"
            onClick={handleNewConversation}
            style={{
              padding: '6px 12px',
              borderRadius: '7px',
              border: '1px solid #ebdbe4',
              backgroundColor: '#fff',
              color: 'var(--color-brand, #8a526f)',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            ＋ New Chat
          </button>
        </div>
      </div>

      {/* Main Workspace */}
      <div className={styles.workspaceLayout}>
        {/* Conversation History Drawer */}
        <ConversationSidebar
          isOpen={isHistoryOpen}
          onToggle={() => setIsHistoryOpen(false)}
          conversations={conversations}
          activeConversationId={activeConversationId}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
        />

        {/* Workspace Center + Explorer */}
        <div className={styles.workspaceMain}>
          {/* Chat Panel */}
          <section className={styles.chatPanel} aria-labelledby="ask-heading">
            <div className={styles.panelHeader}>
              <div className={styles.panelHeaderLeft}>
                <div className={styles.panelIcon} aria-hidden="true">✦</div>
                <div>
                  <h2 id="ask-heading">Ask AI Procurement Analyst</h2>
                  <p>Streaming answers grounded in contracts, ledgers, and live telemetry.</p>
                </div>
              </div>

              {activeConversationId && (
                <div style={{ fontSize: '11px', color: '#9791a0', fontFamily: 'Consolas, monospace' }}>
                  ID: {activeConversationId.slice(0, 8)}…
                </div>
              )}
            </div>

            {/* Messages Thread */}
            <div className={styles.messages} aria-live="polite" aria-label="Conversation history">
              {messages.length === 0 && !isAsking ? (
                <div className={styles.emptyChat}>
                  <div className={styles.emptyMark}>✦</div>
                  <h3>Ask AI Procurement Workspace</h3>
                  <p>
                    Synthesize questions across spend ledgers, contract clauses, reconciliation exceptions,
                    seat forecasting, maverick SaaS, or cross-domain root causes.
                  </p>

                  {/* PRD #23 Preset Prompts Library */}
                  <PromptPresets onSelectPrompt={(p) => void ask(p)} isAsking={isAsking} />
                </div>
              ) : (
                messages.map((message) => {
                  const isUser = message.role === 'user';
                  const confirmedZeros =
                    message.sections?.facts.filter((f) =>
                      f.toLowerCase().includes('zero') || f.toLowerCase().includes('0 ')
                    ) || [];

                  return (
                    <article
                      key={message.message_id}
                      className={`${styles.message} ${isUser ? styles.userMessage : styles.assistantMessage}`}
                    >
                      <div className={styles.messageLabel}>
                        <span>{isUser ? 'You' : 'Ask AI Procurement Agent'}</span>
                        {!isUser && message.confidence !== undefined && (
                          <span
                            style={{
                              fontSize: '10px',
                              backgroundColor: '#e8f5e9',
                              color: '#2e7d32',
                              padding: '1px 5px',
                              borderRadius: '4px',
                              fontWeight: 700,
                            }}
                          >
                            {Math.round(message.confidence * 100)}% Confidence
                          </span>
                        )}
                      </div>

                      {/* Assistant Telemetry Chips */}
                      {!isUser && (
                        <TelemetryChips
                          intent={message.intent}
                          toolCalls={message.tool_calls}
                          processingTimeMs={message.processing_time_ms}
                        />
                      )}

                      {/* Main Message Text / Markdown */}
                      {isUser ? (
                        <p className={styles.messageText}>{message.content}</p>
                      ) : (
                        <MarkdownRenderer content={message.content} />
                      )}

                      {/* Answer Sections Breakdown (Facts vs Calculations vs Hypotheses vs Needs Review) */}
                      {!isUser && message.sections && (
                        <AnswerSectionsView sections={message.sections} />
                      )}

                      {/* Data Gaps Alert: Distinguishes Unavailable Data vs Confirmed Zero */}
                      {!isUser && (message.data_gaps?.length || confirmedZeros.length > 0) ? (
                        <DataGapsAlert
                          dataGaps={message.data_gaps}
                          confirmedZeros={confirmedZeros}
                        />
                      ) : null}

                      {/* Citation Cards (Click opens doc @ page + bbox) */}
                      {!isUser && message.citations && message.citations.length > 0 && (
                        <div className={styles.citations}>
                          <div className={styles.citationsHeading}>
                            Evidence Sources · {message.citations.length} Verified
                          </div>
                          {message.citations.map((citation, cIdx) => {
                            const evidenceItem = message.evidence?.find(
                              (e) => e.document_id === citation.source_id || e.source_id === citation.source_id
                            );
                            return (
                              <CitationCard
                                key={`${citation.source_id}-${cIdx}`}
                                citation={citation}
                                evidenceItem={evidenceItem}
                                index={cIdx}
                                onOpenDocument={handleOpenDocument}
                              />
                            );
                          })}
                        </div>
                      )}

                      {/* Proposed Actions (Low-Risk Inline & High-Risk Confirmation) */}
                      {!isUser && message.proposed_actions && message.proposed_actions.length > 0 && (
                        <div className={styles.actionsSection}>
                          <div className={styles.actionsHeading}>
                            Proposed Procurement Actions ({message.proposed_actions.length})
                          </div>
                          {message.proposed_actions.map((action) => (
                            <ActionCard
                              key={action.action_id}
                              action={action}
                              onExecuteLowRisk={handleExecuteLowRisk}
                              onRequestHighRiskConfirm={handleRequestHighRiskConfirm}
                            />
                          ))}
                        </div>
                      )}

                      {!isUser && message.processing_time_ms !== undefined && (
                        <div className={styles.responseMeta}>
                          <span>{(message.processing_time_ms / 1000).toFixed(1)}s elapsed</span>
                          <span>·</span>
                          <span>grounded via MCP host</span>
                        </div>
                      )}
                    </article>
                  );
                })
              )}

              {/* Live Streaming Message Box */}
              {isAsking && (
                <article className={`${styles.message} ${styles.assistantMessage}`}>
                  <div className={styles.messageLabel}>
                    <span>Ask AI Procurement Agent</span>
                    <span style={{ color: 'var(--color-brand, #8a526f)', fontSize: '10.5px' }}>
                      ● Streaming via SSE
                    </span>
                  </div>

                  <TelemetryChips
                    intent={streamingIntent}
                    toolCalls={streamingToolCalls}
                    isStreaming={true}
                    streamingStage={streamingStage}
                  />

                  {streamingContent ? (
                    <MarkdownRenderer content={streamingContent} isStreaming={true} />
                  ) : (
                    <div className={styles.loadingMessage}>
                      <span className={styles.spinner} />
                      <span>
                        {streamingStage === 'executing_tools'
                          ? 'Invoking MCP tools across PostgreSQL, RAG, and live telemetry…'
                          : streamingStage === 'synthesizing'
                          ? 'Synthesizing evidence-grounded answer…'
                          : 'Planning inquiry execution steps…'}
                      </span>
                    </div>
                  )}
                </article>
              )}

              <div ref={messageEndRef} />
            </div>

            {/* Composer */}
            <form className={styles.composer} onSubmit={submitQuestion}>
              <textarea
                aria-label="Ask a procurement question"
                placeholder="Ask about SaaS spend increases, 90-day renewals, unmanaged card tools, or seat commitment forecasts…"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={onQuestionKeyDown}
                maxLength={2000}
                rows={2}
                disabled={isAsking}
              />
              <div className={styles.composerFooter}>
                <span>Enter to send · Shift + Enter for newline</span>

                <div className={styles.composerButtons}>
                  {isAsking && (
                    <button type="button" onClick={stopStreaming} className={styles.stopButton}>
                      ■ Stop Generation
                    </button>
                  )}

                  <button
                    type="submit"
                    disabled={!question.trim() || isAsking}
                    className={styles.submitButton}
                  >
                    <span>{isAsking ? 'Reasoning…' : 'Ask AI'}</span>
                    <span aria-hidden="true">→</span>
                  </button>
                </div>
              </div>
            </form>
          </section>

        </div>
      </div>

      {/* Document Viewer Modal (@ exact page + bbox highlight) */}
      <DocumentViewerModal
        isOpen={isDocModalOpen}
        onClose={() => setIsDocModalOpen(false)}
        documentId={docModalData.documentId}
        initialPage={docModalData.page}
        bbox={docModalData.bbox}
        documentTitle={docModalData.title}
        excerpt={docModalData.excerpt}
      />

      {/* High-Risk Action Confirmation Modal (Strict Human-in-the-Loop) */}
      <HighRiskActionModal
        isOpen={isHighRiskModalOpen}
        action={pendingHighRiskAction}
        previewData={actionPreviewData}
        isLoadingPreview={isLoadingPreview}
        isExecuting={isExecutingAction}
        onClose={() => {
          setIsHighRiskModalOpen(false);
          setPendingHighRiskAction(null);
        }}
        onConfirm={handleConfirmHighRisk}
      />
    </div>
  );
}

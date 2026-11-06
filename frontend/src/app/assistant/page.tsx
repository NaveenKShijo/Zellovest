'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import Link from 'next/link';
import type { AskAICitation, RAGSearchChunk, Vendor } from '@/types';
import { useApi } from '@/lib/api';
import styles from './assistant.module.css';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: AskAICitation[];
  elapsedMs?: number;
  error?: boolean;
}

const SUGGESTIONS = [
  'What is the renewal notice period in our contract?',
  'Can the vendor raise prices during the current term?',
  'What changed in the latest amendment?',
];

export default function AssistantPage() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [vendorId, setVendorId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [documentType, setDocumentType] = useState('');
  const [searchResults, setSearchResults] = useState<RAGSearchChunk[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const messageEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    apiRef.current.vendors.list()
      .then((response) => {
        if (!cancelled) setVendors(response.vendors ?? []);
      })
      .catch(() => {
        // Vendor filtering is optional; the research UI remains useful without it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, isAsking]);

  const ask = async (value = question) => {
    const trimmed = value.trim();
    if (!trimmed || isAsking) return;
    setQuestion('');
    setMessages((current) => [...current, {
      id: crypto.randomUUID(), role: 'user', content: trimmed,
    }]);
    setIsAsking(true);
    try {
      const response = await api.askAi.ask(trimmed, vendorId || undefined);
      setMessages((current) => [...current, {
        id: response.conversation_id || crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        citations: response.citations ?? [],
        elapsedMs: response.processing_time_ms,
      }]);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not answer this question.';
      setMessages((current) => [...current, {
        id: crypto.randomUUID(), role: 'assistant', content: message, error: true,
      }]);
    } finally {
      setIsAsking(false);
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

  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = searchQuery.trim();
    if (!trimmed || isSearching) return;
    setIsSearching(true);
    setSearchError(null);
    setHasSearched(true);
    setSearchResults([]);
    try {
      const response = await api.rag.search({
        query: trimmed,
        vendor_id: vendorId || undefined,
        document_type: documentType || undefined,
        limit: 8,
      });
      setSearchResults(response.chunks ?? []);
    } catch (error) {
      setSearchResults([]);
      setSearchError(error instanceof Error ? error.message : 'Could not search documents.');
    } finally {
      setIsSearching(false);
    }
  };

  const citationCard = (citation: AskAICitation, index: number) => (
    <div className={styles.citation} key={`${citation.source_id}-${index}`}>
      <div className={styles.citationTop}>
        <span className={styles.citationNumber}>{index + 1}</span>
        <span className={styles.citationTitle}>{citation.description}</span>
        <Link className={styles.sourceLink} href={`/documents/${citation.source_id}`}>
          Open source
        </Link>
      </div>
      {citation.excerpt && <p className={styles.citationExcerpt}>{citation.excerpt}</p>}
    </div>
  );

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>DOCUMENT INTELLIGENCE</div>
          <h1 className={styles.title}>Research your procurement documents</h1>
          <p className={styles.subtitle}>
            Ask questions across indexed contracts and amendments, or search for the source passages yourself.
          </p>
        </div>
        <div className={styles.indexBadge}>
          Indexed contracts and amendments
        </div>
      </header>

      <div className={styles.scopeBar}>
        <label htmlFor="vendor-scope">Research scope</label>
        <select id="vendor-scope" value={vendorId} onChange={(event) => setVendorId(event.target.value)}>
          <option value="">All vendors</option>
          {vendors.map((vendor) => (
            <option key={vendor.id} value={vendor.id}>{vendor.canonicalName}</option>
          ))}
        </select>
        <span className={styles.scopeHint}>The selected vendor filter applies to questions and passage search.</span>
      </div>

      <main className={styles.workspace}>
        <section className={styles.chatPanel} aria-labelledby="ask-heading">
          <div className={styles.panelHeader}>
            <div className={styles.panelIcon} aria-hidden="true">✦</div>
            <div>
              <h2 id="ask-heading">Ask your documents</h2>
              <p>Answers use retrieved evidence and include source citations.</p>
            </div>
          </div>

          <div className={styles.messages} aria-live="polite" aria-label="Research conversation">
            {messages.length === 0 ? (
              <div className={styles.emptyChat}>
                <div className={styles.emptyMark}>Z</div>
                <h3>What would you like to know?</h3>
                <p>Try a question about renewal terms, price changes, termination rights, or an amendment.</p>
                <div className={styles.suggestions}>
                  {SUGGESTIONS.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => void ask(suggestion)}>
                      {suggestion}<span aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => (
                <article
                  className={`${styles.message} ${message.role === 'user' ? styles.userMessage : styles.assistantMessage}`}
                  key={message.id}
                >
                  <div className={styles.messageLabel}>{message.role === 'user' ? 'You' : 'Zellovest research'}</div>
                  <p className={message.error ? styles.errorText : styles.messageText}>{message.content}</p>
                  {message.citations && message.citations.length > 0 && (
                    <div className={styles.citations}>
                      <div className={styles.citationsHeading}>Sources · {message.citations.length}</div>
                      {message.citations.map(citationCard)}
                    </div>
                  )}
                  {message.elapsedMs !== undefined && (
                    <div className={styles.responseMeta}>{(message.elapsedMs / 1000).toFixed(1)}s · grounded in indexed documents</div>
                  )}
                </article>
              ))
            )}
            {isAsking && <div className={styles.loadingMessage}><span className={styles.spinner} />Searching documents and preparing an evidence-based answer…</div>}
            <div ref={messageEndRef} />
          </div>

          <form className={styles.composer} onSubmit={submitQuestion}>
            <textarea
              aria-label="Ask a procurement document question"
              placeholder="Ask about a contract term, pricing clause, or amendment…"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={onQuestionKeyDown}
              maxLength={2000}
              rows={2}
              disabled={isAsking}
            />
            <div className={styles.composerFooter}>
              <span>Enter to send · Shift + Enter for a new line</span>
              <button type="submit" disabled={!question.trim() || isAsking}>
                {isAsking ? 'Researching…' : 'Ask'} <span aria-hidden="true">→</span>
              </button>
            </div>
          </form>
        </section>

        <aside className={styles.searchPanel} aria-labelledby="search-heading">
          <div className={styles.panelHeader}>
            <div className={styles.searchIcon} aria-hidden="true">⌕</div>
            <div>
              <h2 id="search-heading">Find source passages</h2>
              <p>Search exact terms or describe a clause.</p>
            </div>
          </div>
          <form className={styles.searchForm} onSubmit={search}>
            <label htmlFor="passage-query">Search documents</label>
            <div className={styles.searchInputWrap}>
              <input
                id="passage-query"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="e.g. annual price increase cap"
                maxLength={500}
              />
              <button type="submit" disabled={!searchQuery.trim() || isSearching} aria-label="Search passages">
                {isSearching ? <span className={styles.spinner} /> : '⌕'}
              </button>
            </div>
            <label htmlFor="document-type">Document type</label>
            <select id="document-type" value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
              <option value="">All indexed documents</option>
              <option value="contract">Contracts</option>
              <option value="amendment">Amendments</option>
            </select>
          </form>

          <div className={styles.searchResults} aria-live="polite">
            {searchError && <div className={styles.inlineError} role="alert">{searchError}</div>}
            {!hasSearched && !searchError && (
              <div className={styles.searchEmpty}>
                <span aria-hidden="true">⌕</span>
                <p>Passages will appear here with their document, page, and section.</p>
              </div>
            )}
            {hasSearched && !isSearching && !searchError && searchResults.length === 0 && (
              <div className={styles.searchEmpty}><p>No matching passages found. Try broader wording.</p></div>
            )}
            {searchResults.map((chunk) => (
              <article className={styles.resultCard} key={chunk.chunk_id}>
                <div className={styles.resultMeta}>
                  <span>{chunk.provenance?.filename || 'Procurement document'}</span>
                  <span>{chunk.page ? `Page ${chunk.page}` : 'Page not available'}{chunk.section ? ` · ${chunk.section}` : ''}</span>
                </div>
                <p>{chunk.content}</p>
                <div className={styles.resultFooter}>
                  <span>{chunk.document_type.replace('_', ' ')}</span>
                  <Link href={`/documents/${chunk.document_id}`}>View document ↗</Link>
                </div>
              </article>
            ))}
          </div>
        </aside>
      </main>
    </div>
  );
}

'use client';

import React, { useState } from 'react';
import { ConversationHistory } from '@/types/askAi';

interface ConversationSidebarProps {
  conversations: ConversationHistory[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation?: (id: string) => void;
  isOpen: boolean;
  onToggle: () => void;
}

/**
 * ConversationSidebar: Manages Ask AI Session History
 */
export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
  isOpen,
  onToggle,
}) => {
  const [search, setSearch] = useState('');

  const filtered = conversations.filter((c) =>
    (c.title || c.question).toLowerCase().includes(search.toLowerCase())
  );

  return (
    <aside
      style={{
        width: isOpen ? '280px' : '0px',
        minWidth: isOpen ? '280px' : '0px',
        transition: 'width 200ms ease, min-width 200ms ease',
        backgroundColor: '#fff',
        borderRight: isOpen ? '1px solid #ebe5ef' : 'none',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        height: '100%',
        flexShrink: 0,
      }}
    >
      {/* Top Header */}
      <div
        style={{
          padding: '16px 14px 12px',
          borderBottom: '1px solid #efeaf1',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '13px', fontWeight: 750, color: '#2b2734' }}>
            Chat History
          </span>
          <button
            type="button"
            onClick={onToggle}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#817c89',
              fontSize: '14px',
              cursor: 'pointer',
              padding: '2px 6px',
            }}
            title="Collapse sidebar"
          >
            ◀
          </button>
        </div>

        {/* New Chat Button */}
        <button
          type="button"
          onClick={onNewConversation}
          style={{
            width: '100%',
            padding: '9px 12px',
            backgroundColor: '#f6edf2',
            border: '1px solid #eadbe4',
            borderRadius: '9px',
            color: 'var(--color-brand, #8a526f)',
            fontSize: '12.5px',
            fontWeight: 750,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            transition: 'background-color 150ms ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f1e2ea')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#f6edf2')}
        >
          <span>＋</span>
          <span>New Investigation</span>
        </button>

        {/* Search Input */}
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search history…"
          style={{
            width: '100%',
            padding: '6px 10px',
            fontSize: '12px',
            borderRadius: '7px',
            border: '1px solid #e2dbdf',
            backgroundColor: '#fbf9fb',
            color: '#262332',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* Conversation List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {filtered.length === 0 ? (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: '#97919e', fontSize: '12px' }}>
            {conversations.length === 0 ? 'No previous chats yet' : 'No matching chats'}
          </div>
        ) : (
          filtered.map((conv) => {
            const isActive = conv.conversation_id === activeConversationId;
            const displayTitle = conv.title || conv.question || 'Untitled inquiry';

            return (
              <div
                key={conv.conversation_id}
                onClick={() => onSelectConversation(conv.conversation_id)}
                style={{
                  padding: '10px 11px',
                  borderRadius: '9px',
                  marginBottom: '4px',
                  cursor: 'pointer',
                  backgroundColor: isActive ? '#f8f2f6' : 'transparent',
                  border: isActive ? '1px solid #ebdbe4' : '1px solid transparent',
                  transition: 'all 120ms ease',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = '#faf8fa';
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                <div
                  style={{
                    fontSize: '12.5px',
                    fontWeight: isActive ? 700 : 550,
                    color: isActive ? 'var(--color-brand, #8a526f)' : '#332d3c',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                  title={displayTitle}
                >
                  {displayTitle}
                </div>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginTop: '4px',
                    fontSize: '10.5px',
                    color: '#908a98',
                  }}
                >
                  <span>
                    {conv.last_message_at
                      ? new Date(conv.last_message_at).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                        })
                      : 'Recent'}
                  </span>
                  {conv.message_count > 0 && (
                    <span
                      style={{
                        backgroundColor: '#eee8f0',
                        padding: '1px 5px',
                        borderRadius: '999px',
                        fontWeight: 650,
                      }}
                    >
                      {conv.message_count} {conv.message_count === 1 ? 'msg' : 'msgs'}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
};

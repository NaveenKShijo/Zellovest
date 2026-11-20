'use client';

import React, { useMemo } from 'react';

interface MarkdownRendererProps {
  content: string;
  isStreaming?: boolean;
}

/**
 * Enterprise Markdown Renderer
 *
 * Supports:
 * - Headings (H1, H2, H3, H4)
 * - Tables with formatted headers, borders, and cells
 * - Bullet lists, ordered lists, nested items
 * - Bold, italic, strikethrough
 * - Inline code and fenced code blocks with copy-to-clipboard
 * - Blockquotes with subtle brand tint
 * - Clean external/internal links
 * - Streaming typing cursor
 */
export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, isStreaming }) => {
  const renderedElements = useMemo(() => {
    return parseMarkdown(content);
  }, [content]);

  return (
    <div className="ask-ai-markdown" style={{ lineHeight: 1.65, fontSize: '13.5px', color: '#262332' }}>
      {renderedElements}
      {isStreaming && (
        <span
          className="streaming-cursor"
          style={{
            display: 'inline-block',
            width: '6px',
            height: '14px',
            backgroundColor: 'var(--color-brand, #8a526f)',
            marginLeft: '4px',
            verticalAlign: 'middle',
            borderRadius: '1px',
            animation: 'blink 1s infinite',
          }}
        />
      )}
    </div>
  );
};

function parseMarkdown(text: string): React.ReactNode[] {
  if (!text) return [];

  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 1. Fenced Code Block
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      const codeString = codeLines.join('\n');
      elements.push(
        <CodeBlock key={`code-${i}`} code={codeString} language={lang} />
      );
      continue;
    }

    // 2. Markdown Table
    if (line.includes('|') && lines[i + 1] && lines[i + 1].includes('|') && lines[i + 1].includes('-')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      elements.push(<MarkdownTable key={`table-${i}`} lines={tableLines} />);
      continue;
    }

    // 3. Headings
    if (line.startsWith('# ')) {
      elements.push(
        <h2 key={`h1-${i}`} style={{ fontSize: '18px', fontWeight: 750, color: '#1f1c28', margin: '14px 0 8px' }}>
          {renderInline(line.slice(2))}
        </h2>
      );
      i++;
      continue;
    }
    if (line.startsWith('## ')) {
      elements.push(
        <h3 key={`h2-${i}`} style={{ fontSize: '16px', fontWeight: 700, color: '#282434', margin: '12px 0 6px' }}>
          {renderInline(line.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={`h3-${i}`} style={{ fontSize: '14.5px', fontWeight: 700, color: '#322d40', margin: '10px 0 6px' }}>
          {renderInline(line.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith('#### ')) {
      elements.push(
        <h5 key={`h4-${i}`} style={{ fontSize: '13.5px', fontWeight: 650, color: '#433c52', margin: '8px 0 4px' }}>
          {renderInline(line.slice(5))}
        </h5>
      );
      i++;
      continue;
    }

    // 4. Blockquote
    if (line.startsWith('> ')) {
      const quoteLines: string[] = [line.slice(2)];
      i++;
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      elements.push(
        <blockquote
          key={`quote-${i}`}
          style={{
            margin: '10px 0',
            padding: '8px 14px',
            borderLeft: '3px solid var(--color-brand, #8a526f)',
            backgroundColor: '#fbf7f9',
            borderRadius: '0 8px 8px 0',
            color: '#494454',
            fontStyle: 'italic',
          }}
        >
          {quoteLines.map((ql, qidx) => (
            <p key={qidx} style={{ margin: qidx > 0 ? '4px 0 0' : 0 }}>
              {renderInline(ql)}
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    // 5. Unordered List Items
    if (/^\s*[-*•]\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*[-*•]\s+/, ''));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} style={{ margin: '8px 0', paddingLeft: '22px' }}>
          {listItems.map((item, idx) => (
            <li key={idx} style={{ margin: '4px 0' }}>
              {renderInline(item)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // 6. Ordered List Items
    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} style={{ margin: '8px 0', paddingLeft: '22px' }}>
          {listItems.map((item, idx) => (
            <li key={idx} style={{ margin: '4px 0' }}>
              {renderInline(item)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // 7. Horizontal Rule
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      elements.push(<hr key={`hr-${i}`} style={{ border: 'none', borderTop: '1px solid #e7e2ea', margin: '14px 0' }} />);
      i++;
      continue;
    }

    // 8. Regular Paragraph or blank line
    if (line.trim() === '') {
      i++;
      continue;
    }

    elements.push(
      <p key={`p-${i}`} style={{ margin: '6px 0' }}>
        {renderInline(line)}
      </p>
    );
    i++;
  }

  return elements;
}

function renderInline(text: string): React.ReactNode {
  // Regex to match code spans, bold, italic, and links
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let keyIdx = 0;

  while (remaining.length > 0) {
    // 1. Inline code: `code`
    const codeMatch = remaining.match(/^`([^`]+)`/);
    if (codeMatch) {
      parts.push(
        <code
          key={`inline-code-${keyIdx++}`}
          style={{
            background: '#f2edf4',
            color: '#6e3c56',
            padding: '2px 5px',
            borderRadius: '4px',
            fontSize: '12px',
            fontFamily: 'Consolas, Monaco, monospace',
          }}
        >
          {codeMatch[1]}
        </code>
      );
      remaining = remaining.slice(codeMatch[0].length);
      continue;
    }

    // 2. Bold + Italic: ***text*** or ___text___
    const boldItalicMatch = remaining.match(/^(\*\*\*|___)(.+?)\1/);
    if (boldItalicMatch) {
      parts.push(
        <strong key={`bi-${keyIdx++}`}>
          <em>{boldItalicMatch[2]}</em>
        </strong>
      );
      remaining = remaining.slice(boldItalicMatch[0].length);
      continue;
    }

    // 3. Bold: **text** or __text__
    const boldMatch = remaining.match(/^(\*\*|__)(.+?)\1/);
    if (boldMatch) {
      parts.push(
        <strong key={`b-${keyIdx++}`} style={{ fontWeight: 700, color: '#1f1b26' }}>
          {boldMatch[2]}
        </strong>
      );
      remaining = remaining.slice(boldMatch[0].length);
      continue;
    }

    // 4. Italic: *text* or _text_
    const italicMatch = remaining.match(/^(\*|_)(.+?)\1/);
    if (italicMatch) {
      parts.push(<em key={`i-${keyIdx++}`}>{italicMatch[2]}</em>);
      remaining = remaining.slice(italicMatch[0].length);
      continue;
    }

    // 5. Links: [text](url)
    const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/);
    if (linkMatch) {
      parts.push(
        <a
          key={`a-${keyIdx++}`}
          href={linkMatch[2]}
          target={linkMatch[2].startsWith('http') ? '_blank' : undefined}
          rel={linkMatch[2].startsWith('http') ? 'noopener noreferrer' : undefined}
          style={{
            color: 'var(--color-brand, #8a526f)',
            fontWeight: 600,
            textDecoration: 'underline',
          }}
        >
          {linkMatch[1]}
        </a>
      );
      remaining = remaining.slice(linkMatch[0].length);
      continue;
    }

    // Regular char chunk until next special syntax
    const nextSpecial = remaining.search(/[`*_\[]/);
    if (nextSpecial === -1) {
      parts.push(remaining);
      break;
    } else if (nextSpecial === 0) {
      parts.push(remaining[0]);
      remaining = remaining.slice(1);
    } else {
      parts.push(remaining.slice(0, nextSpecial));
      remaining = remaining.slice(nextSpecial);
    }
  }

  return parts;
}

const CodeBlock: React.FC<{ code: string; language?: string }> = ({ code, language }) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        margin: '10px 0',
        borderRadius: '10px',
        overflow: 'hidden',
        border: '1px solid #2e283b',
        backgroundColor: '#1b1724',
        color: '#f0ecf6',
        fontSize: '12px',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '6px 12px',
          backgroundColor: '#262033',
          borderBottom: '1px solid #332b44',
          color: '#aba4b6',
          fontSize: '11px',
          fontWeight: 600,
        }}
      >
        <span>{language ? language.toUpperCase() : 'CODE'}</span>
        <button
          onClick={handleCopy}
          type="button"
          style={{
            background: 'transparent',
            border: 'none',
            color: copied ? '#48bb78' : '#c6bfc2',
            cursor: 'pointer',
            fontSize: '11px',
            fontWeight: 650,
          }}
        >
          {copied ? '✓ Copied' : 'Copy'}
        </button>
      </div>
      <pre style={{ margin: 0, padding: '12px 14px', overflowX: 'auto', fontFamily: 'Consolas, Monaco, monospace' }}>
        <code>{code}</code>
      </pre>
    </div>
  );
};

const MarkdownTable: React.FC<{ lines: string[] }> = ({ lines }) => {
  if (lines.length < 2) return null;

  const headerCells = lines[0]
    .split('|')
    .slice(1, -1)
    .map((c) => c.trim());

  const rows = lines.slice(2).map((l) =>
    l
      .split('|')
      .slice(1, -1)
      .map((c) => c.trim())
  );

  return (
    <div style={{ overflowX: 'auto', margin: '12px 0' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: '12.5px',
          border: '1px solid #e7e2ea',
          borderRadius: '8px',
          overflow: 'hidden',
          backgroundColor: '#fff',
        }}
      >
        <thead>
          <tr style={{ backgroundColor: '#f6f1f5', borderBottom: '2px solid #ded5e1' }}>
            {headerCells.map((h, idx) => (
              <th
                key={idx}
                style={{
                  padding: '9px 12px',
                  textAlign: 'left',
                  fontWeight: 750,
                  color: '#2e2837',
                  fontSize: '11.5px',
                  letterSpacing: '0.02em',
                }}
              >
                {renderInline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rIdx) => (
            <tr
              key={rIdx}
              style={{
                borderBottom: rIdx === rows.length - 1 ? 'none' : '1px solid #ede8ef',
                backgroundColor: rIdx % 2 === 0 ? '#ffffff' : '#faf8fb',
              }}
            >
              {row.map((cell, cIdx) => (
                <td key={cIdx} style={{ padding: '8px 12px', color: '#393345' }}>
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

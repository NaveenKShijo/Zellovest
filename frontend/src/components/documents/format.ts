/**
 * Formatting helpers shared by the Document Explorer components
 * (bytes, dates, percentages, and snake_case → Title Case labels).
 */

/** Human-readable byte size (B / KB / MB / GB). */
export function formatFileSize(bytes: number | null | undefined): string {
    if (bytes === null || bytes === undefined) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** Long date + time in the user's locale (e.g. "Nov 1, 2026, 12:04 PM"). */
export function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

/** Confidence as an integer percentage ("94%") or "—" when unknown. */
export function formatConfidence(confidence: number | null | undefined): string {
    if (confidence === null || confidence === undefined) return "—";
    return `${Math.round(confidence * 100)}%`;
}

/** "invoice_number" → "Invoice Number" / "route" stays one word. */
export function humanizeLabel(raw: string | null | undefined): string {
    if (!raw) return "—";
    return raw
        .split(/[_\s]+/)
        .filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
}

/** Bar/bar color by extraction confidence vs the PRD §7 review threshold. */
export function confidenceColor(confidence: number): string {
    if (confidence >= 0.9) return "var(--color-success)";
    if (confidence >= 0.7) return "var(--color-warning)";
    return "var(--color-danger)";
}

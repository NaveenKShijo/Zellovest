'use client';

import { useSyncExternalStore } from 'react';

const REVIEW_HASH = '#review';

function subscribeToHash(callback: () => void): () => void {
    window.addEventListener('hashchange', callback);
    return () => window.removeEventListener('hashchange', callback);
}

function hashRequestsReview(): boolean {
    return window.location.hash === REVIEW_HASH;
}

function serverHashRequestsReview(): boolean {
    return false;
}

/**
 * Whether the explorer's "Review exception" link (`#review`) is active.
 *
 * The hash lives outside React, so `useSyncExternalStore` keeps the drawer
 * state in sync without a `setState` inside an effect. The server snapshot is
 * always `false`, which avoids a hydration mismatch on the detail route.
 */
export function useReviewHashRequest(): boolean {
    return useSyncExternalStore(
        subscribeToHash,
        hashRequestsReview,
        serverHashRequestsReview,
    );
}

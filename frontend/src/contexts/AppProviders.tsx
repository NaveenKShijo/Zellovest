'use client';

import React, { ReactNode } from 'react';
import { AuthProvider } from './AuthContext';
import { LayoutProvider } from './LayoutContext';
import { ToastProvider } from './ToastContext';

/**
 * AppProviders: Composes all global React Contexts in one place.
 * 
 * Hierarchy:
 * 1. AuthProvider: Determines who the active user is.
 * 2. ToastProvider: Allows any child component to trigger alerts & toasts.
 * 3. LayoutProvider: Tracks responsive sidebar state across the shell.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <ToastProvider>
        <LayoutProvider>
          {children}
        </LayoutProvider>
      </ToastProvider>
    </AuthProvider>
  );
}

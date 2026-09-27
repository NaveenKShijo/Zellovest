'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import {
  ToastNotification,
  SystemAlert,
  ToastContextType,
  NotificationType,
} from '@/types';

/**
 * ToastContext: Manages global transient toasts and persistent system alerts.
 * 
 * Provides an event-driven notification API accessible anywhere in the component tree:
 *   const { notify } = useToast();
 *   notify.success("Invoice #INV-23891 extracted with 98% confidence");
 *   notify.error("Variance detected: $4,800 mismatch on Adobe contract");
 */

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastNotification[]>([]);
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);

  // Remove a toast by ID
  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  // Generic internal toast creator
  const addToast = useCallback(
    (
      type: NotificationType,
      title: string,
      message?: string,
      action?: ToastNotification['action'],
      durationMs: number = 4500
    ): string => {
      const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      const newToast: ToastNotification = {
        id,
        type,
        title,
        message,
        durationMs,
        action,
      };

      setToasts((prev) => [newToast, ...prev].slice(0, 5)); // Keep max 5 visible

      // Auto dismiss after durationMs
      if (durationMs > 0) {
        setTimeout(() => {
          removeToast(id);
        }, durationMs);
      }

      return id;
    },
    [removeToast]
  );

  // Semantic notification helpers
  const notify = {
    success: useCallback(
      (title: string, message?: string, action?: ToastNotification['action']) =>
        addToast('success', title, message, action),
      [addToast]
    ),
    error: useCallback(
      (title: string, message?: string, action?: ToastNotification['action']) =>
        addToast('error', title, message, action, 6000), // Errors stay a bit longer
      [addToast]
    ),
    warning: useCallback(
      (title: string, message?: string, action?: ToastNotification['action']) =>
        addToast('warning', title, message, action, 5500),
      [addToast]
    ),
    info: useCallback(
      (title: string, message?: string, action?: ToastNotification['action']) =>
        addToast('info', title, message, action),
      [addToast]
    ),
  };

  // Persistent System Alert Banners
  const addAlert = useCallback((alert: Omit<SystemAlert, 'id' | 'timestamp'>): string => {
    const id = `alert_${Date.now()}`;
    const newAlert: SystemAlert = {
      ...alert,
      id,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };
    setAlerts((prev) => [newAlert, ...prev]);
    return id;
  }, []);

  const dismissAlert = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  return (
    <ToastContext.Provider
      value={{
        toasts,
        alerts,
        notify,
        removeToast,
        addAlert,
        dismissAlert,
      }}
    >
      {children}
    </ToastContext.Provider>
  );
}

/**
 * Custom Hook: useToast()
 * Read toasts/alerts or emit notifications from any button or API handler.
 */
export function useToast(): ToastContextType {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';
import { LayoutContextType } from '@/types';

/**
 * LayoutContext: Manages UI shell layout states across the application.
 * 
 * - Default behavior is EXPANDED (false) permanently.
 * - Clicking sidebar tabs stays expanded with zero auto-shrinking or layout jumping.
 * - Desktop sidebar only collapses when user explicitly clicks the << collapse button.
 */

const LayoutContext = createContext<LayoutContextType | undefined>(undefined);

export function LayoutProvider({ children }: { children: ReactNode }) {
  // Sidebar is permanently EXPANDED (false) by default
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);

  // Mobile drawer open/close state
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);

  const toggleSidebar = () => {
    setIsSidebarCollapsed((prev) => !prev);
  };

  const toggleMobileSidebar = () => {
    setIsMobileSidebarOpen((prev) => !prev);
  };

  const closeMobileSidebar = () => {
    setIsMobileSidebarOpen(false);
  };

  return (
    <LayoutContext.Provider
      value={{
        isSidebarCollapsed,
        isMobileSidebarOpen,
        toggleSidebar,
        setSidebarCollapsed: setIsSidebarCollapsed,
        toggleMobileSidebar,
        closeMobileSidebar,
      }}
    >
      {children}
    </LayoutContext.Provider>
  );
}

export function useLayout(): LayoutContextType {
  const context = useContext(LayoutContext);
  if (!context) {
    throw new Error('useLayout must be used within a LayoutProvider');
  }
  return context;
}

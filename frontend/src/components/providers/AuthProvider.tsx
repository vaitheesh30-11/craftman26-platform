'use client';

import { createContext, useContext, type ReactNode } from 'react';

interface AuthContextValue { isAuthenticated: boolean; }
const AuthContext = createContext<AuthContextValue>({ isAuthenticated: false });

/** Route middleware is the source of truth; this context never exposes an auth token to client code. */
export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  return <AuthContext.Provider value={{ isAuthenticated: true }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue { return useContext(AuthContext); }

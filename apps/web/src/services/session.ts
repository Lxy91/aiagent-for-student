export interface SessionUser {
  id: string;
  email: string;
  displayName: string;
}

export interface StoredSession {
  accessToken: string;
  user: SessionUser;
}

const SESSION_KEY = 'workplace-agent-session';

export function getStoredSession(): StoredSession | null {
  const value = window.localStorage.getItem(SESSION_KEY);
  if (!value) return null;
  try {
    return JSON.parse(value) as StoredSession;
  } catch {
    window.localStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function storeSession(session: StoredSession): void {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearStoredSession(): void {
  window.localStorage.removeItem(SESSION_KEY);
}

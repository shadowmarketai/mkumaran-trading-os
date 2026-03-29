import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import api, { toolsApi } from '../services/api';

interface AuthState {
  token: string | null;
  email: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = 'mkumaran_auth_token';
const EMAIL_KEY = 'mkumaran_auth_email';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: localStorage.getItem(TOKEN_KEY),
    email: localStorage.getItem(EMAIL_KEY),
    isAuthenticated: !!localStorage.getItem(TOKEN_KEY),
    isLoading: true,
  });

  // Set Authorization header whenever token changes
  useEffect(() => {
    if (state.token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${state.token}`;
      toolsApi.defaults.headers.common['Authorization'] = `Bearer ${state.token}`;
    } else {
      delete api.defaults.headers.common['Authorization'];
      delete toolsApi.defaults.headers.common['Authorization'];
    }
  }, [state.token]);

  // Validate token on mount
  useEffect(() => {
    const validateToken = async () => {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) {
        setState((s) => ({ ...s, isLoading: false }));
        return;
      }

      try {
        api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        toolsApi.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        const resp = await api.get('/auth/me');
        // If auth is disabled on server, still treat as authenticated
        if (resp.data.auth_enabled === false) {
          setState({
            token: null,
            email: 'dev@local',
            isAuthenticated: true,
            isLoading: false,
          });
          return;
        }
        setState({
          token,
          email: resp.data.email,
          isAuthenticated: true,
          isLoading: false,
        });
      } catch {
        // Token invalid — clear it
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(EMAIL_KEY);
        delete api.defaults.headers.common['Authorization'];
        delete toolsApi.defaults.headers.common['Authorization'];
        setState({
          token: null,
          email: null,
          isAuthenticated: false,
          isLoading: false,
        });
      }
    };

    validateToken();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await api.post('/auth/login', { email, password });
    const { access_token, email: userEmail } = resp.data;

    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(EMAIL_KEY, userEmail);
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
    toolsApi.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;

    setState({
      token: access_token,
      email: userEmail,
      isAuthenticated: true,
      isLoading: false,
    });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
    delete api.defaults.headers.common['Authorization'];
    delete toolsApi.defaults.headers.common['Authorization'];
    setState({
      token: null,
      email: null,
      isAuthenticated: false,
      isLoading: false,
    });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

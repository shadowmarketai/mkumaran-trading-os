import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ProtectedRoute from '../components/ProtectedRoute';
import * as AuthContext from '../context/AuthContext';

type AuthHookReturn = ReturnType<typeof AuthContext.useAuth>;

function stubAuth(overrides: Partial<AuthHookReturn>): AuthHookReturn {
  return {
    token: null,
    email: null,
    isAuthenticated: false,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  } as AuthHookReturn;
}

function renderWithRouter(initial = '/dashboard') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <div data-testid="dashboard-content">secret</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<div data-testid="login">login page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProtectedRoute', () => {
  it('redirects unauthenticated users to /login', () => {
    vi.spyOn(AuthContext, 'useAuth').mockReturnValue(
      stubAuth({ isAuthenticated: false, isLoading: false })
    );

    renderWithRouter();
    expect(screen.getByTestId('login')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-content')).not.toBeInTheDocument();
  });

  it('shows children when authenticated', () => {
    vi.spyOn(AuthContext, 'useAuth').mockReturnValue(
      stubAuth({
        isAuthenticated: true,
        isLoading: false,
        token: 'fake-jwt',
        email: 'user@test.com',
      })
    );

    renderWithRouter();
    expect(screen.getByTestId('dashboard-content')).toBeInTheDocument();
  });

  it('shows a loading indicator while auth is resolving', () => {
    vi.spyOn(AuthContext, 'useAuth').mockReturnValue(
      stubAuth({ isLoading: true })
    );

    renderWithRouter();
    // Neither redirect target nor the protected content should render yet.
    expect(screen.queryByTestId('login')).not.toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-content')).not.toBeInTheDocument();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});

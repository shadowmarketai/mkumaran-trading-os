# Frontend Skill

> React + TypeScript + Modern UI + API Integration

---

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ui/          # GlassCard, GradientButton, AnimatedInput
│   │   ├── layout/      # PageWrapper, MeshBackground
│   │   └── forms/       # LoginForm, RegisterForm
│   ├── pages/           # Route pages
│   ├── hooks/           # Custom hooks
│   ├── services/        # API client
│   ├── context/         # AuthContext
│   ├── types/           # TypeScript interfaces
│   ├── lib/             # Utils (cn function)
│   └── App.tsx
└── package.json
```

---

## Setup

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install axios react-router-dom @tanstack/react-query framer-motion
npm install @chakra-ui/react @emotion/react @emotion/styled  # OR
npm install tailwindcss clsx tailwind-merge                  # Tailwind
```

---

## API Client

```typescript
// services/api.ts
import axios from 'axios';

const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_URL}/api/v1`,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      error.config._retry = true;
      const refresh = localStorage.getItem('refresh_token');
      const { data } = await axios.post(`${import.meta.env.VITE_API_URL}/api/v1/auth/refresh`, { refresh_token: refresh });
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      return api(error.config);
    }
    return Promise.reject(error);
  }
);

export default api;
```

---

## Auth Context

```typescript
// context/AuthContext.tsx
import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import api from '../services/api';

interface User { id: number; email: string; full_name: string | null; }
interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      api.get('/auth/me').then(r => setUser(r.data)).catch(() => {}).finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const form = new FormData();
    form.append('username', email);
    form.append('password', password);
    const { data } = await api.post('/auth/login', form);
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    const user = await api.get('/auth/me');
    setUser(user.data);
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, isLoading, login, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext)!;
```

---

## Modern UI Components

### GlassCard
```typescript
// components/ui/GlassCard.tsx
import { motion } from 'framer-motion';
import { ReactNode } from 'react';

export function GlassCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.02, y: -5 }}
      className={`p-6 rounded-2xl bg-white/10 backdrop-blur-lg border border-white/20 shadow-xl ${className}`}
    >
      {children}
    </motion.div>
  );
}
```

### GradientButton
```typescript
// components/ui/GradientButton.tsx
import { motion } from 'framer-motion';
import { ButtonHTMLAttributes } from 'react';

export function GradientButton({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <motion.button
      whileHover={{ scale: 1.02, y: -2 }}
      whileTap={{ scale: 0.98 }}
      className="px-6 py-3 rounded-full font-semibold text-white bg-gradient-to-r from-purple-500 to-pink-500 hover:shadow-lg"
      {...props}
    >
      {children}
    </motion.button>
  );
}
```

### PageWrapper
```typescript
// components/layout/PageWrapper.tsx
import { motion } from 'framer-motion';
import { ReactNode } from 'react';

export function PageWrapper({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.3 }}
      className="min-h-screen"
    >
      {children}
    </motion.div>
  );
}
```

### AnimatedList
```typescript
// components/ui/AnimatedList.tsx
import { motion } from 'framer-motion';
import { ReactNode } from 'react';

export function AnimatedList({ children }: { children: ReactNode[] }) {
  return (
    <motion.div initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.1 } } }}>
      {children.map((child, i) => (
        <motion.div key={i} variants={{ hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0 } }}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
}
```

### MeshBackground
```typescript
// components/layout/MeshBackground.tsx
export function MeshBackground() {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-purple-50 via-white to-pink-50" />
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-purple-200 rounded-full blur-3xl opacity-30 animate-pulse" />
      <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-pink-200 rounded-full blur-3xl opacity-30 animate-pulse" />
    </div>
  );
}
```

### AnimatedInput
```typescript
// components/ui/AnimatedInput.tsx
import { motion } from 'framer-motion';
import { InputHTMLAttributes, forwardRef } from 'react';

interface Props extends InputHTMLAttributes<HTMLInputElement> { label?: string; error?: string; }

export const AnimatedInput = forwardRef<HTMLInputElement, Props>(({ label, error, ...props }, ref) => (
  <div>
    {label && <label className="block text-sm font-medium mb-1">{label}</label>}
    <motion.input
      ref={ref}
      whileFocus={{ scale: 1.01 }}
      className={`w-full px-4 py-3 rounded-xl border-2 ${error ? 'border-red-500' : 'border-gray-200'} focus:border-purple-500 outline-none`}
      {...props}
    />
    {error && <p className="text-red-500 text-sm mt-1">{error}</p>}
  </div>
));
```

---

## Protected Route

```typescript
// components/ProtectedRoute.tsx
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <div>Loading...</div>;
  if (!user) return <Navigate to="/login" />;
  return <>{children}</>;
}
```

---

## App Router

```typescript
// App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

---

## React Query Hooks

```typescript
// hooks/useResource.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';

export function useItems(page = 1) {
  return useQuery({ queryKey: ['items', page], queryFn: () => api.get(`/items?page=${page}`).then(r => r.data) });
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => api.post('/items', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['items'] }),
  });
}
```

---

## UI Rules

| Element | Use This Component |
|---------|-------------------|
| All pages | `PageWrapper` |
| Cards | `GlassCard` |
| Primary buttons | `GradientButton` |
| Lists | `AnimatedList` |
| Form inputs | `AnimatedInput` |
| Auth pages | `MeshBackground` |

**Every interactive element must have hover/tap animations.**

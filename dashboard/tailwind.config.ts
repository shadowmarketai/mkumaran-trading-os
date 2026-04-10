import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        trading: {
          // Light SaaS base
          bg: '#FAFBFC',
          'bg-secondary': '#F1F3F9',
          card: '#FFFFFF',
          'card-hover': '#F8F9FC',
          'card-active': '#F0F2F8',
          border: '#E2E8F0',
          'border-light': '#EDF2F7',
          // Bull / Bear
          bull: '#10B981',
          'bull-light': '#34D399',
          'bull-dim': '#ECFDF5',
          'bull-bg': '#F0FDF4',
          bear: '#EF4444',
          'bear-light': '#F87171',
          'bear-dark': '#DC2626',
          'bear-bg': '#FEF2F2',
          // Primary brand — violet
          ai: '#7C3AED',
          'ai-light': '#8B5CF6',
          'ai-glow': '#A78BFA',
          'ai-dim': '#EDE9FE',
          'ai-bg': '#F5F3FF',
          // Info / Cyan
          info: '#0EA5E9',
          'info-light': '#38BDF8',
          'info-dim': '#F0F9FF',
          // Alert / Gold
          alert: '#F59E0B',
          gold: '#EAB308',
          'alert-bg': '#FFFBEB',
          // Accents
          accent: '#3B82F6',
          'accent-light': '#60A5FA',
          cyan: '#06D6A0',
          magenta: '#EC4899',
          indigo: '#6366F1',
          // Brand
          brand: '#7C3AED',
          'brand-light': '#8B5CF6',
          'brand-bg': '#F5F3FF',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'SF Mono', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'card': '0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04)',
        'elevated': '0 8px 24px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)',
        'soft': '0 1px 2px rgba(0,0,0,0.04)',
        'inner-glow': 'inset 0 1px 0 0 rgba(255,255,255,0.8)',
        'brand': '0 4px 14px rgba(124,58,237,0.15)',
        'brand-lg': '0 8px 24px rgba(124,58,237,0.2)',
        'bull': '0 4px 14px rgba(16,185,129,0.12)',
        'bear': '0 4px 14px rgba(239,68,68,0.12)',
      },
      animation: {
        'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in': 'fadeIn 0.5s ease-out',
        'pulse-live': 'pulseLive 2s ease-in-out infinite',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseLive: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;

import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        trading: {
          bg: '#0F172A',
          card: '#1E293B',
          'card-hover': '#334155',
          border: '#334155',
          bull: '#10B981',
          'bull-light': '#84CC16',
          bear: '#F43F5E',
          'bear-dark': '#EF4444',
          info: '#06B6D4',
          'info-light': '#3B82F6',
          alert: '#F59E0B',
          gold: '#EAB308',
          ai: '#8B5CF6',
          'ai-light': '#A78BFA',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-bull': 'pulse-bull 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-bear': 'pulse-bear 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.5s ease-out',
      },
      keyframes: {
        'pulse-bull': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(16, 185, 129, 0.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(16, 185, 129, 0)' },
        },
        'pulse-bear': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(244, 63, 94, 0.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(244, 63, 94, 0)' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;

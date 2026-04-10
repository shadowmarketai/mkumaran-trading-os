import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        trading: {
          bg: '#05080F',
          'bg-secondary': '#0B1121',
          card: '#0E1A2E',
          'card-hover': '#132240',
          'card-active': '#1A2D52',
          border: '#1A2744',
          'border-light': '#253A5C',
          // Vibrant bull/bear
          bull: '#00FF88',
          'bull-light': '#5CFFB1',
          'bull-dim': '#003D21',
          bear: '#FF2D55',
          'bear-light': '#FF6B8A',
          'bear-dark': '#CC0033',
          // Vivid accents
          info: '#00D4FF',
          'info-light': '#5CE1FF',
          'info-dim': '#003D4D',
          alert: '#FFB800',
          gold: '#FFD426',
          // AI purple — more vivid
          ai: '#8B5CF6',
          'ai-light': '#A78BFA',
          'ai-glow': '#C084FC',
          'ai-dim': '#2E1065',
          // New accent colors
          accent: '#3B82F6',
          'accent-light': '#60A5FA',
          cyan: '#06D6A0',
          magenta: '#F72585',
          indigo: '#6366F1',
          // SaaS branding
          brand: '#8B5CF6',
          'brand-light': '#C084FC',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'SF Mono', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'glow-bull': 'radial-gradient(ellipse at center, rgba(0,255,136,0.12) 0%, transparent 70%)',
        'glow-bear': 'radial-gradient(ellipse at center, rgba(255,45,85,0.12) 0%, transparent 70%)',
        'glow-ai': 'radial-gradient(ellipse at center, rgba(139,92,246,0.15) 0%, transparent 70%)',
        'mesh-gradient': 'radial-gradient(at 0% 0%, rgba(139,92,246,0.08) 0%, transparent 50%), radial-gradient(at 100% 100%, rgba(0,255,136,0.04) 0%, transparent 50%)',
        'hero-gradient': 'linear-gradient(135deg, rgba(139,92,246,0.15) 0%, rgba(59,130,246,0.08) 50%, rgba(0,255,136,0.05) 100%)',
        'card-gradient': 'linear-gradient(135deg, rgba(14,26,46,0.95) 0%, rgba(11,17,33,0.98) 100%)',
        'sidebar-gradient': 'linear-gradient(180deg, rgba(11,17,33,1) 0%, rgba(5,8,15,1) 100%)',
        'vibrant-mesh': 'radial-gradient(at 20% 20%, rgba(139,92,246,0.12) 0%, transparent 50%), radial-gradient(at 80% 80%, rgba(0,255,136,0.06) 0%, transparent 50%), radial-gradient(at 50% 0%, rgba(59,130,246,0.08) 0%, transparent 60%)',
      },
      boxShadow: {
        'glow-bull': '0 0 24px rgba(0,255,136,0.2), 0 0 80px rgba(0,255,136,0.06)',
        'glow-bear': '0 0 24px rgba(255,45,85,0.2), 0 0 80px rgba(255,45,85,0.06)',
        'glow-ai': '0 0 24px rgba(139,92,246,0.25), 0 0 80px rgba(139,92,246,0.1)',
        'glow-info': '0 0 24px rgba(0,212,255,0.2), 0 0 80px rgba(0,212,255,0.06)',
        'glow-brand': '0 0 32px rgba(139,92,246,0.3), 0 0 100px rgba(139,92,246,0.1)',
        'card': '0 4px 24px -4px rgba(0,0,0,0.5), 0 0 0 1px rgba(26,39,68,0.5)',
        'card-hover': '0 8px 40px -4px rgba(0,0,0,0.6), 0 0 0 1px rgba(37,58,92,0.7)',
        'elevated': '0 20px 60px -12px rgba(0,0,0,0.7)',
        'inner-glow': 'inset 0 1px 0 0 rgba(255,255,255,0.06)',
        'neon-bull': '0 0 5px rgba(0,255,136,0.4), 0 0 20px rgba(0,255,136,0.15)',
        'neon-bear': '0 0 5px rgba(255,45,85,0.4), 0 0 20px rgba(255,45,85,0.15)',
        'neon-ai': '0 0 5px rgba(139,92,246,0.5), 0 0 20px rgba(139,92,246,0.2)',
      },
      animation: {
        'pulse-bull': 'pulseBull 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-bear': 'pulseBear 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-live': 'pulseLive 2s ease-in-out infinite',
        'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-down': 'slideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in': 'fadeIn 0.5s ease-out',
        'shimmer': 'shimmer 2.5s linear infinite',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
        'gradient-shift': 'gradientShift 8s ease-in-out infinite',
      },
      keyframes: {
        pulseBull: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0,255,136,0.4)' },
          '50%': { boxShadow: '0 0 0 10px rgba(0,255,136,0)' },
        },
        pulseBear: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255,45,85,0.4)' },
          '50%': { boxShadow: '0 0 0 10px rgba(255,45,85,0)' },
        },
        pulseLive: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
        slideUp: {
          '0%': { transform: 'translateY(16px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
        gradientShift: {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
    },
  },
  plugins: [],
} satisfies Config;

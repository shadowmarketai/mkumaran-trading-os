import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

type GlowColor = 'bull' | 'bear' | 'ai' | 'alert' | 'info';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  glowColor?: GlowColor;
  animate?: boolean;
  hover?: boolean;
}

const glowStyles: Record<GlowColor, string> = {
  bull: 'shadow-bull border-trading-bull/20',
  bear: 'shadow-bear border-trading-bear/20',
  ai: 'shadow-brand border-trading-ai/20',
  alert: 'border-trading-alert/20 shadow-[0_4px_14px_rgba(245,158,11,0.08)]',
  info: 'glow-info border-trading-info/20',
};

export default function GlassCard({ children, className, glowColor, animate = true, hover = false }: GlassCardProps) {
  const Component = animate ? motion.div : 'div';
  const animationProps = animate
    ? {
        initial: { opacity: 0, y: 8 } as const,
        animate: { opacity: 1, y: 0 } as const,
        transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] } as const,
      }
    : {};

  return (
    <Component
      className={cn(
        hover ? 'glass-card-hover' : 'glass-card',
        'p-5',
        glowColor && glowStyles[glowColor],
        className
      )}
      {...animationProps}
    >
      {children}
    </Component>
  );
}

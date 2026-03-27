import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

type GlowColor = 'bull' | 'bear' | 'ai' | 'alert' | 'info';

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  glowColor?: GlowColor;
  animate?: boolean;
}

const glowStyles: Record<GlowColor, string> = {
  bull: 'glow-bull border-trading-bull/20',
  bear: 'glow-bear border-trading-bear/20',
  ai: 'glow-ai border-trading-ai/20',
  alert: 'border-trading-alert/20 shadow-[0_0_20px_rgba(245,158,11,0.1)]',
  info: 'border-trading-info/20 shadow-[0_0_20px_rgba(6,182,212,0.1)]',
};

export default function GlassCard({ children, className, glowColor, animate = true }: GlassCardProps) {
  const Component = animate ? motion.div : 'div';
  const animationProps = animate
    ? {
        initial: { opacity: 0, y: 10 } as const,
        animate: { opacity: 1, y: 0 } as const,
        transition: { duration: 0.3 } as const,
      }
    : {};

  return (
    <Component
      className={cn(
        'glass-card p-5',
        glowColor && glowStyles[glowColor],
        className
      )}
      {...animationProps}
    >
      {children}
    </Component>
  );
}

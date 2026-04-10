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
  bull: 'glow-bull border-trading-bull/20',
  bear: 'glow-bear border-trading-bear/20',
  ai: 'glow-ai border-trading-ai/25',
  alert: 'border-trading-alert/15 shadow-[0_0_24px_rgba(255,171,0,0.08)]',
  info: 'glow-info border-trading-info/15',
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

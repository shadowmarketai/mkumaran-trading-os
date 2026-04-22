import { useEffect, useRef, type ReactNode } from 'react';
import { gsap, ScrollTrigger } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

interface ParallaxProps {
  /** Speed multiplier: 0.3-0.6 distant, 1.0 normal, 1.1-1.3 foreground */
  speed?: number;
  children: ReactNode;
  className?: string;
}

/**
 * Wraps children in a parallax transform driven by scroll position.
 * Speed < 1 moves slower than scroll (distant feel).
 * Speed > 1 moves faster than scroll (foreground feel).
 * Speed = 1 is neutral (no parallax).
 */
export default function Parallax({ speed = 0.8, children, className = '' }: ParallaxProps) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced || speed === 1) return;
    const el = ref.current;
    if (!el) return;

    const tween = gsap.to(el, {
      y: () => (1 - speed) * ScrollTrigger.maxScroll(window),
      ease: 'none',
      scrollTrigger: {
        start: 0,
        end: 'max',
        invalidateOnRefresh: true,
        scrub: 0,
      },
    });

    return () => {
      tween.scrollTrigger?.kill();
      tween.kill();
    };
  }, [speed, reduced]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

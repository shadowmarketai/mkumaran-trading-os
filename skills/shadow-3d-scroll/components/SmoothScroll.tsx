import { useEffect, type ReactNode } from 'react';
import Lenis from 'lenis';
import { gsap, ScrollTrigger } from './lib/gsapSetup';

interface SmoothScrollProps {
  children: ReactNode;
  /** Lenis duration. 1.2 = premium default, 1.5 = gallery/slow, 0.8 = snappy */
  duration?: number;
}

/**
 * Wraps marketing routes with Lenis smooth scroll + GSAP ScrollTrigger bridge.
 *
 * CRITICAL: Only use on marketing/public routes. Do NOT wrap dashboard routes —
 * Lenis will break modals, fixed sidebars, and scrollable data tables.
 *
 * Usage:
 *   <Route element={<MarketingLayout />}>
 *     where MarketingLayout = <SmoothScroll><Outlet /></SmoothScroll>
 */
export default function SmoothScroll({ children, duration = 1.2 }: SmoothScrollProps) {
  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) return;

    const lenis = new Lenis({
      duration,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      // NEVER true — breaks native mobile inertia
      smoothTouch: false,
    });

    lenis.on('scroll', ScrollTrigger.update);

    const raf = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);

    // Refresh after fonts to avoid pin miscalc
    document.fonts.ready.then(() => ScrollTrigger.refresh());

    return () => {
      lenis.destroy();
      gsap.ticker.remove(raf);
      ScrollTrigger.getAll().forEach((t) => t.kill());
    };
  }, [duration]);

  return <>{children}</>;
}

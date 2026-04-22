import { useEffect, useRef, type ReactNode } from 'react';
import { gsap, ScrollTrigger } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

interface HorizontalScrollProps {
  children: ReactNode;
  /** Called with scroll progress 0-1 — useful for external progress bars */
  onProgress?: (progress: number) => void;
  className?: string;
}

/**
 * Pinned horizontal scroll.
 *
 * Children should be a series of panels, each sized to 100vw (use
 * `HorizontalPanel` as a sibling helper or apply `flex-[0_0_100vw] h-screen`
 * to your own panels).
 *
 * On mobile (<768px) the pinning is disabled and panels stack vertically.
 */
export default function HorizontalScroll({
  children,
  onProgress,
  className = '',
}: HorizontalScrollProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const section = sectionRef.current;
    const track = trackRef.current;
    if (!section || !track) return;

    const mm = ScrollTrigger.matchMedia({
      '(min-width: 768px)': () => {
        const tween = gsap.to(track, {
          x: () => -(track.scrollWidth - window.innerWidth),
          ease: 'none',
          scrollTrigger: {
            trigger: section,
            start: 'top top',
            end: () => `+=${track.scrollWidth - window.innerWidth}`,
            pin: true,
            scrub: 1,
            invalidateOnRefresh: true,
            anticipatePin: 1,
            onUpdate: (self) => onProgress?.(self.progress),
          },
        });

        return () => {
          tween.scrollTrigger?.kill();
          tween.kill();
        };
      },
    });

    return () => mm.revert();
  }, [onProgress, reduced]);

  if (reduced) {
    return (
      <section className={className}>
        <div className="flex flex-col md:flex-row md:overflow-x-auto">{children}</div>
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      className={`h-screen overflow-hidden relative md:block max-md:h-auto ${className}`}
    >
      <div
        ref={trackRef}
        className="flex h-full w-max max-md:flex-col max-md:w-full max-md:h-auto"
      >
        {children}
      </div>
    </section>
  );
}

interface HorizontalPanelProps {
  children: ReactNode;
  className?: string;
}

/** Helper panel — one per "slide" in a HorizontalScroll */
export function HorizontalPanel({ children, className = '' }: HorizontalPanelProps) {
  return (
    <article
      className={`flex-[0_0_100vw] h-screen flex flex-col justify-center p-[8vw] relative max-md:flex-none max-md:w-full max-md:min-h-screen ${className}`}
    >
      {children}
    </article>
  );
}

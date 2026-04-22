import { useEffect, useRef, type ReactNode } from 'react';
import { gsap, ScrollTrigger } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

interface StackedCardsProps {
  children: ReactNode;
  className?: string;
}

/**
 * Sticky stacked card reveal.
 *
 * Children must be `<StackedCard>` elements (or any elements that will each
 * fill a viewport). As the user scrolls, each card sticks to the top and the
 * previous card scales down + darkens — creating a physical "deck" feel.
 *
 * Max recommended children: 6. Beyond that the user loses orientation.
 */
export default function StackedCards({ children, className = '' }: StackedCardsProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const section = sectionRef.current;
    if (!section) return;

    const cards = Array.from(section.querySelectorAll<HTMLElement>('[data-stack-card]'));
    if (cards.length < 2) return;

    const ctx = gsap.context(() => {
      cards.forEach((card, i) => {
        if (i === cards.length - 1) return;
        gsap.to(card, {
          scale: 0.92,
          filter: 'brightness(0.55)',
          borderRadius: '32px',
          y: 40,
          rotationX: -4,
          scrollTrigger: {
            trigger: cards[i + 1],
            start: 'top bottom',
            end: 'top top',
            scrub: 1,
          },
        });
      });
    }, section);

    return () => ctx.revert();
  }, [reduced]);

  return (
    <section
      ref={sectionRef}
      className={`[perspective:1200px] ${className}`}
    >
      {children}
    </section>
  );
}

interface StackedCardProps {
  children: ReactNode;
  /** Background color — required, must differ between adjacent cards */
  background: string;
  /** Text color class, e.g. "text-neutral-100" */
  textColor?: string;
  className?: string;
}

export function StackedCard({
  children,
  background,
  textColor = 'text-neutral-100',
  className = '',
}: StackedCardProps) {
  return (
    <article
      data-stack-card
      style={{ background }}
      className={`sticky top-0 h-screen px-[8vw] py-[10vh] flex flex-col justify-between will-change-[transform,filter] origin-[center_top] ${textColor} ${className}`}
    >
      {children}
    </article>
  );
}

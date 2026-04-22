import { useEffect, useRef, type ReactNode } from 'react';
import SplitType from 'split-type';
import { gsap } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

type RevealVariant = 'chars-3d' | 'mask-up' | 'scroll-typed' | 'editorial';

interface SplitTextRevealProps {
  as?: 'h1' | 'h2' | 'h3' | 'p';
  variant?: RevealVariant;
  children: ReactNode;
  className?: string;
  /** Start position for the scroll trigger. Default 'top 80%' */
  start?: string;
}

/**
 * Scroll-driven text reveal using SplitType.
 *
 * Variants:
 *   - chars-3d: letter fade-up with 3D perspective tilt (Lusion headline)
 *   - mask-up: each line slides up from behind an overflow mask (editorial)
 *   - scroll-typed: each word fades in as scroll position crosses it
 *   - editorial: no split — stacked spans with staggered reveal (Obsidian style)
 */
export default function SplitTextReveal({
  as = 'h2',
  variant = 'chars-3d',
  children,
  className = '',
  start = 'top 80%',
}: SplitTextRevealProps) {
  const ref = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;

    // Wait for fonts before splitting
    let split: SplitType | null = null;
    let cleanup: (() => void) | null = null;

    document.fonts.ready.then(() => {
      if (!el) return;

      if (variant === 'chars-3d') {
        split = new SplitType(el, { types: 'chars,words' });
        const anim = gsap.from(split.chars, {
          y: 100,
          opacity: 0,
          rotationX: -90,
          duration: 0.9,
          ease: 'power4.out',
          stagger: 0.015,
          scrollTrigger: { trigger: el, start, toggleActions: 'play none none reverse' },
        });
        cleanup = () => {
          anim.scrollTrigger?.kill();
          anim.kill();
          split?.revert();
        };
      } else if (variant === 'mask-up') {
        split = new SplitType(el, { types: 'lines,words' });
        el.querySelectorAll('.line').forEach((l) => {
          (l as HTMLElement).style.overflow = 'hidden';
        });
        const anim = gsap.from(split.words, {
          yPercent: 110,
          duration: 1.2,
          ease: 'power4.out',
          stagger: 0.02,
          scrollTrigger: { trigger: el, start },
        });
        cleanup = () => {
          anim.scrollTrigger?.kill();
          anim.kill();
          split?.revert();
        };
      } else if (variant === 'scroll-typed') {
        split = new SplitType(el, { types: 'words' });
        gsap.set(split.words, { opacity: 0.15 });
        const triggers = split.words!.map((word) =>
          gsap.to(word, {
            opacity: 1,
            scrollTrigger: { trigger: word, start: 'top 75%', end: 'top 45%', scrub: true },
          })
        );
        cleanup = () => {
          triggers.forEach((t) => {
            t.scrollTrigger?.kill();
            t.kill();
          });
          split?.revert();
        };
      } else if (variant === 'editorial') {
        // Don't split — animate direct children <span>s
        const spans = el.querySelectorAll(':scope > span');
        const anim = gsap.from(spans, {
          opacity: 0,
          y: 40,
          duration: 1.2,
          ease: 'power3.out',
          stagger: 0.15,
          scrollTrigger: { trigger: el, start, toggleActions: 'play none none reverse' },
        });
        cleanup = () => {
          anim.scrollTrigger?.kill();
          anim.kill();
        };
      }
    });

    return () => {
      cleanup?.();
    };
  }, [variant, start, reduced]);

  const Tag = as as keyof JSX.IntrinsicElements;
  // perspective needed for chars-3d
  const perspectiveClass = variant === 'chars-3d' ? '[perspective:1000px]' : '';

  return (
    <Tag
      ref={ref as React.Ref<HTMLElement>}
      className={`${perspectiveClass} ${className}`}
    >
      {children}
    </Tag>
  );
}

# Pattern 01 — Smooth Scroll Foundation (Lenis + GSAP bridge)

**This is the base layer for every other pattern.** Every scroll-driven animation in this skill assumes Lenis is running and its RAF loop is bridged to GSAP's ticker. Without the bridge, you get dual-RAF jitter where the scroll position and the animation are off by one frame.

## Vanilla HTML/JS

```html
<!-- In <head> -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>
<script src="https://unpkg.com/lenis@1.1.14/dist/lenis.min.js"></script>

<script>
  // Wait for DOM
  document.addEventListener('DOMContentLoaded', () => {
    gsap.registerPlugin(ScrollTrigger);

    // 1. Init Lenis
    const lenis = new Lenis({
      duration: 1.2,             // 1.2s feels premium; 0.8 is snappier
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // expo out
      smoothWheel: true,
      smoothTouch: false,        // NEVER true on mobile — it breaks native inertia
      touchMultiplier: 2,
    });

    // 2. Bridge Lenis → ScrollTrigger (THIS IS THE CRITICAL LINE)
    lenis.on('scroll', ScrollTrigger.update);

    // 3. Drive Lenis with GSAP's ticker (single RAF loop)
    gsap.ticker.add((time) => { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);

    // 4. Respect reduced motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      lenis.destroy();
    }

    // Expose globally if other scripts need it
    window.lenis = lenis;
  });
</script>
```

## React (Next.js / Vite)

```bash
npm i lenis gsap
```

```jsx
// app/providers/SmoothScroll.jsx
'use client';
import { useEffect } from 'react';
import Lenis from 'lenis';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export default function SmoothScroll({ children }) {
  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) return;

    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
      smoothTouch: false,
    });

    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((time) => lenis.raf(time * 1000));
    gsap.ticker.lagSmoothing(0);

    return () => {
      lenis.destroy();
      gsap.ticker.remove((time) => lenis.raf(time * 1000));
    };
  }, []);

  return children;
}
```

Wrap your layout: `<SmoothScroll>{children}</SmoothScroll>`.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Scroll jitters / double-RAF | Lenis not bridged to ScrollTrigger | Add `lenis.on('scroll', ScrollTrigger.update)` |
| Pinned section jumps on load | ScrollTrigger measured before fonts loaded | Call `ScrollTrigger.refresh()` after `document.fonts.ready` |
| Mobile scroll feels broken | `smoothTouch: true` | Always `smoothTouch: false` |
| Anchor links don't work | Native scroll hijacked | Use `lenis.scrollTo('#section')` instead of `href="#section"` |
| Horizontal scroll inside pinned section fights Lenis | Lenis intercepts wheel | Add `data-lenis-prevent` to the inner scroller |

## Tuning duration

- `0.8` — snappy, app-like (use for dashboards)
- `1.2` — premium default (use for marketing sites)
- `1.5` — cinematic, slow (use for portfolios / gallery sites like obsidianassembly.com)
- `2.0+` — usually too slow, users feel lag

## When to skip Lenis

Skip Lenis and use native scroll when:
- The page has `position: fixed` elements that must track scroll precisely (iOS Safari edge case)
- The user has `prefers-reduced-motion: reduce` set
- The site is primarily a form/input-heavy app (dashboards, admin panels)
- Viewport is below 768px AND you want to preserve native iOS momentum

# Pattern 08 — Multi-Layer Parallax With Depth

The foundational "things move at different speeds" effect. Used everywhere on both reference sites as the connective tissue between bigger effects. Done wrong, it feels dated (early-2010s Apple knockoff). Done right, it's invisible — the user just feels that the page has depth.

## The two parallax philosophies

### Philosophy 1: `data-speed` (GSAP official pattern)

Tag every parallax element with a speed multiplier. GSAP handles the rest.

```html
<div data-speed="0.5">Background layer (moves slow)</div>
<div data-speed="1">Normal layer (moves at scroll speed)</div>
<div data-speed="1.5">Foreground layer (moves fast, creates depth)</div>
```

```js
gsap.utils.toArray('[data-speed]').forEach((el) => {
  const speed = parseFloat(el.dataset.speed);
  
  gsap.to(el, {
    y: () => (1 - speed) * ScrollTrigger.maxScroll(window),
    ease: 'none',
    scrollTrigger: {
      start: 0,
      end: 'max',
      invalidateOnRefresh: true,
      scrub: 0,
    }
  });
});
```

**Speed rules of thumb:**
- `0.3–0.6` — distant backgrounds (sky, blurred photography)
- `0.7–0.9` — mid-ground (section imagery)
- `1.0` — normal (text, standard content)
- `1.1–1.3` — foreground (feels like it's floating toward you)
- `>1.5` — rarely looks good; feels jumpy

### Philosophy 2: per-element ScrollTrigger (more control)

When you need different parallax behavior per section rather than globally:

```js
gsap.to('.hero-bg-img', {
  y: '30%',
  ease: 'none',
  scrollTrigger: {
    trigger: '.hero',
    start: 'top top',
    end: 'bottom top',
    scrub: 1,
  }
});
```

Use this when parallax should only fire within a specific section, or when you want different easing/scrub values.

## The 3D depth upgrade (CSS perspective)

True parallax = multiple Z-layers. Create it with `transform-style: preserve-3d` and `translateZ`:

```css
.parallax-scene {
  perspective: 1px;
  perspective-origin: center center;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
  transform-style: preserve-3d;
}

.parallax-layer {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
}

.parallax-layer--back  { transform: translateZ(-2px) scale(3); }
.parallax-layer--mid   { transform: translateZ(-1px) scale(2); }
.parallax-layer--front { transform: translateZ(0); }
```

This is pure CSS parallax — no JS, runs at 60fps on mobile. Scale values must equal `(distance + 1)` to compensate for perspective shrinking.

**Limitation:** doesn't play well with `position: fixed`, Lenis smooth scroll, or modals. Use for self-contained sections only.

## Mouse-driven parallax (the polish touch)

In addition to scroll, add subtle mouse-move parallax to hero sections. Elements drift toward the cursor.

```js
const heroElements = document.querySelectorAll('.hero [data-mouse-speed]');

document.addEventListener('mousemove', (e) => {
  const x = (e.clientX / window.innerWidth - 0.5) * 2;  // -1 to 1
  const y = (e.clientY / window.innerHeight - 0.5) * 2;
  
  heroElements.forEach((el) => {
    const speed = parseFloat(el.dataset.mouseSpeed);
    gsap.to(el, {
      x: x * 20 * speed,
      y: y * 20 * speed,
      duration: 0.8,
      ease: 'power2.out',
    });
  });
});
```

```html
<div class="hero">
  <img data-mouse-speed="0.3" src="bg.jpg" />        <!-- barely moves -->
  <h1 data-mouse-speed="0.8">Headline</h1>            <!-- noticeable drift -->
  <div data-mouse-speed="1.2" class="glow"></div>    <!-- leads the cursor -->
</div>
```

Disable on touch devices:

```js
if (!('ontouchstart' in window)) {
  // mousemove code here
}
```

## Parallax + 3D Three.js hero

If your hero already has a Three.js canvas (Pattern 02), the 3D scene *is* the parallax — camera movement provides real depth. Don't add CSS parallax on top, it fights the 3D.

But you *can* add parallax to overlay UI (copy, CTA buttons) that sit on top of the canvas:

```js
gsap.to('.hero-copy', {
  y: -100,
  opacity: 0,
  scrollTrigger: {
    trigger: '.hero',
    start: 'top top',
    end: 'bottom top',
    scrub: 1,
  }
});
```

## Do / Don't

| Do | Don't |
|---|---|
| Use `ease: 'none'` with `scrub` | Use `ease: 'power2.out'` with scrub (feels laggy) |
| Keep speed differences subtle (0.7 to 1.2 range) | Use extreme speeds (0.1 or 2.0) — feels like broken page |
| `transform: translateY()` only | `margin-top` or `top` (triggers layout, not GPU) |
| Use `will-change: transform` on parallax elements | Leave `will-change` on after animation — hurts performance |
| Test on a 75Hz and 60Hz monitor | Only test on one refresh rate |

## The "mask reveal" advanced trick

A hybrid of parallax + clipping. Background image stays still while a foreground mask scrolls up to reveal it. Used in premium magazine sites.

```css
.reveal-section {
  position: relative;
  height: 200vh;
  overflow: hidden;
}
.reveal-section__bg {
  position: sticky;
  top: 0;
  height: 100vh;
  background: url('/photo.jpg') center / cover;
}
.reveal-section__mask {
  position: absolute;
  inset: 0;
  background: var(--page-bg);
  clip-path: inset(0 0 0 0);
}
```

```js
gsap.to('.reveal-section__mask', {
  clipPath: 'inset(100% 0 0 0)',  // mask slides up
  ease: 'none',
  scrollTrigger: {
    trigger: '.reveal-section',
    start: 'top top',
    end: 'center top',
    scrub: 1,
  }
});
```

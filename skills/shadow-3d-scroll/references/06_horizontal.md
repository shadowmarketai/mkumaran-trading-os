# Pattern 06 — Horizontal Pinned Scroll

A section that pins vertically, then the user's vertical scroll translates horizontal content. Used on oryzo.ai for the product tier comparison (ORYZO / ORYZO Pro / ORYZO Pro Max).

## The structure

```html
<section class="h-scroll">
  <div class="h-scroll__track">
    <div class="h-scroll__panel">Panel 1</div>
    <div class="h-scroll__panel">Panel 2</div>
    <div class="h-scroll__panel">Panel 3</div>
    <div class="h-scroll__panel">Panel 4</div>
  </div>
</section>
```

```css
.h-scroll { 
  height: 100vh; 
  overflow: hidden; 
}
.h-scroll__track {
  display: flex;
  height: 100%;
  width: max-content;     /* auto-sizes to panel count */
}
.h-scroll__panel {
  flex: 0 0 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
```

## The animation

```js
const track = document.querySelector('.h-scroll__track');
const panels = gsap.utils.toArray('.h-scroll__panel');

gsap.to(track, {
  x: () => -(track.scrollWidth - window.innerWidth),
  ease: 'none',
  scrollTrigger: {
    trigger: '.h-scroll',
    start: 'top top',
    end: () => `+=${track.scrollWidth - window.innerWidth}`,
    pin: true,
    scrub: 1,
    invalidateOnRefresh: true,  // recompute on resize
    anticipatePin: 1,
  }
});
```

**Critical detail:** `end` must equal the width of the track minus one viewport. This makes 1px of vertical scroll = 1px of horizontal translation. Any other value feels off.

## Per-panel scroll triggers

Often you want things to happen *inside* each panel as it crosses the viewport center. This is trickier because the panels are moving, not the user.

```js
panels.forEach((panel, i) => {
  const heading = panel.querySelector('h2');
  
  gsap.from(heading, {
    y: 100,
    opacity: 0,
    scrollTrigger: {
      trigger: panel,
      containerAnimation: gsap.getTweensOf(track)[0], // << key line
      start: 'left 80%',
      end: 'left 20%',
      scrub: 1,
    }
  });
});
```

`containerAnimation` tells ScrollTrigger that the panel is moving via another animation, not scrolled directly. Without this, the per-panel triggers never fire.

## Variants

### Snap to each panel
Add `snap: 1 / (panels.length - 1)` to the main ScrollTrigger.

```js
scrollTrigger: {
  // ...existing options
  snap: {
    snapTo: 1 / (panels.length - 1),
    duration: 0.5,
    ease: 'power2.inOut',
  }
}
```

### Last panel is taller (call-to-action)
Make the final panel `flex: 0 0 150vw` or similar. Don't change the structure — GSAP handles variable widths automatically when you use `track.scrollWidth`.

### Fade-in product cards as they enter
```js
panels.forEach((panel) => {
  gsap.from(panel.querySelector('.card'), {
    scale: 0.8,
    opacity: 0,
    scrollTrigger: {
      trigger: panel,
      containerAnimation: gsap.getTweensOf(track)[0],
      start: 'left center',
      toggleActions: 'play none none reverse',
    }
  });
});
```

## Mobile fallback

Horizontal scroll often feels wrong on mobile (users expect to scroll down). Use `matchMedia` to disable:

```js
ScrollTrigger.matchMedia({
  '(min-width: 768px)': () => {
    // horizontal scroll code here
  },
  '(max-width: 767px)': () => {
    // on mobile, just let panels stack vertically
    gsap.set('.h-scroll__track', { display: 'block' });
    gsap.set('.h-scroll__panel', { width: '100%', height: 'auto' });
  }
});
```

## Common bugs

| Bug | Cause | Fix |
|---|---|---|
| Panels overlap on first load | ScrollTrigger measured before images loaded | `ScrollTrigger.refresh()` after `window.onload` |
| Scroll feels "too fast" | `end` value too small | Set `end: () => '+=' + (track.scrollWidth - window.innerWidth)` — don't hardcode pixels |
| Pin releases early | Other ScrollTriggers below using same trigger | Use unique trigger elements per pin |
| Flicker at pin start | `anticipatePin` not set | Add `anticipatePin: 1` |
| Resize breaks layout | Positions cached at init | Add `invalidateOnRefresh: true` |

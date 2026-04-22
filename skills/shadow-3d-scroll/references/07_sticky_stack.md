# Pattern 07 — Sticky Stacked Card Reveal

Cards that stack on top of each other as the user scrolls — each new card arrives, pins in place, and the previous one slightly scales/darkens as it gets buried under the new one. Used by Apple, Linear, obsidianassembly.com's objects section.

## The core idea

Every card gets `position: sticky; top: 0`. As the user scrolls, each card sticks to the top of the viewport while the next card scrolls up over it. The visual effect is cards layering on top of each other.

## Minimal CSS-only version (no JS required for the sticking)

```html
<section class="stack">
  <div class="stack__card" data-index="0">
    <h2>Origin Objects</h2>
    <p>These items are formed within the places themselves.</p>
  </div>
  <div class="stack__card" data-index="1">
    <h2>Connection</h2>
    <p>The Item Shown at Point of Origin.</p>
  </div>
  <div class="stack__card" data-index="2">
    <h2>Updates Now Forming</h2>
    <p>Work continues. Conditions are being refined prior to use.</p>
  </div>
</section>
```

```css
.stack {
  /* no height needed — auto from children */
}
.stack__card {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  align-items: center;
  padding: 10vw;
  /* unique backgrounds per card */
}
.stack__card:nth-child(1) { background: #1a1a1a; color: #fff; }
.stack__card:nth-child(2) { background: #f5efe0; color: #1a1a1a; }
.stack__card:nth-child(3) { background: #2e4033; color: #fff; }
```

That's it — already works as a basic stack. Now add the premium layer.

## Premium layer: scale + darken the card beneath

```js
const cards = gsap.utils.toArray('.stack__card');

cards.forEach((card, i) => {
  if (i === cards.length - 1) return; // last card doesn't scale
  
  gsap.to(card, {
    scale: 0.92,
    filter: 'brightness(0.5)',
    borderRadius: '24px',
    scrollTrigger: {
      trigger: cards[i + 1],   // when the NEXT card enters
      start: 'top bottom',
      end: 'top top',
      scrub: 1,
    }
  });
});
```

Now as each new card scrolls in, the previous one scales down to 92% and darkens to 50% brightness. Subtle, but this is *the* move that makes stacked sections feel premium.

## Variant A: Rounded corners emerge as cards stack

```css
.stack__card {
  position: sticky;
  top: 0;
  height: 100vh;
  border-radius: 0;
  transition: border-radius 0.3s;
}
```

The GSAP above already animates `borderRadius: '24px'` — combined with the scale, the cards look like they're tucking under each other like a physical deck.

## Variant B: Subtle parallax on card contents

The card sticks, but its *inner content* moves slightly faster than scroll to create depth:

```js
cards.forEach((card) => {
  const content = card.querySelector('.stack__content');
  
  gsap.fromTo(content, 
    { y: 50 }, 
    {
      y: -50,
      ease: 'none',
      scrollTrigger: {
        trigger: card,
        start: 'top bottom',
        end: 'bottom top',
        scrub: 1,
      }
    }
  );
});
```

## Variant C: 3D tilt during transition

When card N+1 arrives, card N tilts backward like it's being pushed down. Requires `perspective` on parent.

```css
.stack { perspective: 1200px; }
```

```js
cards.forEach((card, i) => {
  if (i === cards.length - 1) return;
  
  gsap.to(card, {
    rotationX: -15,    // tilts back
    scale: 0.9,
    y: 50,
    transformOrigin: 'center top',
    scrollTrigger: {
      trigger: cards[i + 1],
      start: 'top bottom',
      end: 'top top',
      scrub: 1,
    }
  });
});
```

## Variant D: Horizontal "deck" (cards slide in from side)

Combine with Pattern 06 (horizontal scroll). Each horizontal panel has its own stacked cards.

## Don't

- Don't put more than 6 cards in a single stack. The user loses orientation.
- Don't make the scale change too dramatic (below 0.8). It looks like a bug.
- Don't forget to set a unique background per card — if two adjacent cards share a color, the user can't tell a new card has arrived.
- Don't use `position: fixed` instead of `position: sticky`. `sticky` is the whole point — it releases naturally at the end of the section.

## Accessibility

Users with `prefers-reduced-motion` should see cards simply stacked vertically with no transforms. The `position: sticky` behavior is fine — it's the scale/rotate that's motion-sensitive.

```css
@media (prefers-reduced-motion: reduce) {
  .stack__card {
    transform: none !important;
    filter: none !important;
  }
}
```

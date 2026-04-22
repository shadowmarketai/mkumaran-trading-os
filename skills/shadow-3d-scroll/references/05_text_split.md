# Pattern 05 — Fragmented Text Reveal (SplitType)

Text that reveals character-by-character, word-by-word, or line-by-line on scroll. Used by both reference sites. The Obsidian Assembly takes it further — *words are broken across lines at unexpected places* to create editorial tension.

## The tool

**SplitType** by Luke Haas splits a string into wrappable spans so you can animate each unit independently. It's the modern replacement for the old GSAP `SplitText` (which is now a Club GreenSock paid plugin).

```html
<script src="https://unpkg.com/split-type"></script>
```

Or for ES modules:

```bash
npm i split-type
```

```js
import SplitType from 'split-type';
```

## Three split modes

```js
const h1 = document.querySelector('h1');

// Mode 1: characters — dramatic per-letter animation
new SplitType(h1, { types: 'chars' });
// → <span class="char">O</span><span class="char">r</span>...

// Mode 2: words — cleaner, less "typewriter-y"
new SplitType(h1, { types: 'words' });
// → <span class="word">Oryzo</span> <span class="word">isn't</span>...

// Mode 3: lines — reveals paragraphs line by line
new SplitType(h1, { types: 'lines' });

// Combo: both — chars inside words inside lines (most control)
new SplitType(h1, { types: 'lines, words, chars' });
```

## The three canonical reveals

### Reveal A: Staggered fade-up (Lusion headline style)

```js
const split = new SplitType('.hero-headline', { types: 'words, chars' });

gsap.from(split.chars, {
  y: 100,
  opacity: 0,
  rotationX: -90,          // slight 3D tilt — the premium touch
  duration: 0.8,
  ease: 'power4.out',
  stagger: 0.015,          // 15ms between chars
  scrollTrigger: {
    trigger: '.hero-headline',
    start: 'top 80%',
    toggleActions: 'play none none reverse',
  }
});
```

CSS needed for the 3D tilt:

```css
.hero-headline {
  perspective: 1000px;
}
.hero-headline .char {
  display: inline-block;
  transform-origin: 50% 50% -50px;
}
```

### Reveal B: Mask slide-up (Obsidian editorial style)

Each line slides up from behind a mask — feels like a printing press.

```html
<h2 class="split-mask">These places aren't broadly announced.</h2>
```

```css
.split-mask { overflow: hidden; }
.split-mask .line { overflow: hidden; }
.split-mask .word { display: inline-block; }
```

```js
const split = new SplitType('.split-mask', { types: 'lines, words' });

// Wrap each line in an overflow: hidden container (SplitType does this if you use 'lines')
gsap.from(split.words, {
  y: '100%',
  duration: 1.2,
  ease: 'power4.out',
  stagger: 0.02,
  scrollTrigger: {
    trigger: '.split-mask',
    start: 'top 75%',
  }
});
```

### Reveal C: Scroll-scrubbed reveal (character by character as you scroll)

Each character's opacity is tied to scroll progress — the text "types itself" as user scrolls through a section.

```js
const split = new SplitType('.scroll-reveal', { types: 'words' });

// Initial state: all words transparent
gsap.set(split.words, { opacity: 0.15 });

// Each word becomes opaque as scroll crosses it
split.words.forEach((word, i) => {
  gsap.to(word, {
    opacity: 1,
    scrollTrigger: {
      trigger: word,
      start: 'top 70%',
      end: 'top 40%',
      scrub: true,
    }
  });
});
```

This is the effect on oryzo.ai's long-form sections — text feels like it's being written as you scroll.

## Editorial fragmentation (obsidianassembly.com signature)

The Obsidian site breaks words at unexpected places: "Nothing/Shown/First", "Commitment/Precedes/Entry". This is done with a combination of:

1. **Explicit `<br>` or `<span>` breaks in HTML**
2. **Narrow column widths** that force wrapping
3. **Visual slashes or punctuation** that separate concepts

```html
<h2 class="obsidian-break">
  <span>Coordinates</span>
  <span>Withheld</span>
</h2>

<h3 class="obsidian-break">
  <span>Commitment</span>
  <span>Precedes</span>
  <span>Entry</span>
</h3>
```

```css
.obsidian-break {
  font-family: 'Editorial New', serif;
  font-size: clamp(3rem, 8vw, 7rem);
  line-height: 0.9;
  letter-spacing: -0.04em;
  text-transform: none;
}
.obsidian-break span {
  display: block;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 1s, transform 1s;
}
.obsidian-break.in-view span:nth-child(1) { transition-delay: 0s; }
.obsidian-break.in-view span:nth-child(2) { transition-delay: 0.1s; }
.obsidian-break.in-view span:nth-child(3) { transition-delay: 0.2s; }
.obsidian-break.in-view span {
  opacity: 1;
  transform: translateY(0);
}
```

Trigger with IntersectionObserver or ScrollTrigger:

```js
ScrollTrigger.create({
  trigger: '.obsidian-break',
  start: 'top 80%',
  onEnter: (self) => self.trigger.classList.add('in-view'),
});
```

## Font re-split on resize

Line-based splits **will break on resize** — the browser re-flows text but SplitType's spans are frozen. Always re-split on resize:

```js
let split = new SplitType('.headline', { types: 'lines' });

const resplit = () => {
  split.revert();
  split = new SplitType('.headline', { types: 'lines' });
  // Re-apply animations here if needed
  ScrollTrigger.refresh();
};

window.addEventListener('resize', gsap.utils.throttle(resplit, 200));
```

## Font loading race condition

If you split before the custom font has loaded, the character widths are wrong and the animation reveals "popping" letters. Always wait:

```js
document.fonts.ready.then(() => {
  new SplitType('.headline', { types: 'chars' });
  // ... animations
});
```

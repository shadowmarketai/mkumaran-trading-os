---
name: shadow-3d-scroll
description: Build award-tier 3D scroll experiences for marketing and landing pages in the style of Lusion (oryzo.ai) and Fiddle.Digital (obsidianassembly.com). ALWAYS use this skill when building PUBLIC/MARKETING pages that need scroll-driven 3D, pinned heroes, image displacement, horizontal scroll, stacked cards, fragmented text reveals, or smooth scroll. Enforces the canonical stack (Lenis + GSAP ScrollTrigger + Three.js + SplitType) on top of the template's Vite + React 18 + TypeScript + Tailwind setup. DO NOT activate for dashboard/app routes — those keep native scroll.
origin: Shadow Market
---

# Shadow 3D Scroll — Shadow Market Template Skill

A production-ready toolkit for building cinematic, 3D-forward scroll experiences on **marketing/landing routes only**. Inspired by [oryzo.ai](https://oryzo.ai) (Lusion) and [obsidianassembly.com](https://obsidianassembly.com) (Fiddle.Digital).

**This is a companion to `frontend-patterns`, not a replacement.** Use `frontend-patterns` for component architecture, state, data fetching. Use `FRONTEND.md` for general React conventions. Use THIS skill only for the motion layer on marketing-facing routes.

---

## Critical: Marketing routes ONLY

This template is an authenticated dashboard SaaS. Routes split into two buckets:

| Route bucket | Example routes | Use this skill? |
|---|---|---|
| **Marketing / public** | `/`, `/pricing`, `/features`, `/about`, `/landing/*` | ✅ YES |
| **Authenticated app** | `/dashboard`, `/settings`, `/admin`, any product route | ❌ NO — native scroll |

Wrap only marketing routes in `<SmoothScroll>`. Lenis will break modals, fixed sidebars, and data tables in the dashboard.

---

## When to activate

Activate when the user asks for ANY of:

- "Lusion-style", "Awwwards-style", "cinematic scroll", "premium landing"
- References to `oryzo.ai` or `obsidianassembly.com`
- 3D hero, scroll rotation, pinned model, horizontal scroll, stacked cards, image displacement, fragmented text, SplitType
- Smooth scroll / Lenis / GSAP ScrollTrigger / Three.js scroll
- "Landing page", "marketing page", "pricing page" + motion brief

Do NOT activate for:
- Dashboard pages inside `src/pages/{dashboard,printers,reports,settings,admin,analytics}/`
- Auth pages (`LoginPage`, `RegisterPage`) — use simple Framer Motion instead
- Basic `opacity: 0 → 1` scroll fades — use Tailwind `animate-*` utilities

---

## Stack additions required

The template's current `frontend/package.json` has no animation libraries. Before any pattern in this skill can be used, add:

```bash
cd frontend
npm install lenis gsap three split-type framer-motion
npm install -D @types/three
```

Deps by purpose:
| Package | For |
|---|---|
| `lenis` | Pattern 01 (smooth scroll) |
| `gsap` | Patterns 02–08 (scroll-driven animation) |
| `three` + `@types/three` | Patterns 02, 03, 04 (3D + displacement) |
| `split-type` | Pattern 05 (fragmented text) |
| `framer-motion` | General component animations, page transitions |

---

## The 8 core patterns

Full details in `references/`. Ready-to-paste React+TSX components in `templates/` and `components/`.

| # | Pattern | Reference | Ready component |
|---|---|---|---|
| 1 | Smooth scroll foundation | `references/01_smooth_scroll.md` | `components/SmoothScroll.tsx` |
| 2 | Pinned 3D hero | `references/02_pinned_3d_hero.md` | `components/HeroPinned3D.tsx` |
| 3 | Scroll-linked model rotation & scale | `references/03_scroll_rotate.md` | Part of `HeroPinned3D.tsx` |
| 4 | Image displacement shader (hover + scroll) | `references/04_displacement.md` | `components/DisplacementImage.tsx` |
| 5 | SplitType fragmented text reveal | `references/05_text_split.md` | `components/SplitTextReveal.tsx` |
| 6 | Horizontal pinned scroll | `references/06_horizontal.md` | `components/HorizontalScroll.tsx` |
| 7 | Sticky stacked card reveal | `references/07_sticky_stack.md` | `components/StackedCards.tsx` |
| 8 | Multi-layer parallax | `references/08_parallax.md` | `components/Parallax.tsx` |

---

## Integration with this template's conventions

### 1. File placement

Drop generated components into `frontend/src/components/scroll/`:

```
frontend/src/
├── components/
│   ├── ui/              # existing shadcn-style primitives — DO NOT TOUCH
│   ├── layout/          # existing PageWrapper, Sidebar — DO NOT TOUCH
│   └── scroll/          # ← NEW: all shadow-3d-scroll output lands here
│       ├── SmoothScroll.tsx
│       ├── HeroPinned3D.tsx
│       ├── DisplacementImage.tsx
│       ├── HorizontalScroll.tsx
│       ├── StackedCards.tsx
│       ├── SplitTextReveal.tsx
│       ├── Parallax.tsx
│       └── lib/
│           ├── gsapSetup.ts
│           └── useReducedMotion.ts
```

### 2. Route wrapping (Vite + react-router-dom v6)

In `src/App.tsx`, split routes into marketing and app trees:

```tsx
import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom';
import SmoothScroll from '@/components/scroll/SmoothScroll';

function MarketingLayout() {
  return (
    <SmoothScroll>
      <Outlet />
    </SmoothScroll>
  );
}

function AppLayout() {
  // Native scroll — no SmoothScroll wrapper
  return <Outlet />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Marketing routes — cinematic scroll */}
        <Route element={<MarketingLayout />}>
          <Route path="/" element={<LandingPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/features" element={<FeaturesPage />} />
        </Route>

        {/* App routes — native scroll */}
        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/printers/*" element={<PrintersRoutes />} />
          {/* ... rest of existing app routes ... */}
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

### 3. TypeScript conventions

All components use the template's existing conventions:
- Export default for page-level components
- Named exports for utilities
- `interface Props` not `type Props`
- Path alias `@/` maps to `src/` (verify `tsconfig.json` / `vite.config.ts`)
- Tailwind classes only — no `styled-components`, no CSS-in-JS

### 4. Central GSAP registration

One file registers all plugins. Import this once at app entry:

```ts
// frontend/src/components/scroll/lib/gsapSetup.ts
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
}

export { gsap, ScrollTrigger };
```

Then in every scroll component: `import { gsap, ScrollTrigger } from '@/components/scroll/lib/gsapSetup'`.

---

## Non-negotiable rules

These are enforced because violating them is what separates amateur scroll sites from Lusion-tier work.

1. **Always wire Lenis to ScrollTrigger's ticker.** Without this, GSAP and Lenis fight each other and you get jitter. See `components/SmoothScroll.tsx`.

2. **Always respect `prefers-reduced-motion`.** Every component must check it and return a static fallback.

3. **Pin 3D canvases, don't translate them.** Use `ScrollTrigger.pin()` + `scrub: 1`, never absolute positioning with `transform: translateY()`.

4. **Use `scrub: 1` (or a small number), not `scrub: true`.** `scrub: 1` gives premium feel. `scrub: true` feels cheap.

5. **Load 3D models as GLB, not OBJ.** Store in `frontend/public/models/`.

6. **`renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))`.** Always clamp to 2.

7. **Every ScrollTrigger needs cleanup.** In `useEffect`, always return `() => ScrollTrigger.getAll().forEach(t => t.kill())`.

8. **Disable heavy 3D below 768px.** Use `ScrollTrigger.matchMedia()` to swap in a lighter fallback.

---

## Decision tree

```
Is the target route under /dashboard, /printers, /reports, /settings, /admin?
├── YES → DO NOT USE THIS SKILL. Use frontend-patterns + framer-motion only.
└── NO  → continue

Is there a hero with a focal 3D object or product?
├── YES → HeroPinned3D (Pattern 02 + 03)
└── NO  → continue

Are there images that should distort, ripple, or flow?
├── YES → DisplacementImage (Pattern 04)
└── NO  → continue

Is there long-form copy that should feel "typed in" by scroll?
├── YES → SplitTextReveal (Pattern 05)
└── NO  → continue

Is there a product lineup, pricing comparison, or feature gallery?
├── YES → HorizontalScroll (Pattern 06)
└── NO  → continue

Are there stacking process steps, layered cards, or overlapping sections?
├── YES → StackedCards (Pattern 07)
└── NO  → Parallax (Pattern 08) as connective motion layer
```

SmoothScroll (Pattern 01) is **always** included on marketing routes.

---

## Interaction with existing template skills

| If the brief involves... | Activate |
|---|---|
| Marketing page build | `shadow-3d-scroll` + `frontend-patterns` + `FRONTEND.md` |
| Marketing copy/ads | `shadow-3d-scroll` + `shadow-market-prompt` (if added) |
| Video/reel for page | `scene-pipeline` (if added) + `shadow-3d-scroll` for accompanying web work |
| Dashboard feature | `frontend-patterns` + `FRONTEND.md` ONLY (no shadow-3d-scroll) |
| Backend work | `BACKEND.md` + `api-design` + `python-patterns` (no shadow-3d-scroll) |

---

## Output checklist

Before handing off any build using this skill, confirm:

- [ ] Dependencies added to `frontend/package.json` (`lenis`, `gsap`, `three`, `split-type`, `@types/three`)
- [ ] Lenis is wired to GSAP's ticker in `SmoothScroll.tsx`
- [ ] All ScrollTriggers use `scrub: 1` (not `true`)
- [ ] `prefers-reduced-motion` fallback returns static version
- [ ] Three.js `renderer.setPixelRatio` clamped to max 2
- [ ] Mobile (<768px) uses `ScrollTrigger.matchMedia()` with lighter branch
- [ ] All `useEffect` hooks have ScrollTrigger cleanup
- [ ] Components only imported into marketing routes (not dashboard)
- [ ] `document.fonts.ready.then(() => ScrollTrigger.refresh())` after mount
- [ ] Page weight inspected — if >3MB, compress GLB with `gltf-transform`

---

## Studio fingerprints

**Lusion (oryzo.ai):** dark mode, warm accents (#c9a074 cork), display serif + geometric sans, pinned 3D for 3–5 viewport heights, playful micro-interactions, GLSL-heavy.

**Fiddle.Digital (obsidianassembly.com):** muted stone/bone/graphite, editorial serifs with aggressive word-breaking, image displacement on hover, slow Lenis duration (1.5s), gallery-like restraint.

Pick one or blend — match the client's brand voice.

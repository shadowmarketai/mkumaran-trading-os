# Build Marketing Page

Scaffold a cinematic marketing/landing page using the `shadow-3d-scroll` skill.

## When to use

Run this command when the user asks for a landing page, marketing page, homepage, or any public-facing page with motion. Do NOT run this for dashboard/app features — use standard `frontend-patterns` for those.

## Step 1: Gather the brief

If the user hasn't provided a client brief, ask for these fields (ONE message, bundled):

1. **Client name & industry**
2. **Brand colors** (primary, accent, background — hex codes)
3. **Reference sites** (1–3 sites whose aesthetic should be matched)
4. **Page scope** (home / pricing / features / about / case studies)
5. **Must-have sections** (free-form)
6. **Aesthetic direction** — Lusion-playful / Obsidian-editorial / Custom hybrid
7. **Assets provided** — logo, 3D model, photography, copy?

## Step 2: Confirm dependencies

Check `frontend/package.json` for `lenis`, `gsap`, `three`, `split-type`, `framer-motion`. If any are missing, run:

```bash
cd frontend && npm install lenis@^1.1.14 gsap@^3.12.5 three@^0.160.0 split-type@^0.3.4 framer-motion@^11.3.0 && npm install -D @types/three@^0.160.0
```

## Step 3: Verify scroll components exist

Check `frontend/src/components/scroll/` for:
- `SmoothScroll.tsx`
- `HeroPinned3D.tsx`
- `DisplacementImage.tsx`
- `SplitTextReveal.tsx`
- `HorizontalScroll.tsx`
- `StackedCards.tsx`
- `Parallax.tsx`
- `lib/gsapSetup.ts`
- `lib/useReducedMotion.ts`

If missing, copy from `skills/shadow-3d-scroll/components/` into `frontend/src/components/scroll/`.

## Step 4: Verify route split

Check `frontend/src/App.tsx` for a `MarketingLayout` that wraps public routes in `<SmoothScroll>`. If the split doesn't exist, refactor per `skills/shadow-3d-scroll/App.example.tsx`.

## Step 5: Build the page

Create `frontend/src/pages/marketing/<PageName>.tsx` using the composition pattern from `LandingPage.example.tsx`. Adapt copy, colors, and section order to the client brief. Follow the skill's 8 pattern references in `skills/shadow-3d-scroll/references/` when unsure.

## Step 6: Register the route

Add the route inside `MarketingLayout` in `App.tsx`. Use `React.lazy()` for code splitting so the 3D/GSAP bundle stays out of the dashboard.

## Step 7: Validate

Run:
```bash
cd frontend && npm run lint && npm run type-check && npm run build
```

All three must pass. Then run `npm run dev` and confirm:
- Page loads without console errors
- Scroll feels smooth, no jitter
- Reduced-motion fallback works (test via DevTools)
- Mobile layout degrades gracefully

## Rules (non-negotiable)

- NEVER import scroll components into dashboard routes (`/dashboard`, `/printers`, `/reports`, `/settings`, `/admin`, `/analytics`)
- ALWAYS use `scrub: 1` (not `true`) on ScrollTrigger
- ALWAYS clamp `renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))`
- ALWAYS clean up ScrollTriggers in `useEffect` return
- NEVER use `any` types; interfaces for all props
- Tailwind classes only; no `style={}` except for dynamic color/transform values

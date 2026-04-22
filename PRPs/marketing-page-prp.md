# PRP: Marketing Page Build (Shadow 3D Scroll)

> Implementation blueprint for building a cinematic marketing/landing page using the `shadow-3d-scroll` skill.

---

## METADATA

| Field | Value |
|-------|-------|
| **Product** | Client Marketing Page |
| **Type** | Public-facing landing page (Vite + React + TypeScript) |
| **Skill** | `shadow-3d-scroll` (primary) + `frontend-patterns` (supporting) |
| **Complexity** | Medium |
| **Typical duration** | 2–4 days per page |
| **Frontend Pages** | 1–6 (Home, Pricing, Features, About, Case Studies, Contact) |

---

## INPUT BRIEF (fill this in before handing to Claude Code)

### Client details
- **Client name:** _______________
- **Industry:** _______________
- **Brand colors (HEX):** primary ___, accent ___, background ___
- **Typography preference:** _______________
- **Reference sites to match (1–3):** _______________
- **Brand voice:** [Lusion-playful | Obsidian-editorial | Custom hybrid]

### Page scope
- **Pages to build:** [ ] Home  [ ] Pricing  [ ] Features  [ ] About  [ ] Case Studies  [ ] Contact
- **Must-have sections:** _______________
- **Assets provided:**
  - [ ] Logo (SVG)
  - [ ] Hero 3D model (GLB) or use placeholder
  - [ ] Photography (for displacement sections)
  - [ ] Copy deck (or use `shadow-market-prompt` skill to generate)

### Motion brief
- [ ] Hero: 3D pinned model (Pattern 02+03)
- [ ] Text reveals on scroll (Pattern 05)
- [ ] Horizontal pricing/features (Pattern 06)
- [ ] Stacked process cards (Pattern 07)
- [ ] Image displacement on case studies (Pattern 04)
- [ ] Parallax layers (Pattern 08) — subtle, throughout

---

## IMPLEMENTATION PHASES

### Phase 1 — Dependencies & scaffolding

**Orchestrator agent / manual:**

1. Verify `frontend/package.json` has the scroll stack. If missing, run:
   ```bash
   cd frontend
   npm install lenis@^1.1.14 gsap@^3.12.5 three@^0.160.0 split-type@^0.3.4 framer-motion@^11.3.0
   npm install -D @types/three@^0.160.0
   ```
2. Copy `shadow-3d-scroll` components into `frontend/src/components/scroll/` if not present:
   - `SmoothScroll.tsx`
   - `HeroPinned3D.tsx`
   - `DisplacementImage.tsx`
   - `SplitTextReveal.tsx`
   - `HorizontalScroll.tsx`
   - `StackedCards.tsx`
   - `Parallax.tsx`
   - `lib/gsapSetup.ts`
   - `lib/useReducedMotion.ts`
3. Verify `App.tsx` splits marketing and dashboard routes. If not, refactor per `App.example.tsx`.
4. Create `src/pages/marketing/` directory if missing.

**Acceptance:** `npm run type-check` passes. `npm run dev` renders without runtime errors.

---

### Phase 2 — Page structure

**frontend-agent:**

Create the page file(s) at `src/pages/marketing/<PageName>.tsx`. Each page is a standalone composition of patterns. Follow the template in `skills/shadow-3d-scroll/components/` and the composition example in `LandingPage.example.tsx`.

**Section order for landing pages:**
1. Hero (Pattern 02+03) — 1 viewport visible, 3–4 viewport pin depth
2. Intro / mission (Pattern 05, `chars-3d` variant) — large statement
3. Capabilities / features (Pattern 06) — horizontal scroll, 3–5 panels
4. Case studies / work (Pattern 04) — displacement image grid
5. Process / how-it-works (Pattern 07) — 3–6 stacked cards
6. CTA (Pattern 05, `editorial` variant) — closing statement + mail-to

**Acceptance:** All imports resolve, no `any` types used, every ScrollTrigger has cleanup in `useEffect` return.

---

### Phase 3 — Copy & content

**If the client provided copy:** paste it in.

**If copy is still to be written:** activate the `shadow-market-prompt` skill (if installed in this repo) and run the 7-block protocol to generate it before filling the components. Do not write copy freestyle — the framework is non-negotiable.

---

### Phase 4 — Assets & performance

**devops-agent / manual:**

1. Place 3D models at `frontend/public/models/*.glb` (compressed with `gltf-transform` if >500KB)
2. Place case study images at `frontend/public/case-studies/` (1024×1280 max, WebP/AVIF preferred)
3. Run Lighthouse on the built page:
   - [ ] LCP < 2.5s
   - [ ] CLS < 0.1
   - [ ] Total JS < 400KB gzipped for marketing routes
4. If Three.js is pushing JS size over budget, confirm lazy routing (`React.lazy()` + `Suspense`) is wrapping marketing pages in `App.tsx`.

**Acceptance:** Lighthouse scores meet targets on both desktop and mobile.

---

### Phase 5 — Review & polish

**code-reviewer + typescript-reviewer agents:**

Review checklist:
- [ ] No scroll components imported into `/dashboard`, `/printers`, `/reports`, `/settings`, `/admin`, `/analytics` pages
- [ ] `prefers-reduced-motion` works on every component (test with DevTools emulation)
- [ ] Keyboard navigation works — all CTAs reachable via Tab
- [ ] Mobile <768px — heavy 3D disabled via `matchMedia`, content still accessible
- [ ] Anchor links use `lenis.scrollTo()` not native `#hash` (if Lenis is active)
- [ ] No `console.log` in shipped code
- [ ] All Tailwind classes used — no inline `style={}` except for dynamic values (colors, transforms)
- [ ] SEO: `<title>`, `<meta description>`, OG tags present per page

---

## VALIDATION

Before marking this PRP complete:

```bash
cd frontend
npm run lint          # Zero errors
npm run type-check    # Zero errors
npm run build         # Clean build
npm run preview       # Manual QA in browser
```

Manual QA:
1. Scroll top to bottom — no jitter, no layout shift
2. Toggle reduced-motion in DevTools — page still readable and functional
3. Resize window mid-scroll — layout doesn't break
4. Load on mobile (real device, not emulator) — 3D either works or degrades gracefully
5. Load on Safari — shaders render correctly

---

## REFERENCES

- Main skill: `skills/shadow-3d-scroll/SKILL.md`
- Pattern references: `skills/shadow-3d-scroll/references/`
- Example composition: `skills/shadow-3d-scroll/components/` + `LandingPage.example.tsx`
- Related PRPs: _add after first use_
- Related skills: `frontend-patterns`, `FRONTEND.md`, `shadow-market-prompt` (for copy)

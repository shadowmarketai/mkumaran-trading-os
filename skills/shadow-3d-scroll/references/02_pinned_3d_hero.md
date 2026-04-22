# Pattern 02 — Pinned 3D Hero (the oryzo.ai opening)

A 3D model sits in the center of the viewport. The user scrolls, the page appears to stay still, and the model rotates / scales / has its material properties change. This is the signature Lusion move.

## The mental model

- The 3D canvas is **pinned** (position doesn't change) for a fixed scroll distance
- As the user scrolls through that distance, the scroll position is mapped 0→1
- That normalized value drives every animated property: rotation, scale, camera position, material uniforms

## Anatomy

```
┌─────────────────────────────────┐
│ Section wrapper (100vh height)  │  ← pin target
│  ┌───────────────────────────┐  │
│  │ Canvas (position: fixed   │  │  ← Three.js renders here
│  │        during pin)        │  │
│  │                           │  │
│  │       [3D MODEL]          │  │  ← rotates with scroll progress
│  │                           │  │
│  └───────────────────────────┘  │
│                                 │
│ Scroll spacer (300vh invisible) │  ← gives scroll distance
└─────────────────────────────────┘
```

## Full working implementation

See `templates/hero_pinned_model.html` for the complete copy-paste version. Core structure below:

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

// 1. Scene setup
const canvas = document.querySelector('#hero-canvas');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 0, 5);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // CLAMP TO 2

// 2. Lighting (three-point setup — the "product photography" look)
const key = new THREE.DirectionalLight(0xffffff, 1.2);
key.position.set(5, 5, 5);
const fill = new THREE.DirectionalLight(0xb0c4de, 0.6);
fill.position.set(-5, 0, 2);
const rim = new THREE.DirectionalLight(0xffffff, 0.8);
rim.position.set(0, -3, -5);
scene.add(key, fill, rim, new THREE.AmbientLight(0xffffff, 0.3));

// 3. Load model
let model;
const loader = new GLTFLoader();
loader.load('/models/product.glb', (gltf) => {
  model = gltf.scene;
  model.scale.set(1, 1, 1);
  scene.add(model);

  // 4. Pin + scroll-drive the model AFTER it's loaded
  initScrollAnimation();
});

// 5. Render loop
function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();

// 6. The scroll animation itself
function initScrollAnimation() {
  // Create a timeline pinned to the hero section
  const tl = gsap.timeline({
    scrollTrigger: {
      trigger: '#hero',
      start: 'top top',
      end: '+=300%',        // pin for 3 viewport heights of scroll
      pin: true,
      scrub: 1,              // 1s ease — premium feel
      anticipatePin: 1,      // prevents pin flicker on fast scroll
    }
  });

  // Phase 1: model rotates 360° on Y
  tl.to(model.rotation, { y: Math.PI * 2, ease: 'none' }, 0);

  // Phase 2: model tilts slightly on X (happens in the last 40%)
  tl.to(model.rotation, { x: 0.3, ease: 'none' }, 0.6);

  // Phase 3: camera pulls back
  tl.to(camera.position, { z: 7, ease: 'none' }, 0.3);

  // Phase 4: background color shifts (if using scene.background)
  tl.to(scene, { background: new THREE.Color(0x0a0a0a), ease: 'none' }, 0.5);
}

// 7. Handle resize
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// 8. Refresh after fonts/images load (prevents pin miscalc)
document.fonts.ready.then(() => ScrollTrigger.refresh());
```

## HTML structure

```html
<section id="hero" style="height: 100vh; position: relative;">
  <canvas id="hero-canvas" style="position: absolute; inset: 0; width: 100%; height: 100%;"></canvas>
  <div class="hero-copy" style="position: relative; z-index: 2;">
    <h1>Made for mugs. Built for tables.</h1>
    <p class="scroll-hint">Scroll to continue</p>
  </div>
</section>

<!-- After the hero, the model disappears and normal content flows -->
<section id="features">...</section>
```

## Tuning guide

| Property | Cheap look | Premium look |
|---|---|---|
| `scrub` | `true` (instant) | `1` or `1.5` (eased) |
| Rotation amount | `Math.PI * 4` (spins too much) | `Math.PI * 2` (one full turn max) |
| Pin duration `end` | `+=100%` (too short, rushed) | `+=300%` to `+=500%` |
| Lighting | Single `AmbientLight` | 3-point + HDR environment |
| Model scale | Jumps abruptly | Eases with `power2.inOut` |

## Performance budget

- Model: **<500KB** compressed (use `gltfpack -c` from meshopt)
- Textures: **1024x1024 max**, use KTX2 / basis compression
- Draw calls: **<30** (merge meshes in Blender if needed)
- Target: **60fps on a 2019 MacBook Air**, **30fps on mid-range Android**

## No model? Use a primitive.

If the user doesn't have a 3D model, fake it convincingly with primitives:

```js
// A "coaster" like oryzo — cylinder with a noise-displaced material
const geometry = new THREE.CylinderGeometry(1.5, 1.5, 0.15, 64);
const material = new THREE.MeshStandardMaterial({
  color: 0xc9a074,
  roughness: 0.9,
  metalness: 0.0,
});
const coaster = new THREE.Mesh(geometry, material);
scene.add(coaster);
```

Add normal maps and ambient occlusion later if needed.

# Pattern 03 — Scroll-Linked Rotation, Scale & Morph

Pattern 02 covered the foundational "pin and rotate." This reference goes deeper into the rotation *vocabulary* — the specific motion choices that separate Lusion-grade from generic.

## The four rotation archetypes

### 1. Orbital rotation (oryzo.ai hero)
Model rotates on Y while camera orbits slightly. Feels like "inspecting" the product.

```js
const tl = gsap.timeline({ scrollTrigger: { trigger: '#hero', start: 'top top', end: '+=400%', pin: true, scrub: 1 } });

// Model spins on Y
tl.to(model.rotation, { y: Math.PI * 2, ease: 'none' }, 0);

// Camera orbits in a subtle arc (not a full circle)
tl.to(camera.position, { 
  x: 2, 
  y: 1, 
  ease: 'power2.inOut' 
}, 0).to(camera.position, { 
  x: 0, 
  y: 0, 
  ease: 'power2.inOut' 
}, 0.5);

// Keep camera looking at model throughout
const cameraUpdate = () => camera.lookAt(0, 0, 0);
gsap.ticker.add(cameraUpdate);
```

### 2. Tumbling reveal (unveiling a product)
Model starts off-axis and "settles" into view as user scrolls.

```js
// Initial state: tilted and scaled down
model.rotation.set(-Math.PI / 4, Math.PI / 3, 0);
model.scale.set(0.3, 0.3, 0.3);

const tl = gsap.timeline({ scrollTrigger: { trigger: '#hero', start: 'top top', end: '+=300%', pin: true, scrub: 1 } });

tl.to(model.rotation, { x: 0, y: 0, z: 0, ease: 'power3.out' }, 0);
tl.to(model.scale, { x: 1, y: 1, z: 1, ease: 'back.out(1.2)' }, 0);
```

### 3. Exploded view (technical product reveal)
Model's sub-meshes separate radially as user scrolls, then reassemble.

```js
// Assumes model has named children: part1, part2, part3...
const parts = model.children;
const originalPositions = parts.map(p => p.position.clone());

const tl = gsap.timeline({ scrollTrigger: { trigger: '#hero', start: 'top top', end: '+=500%', pin: true, scrub: 1 } });

parts.forEach((part, i) => {
  const direction = originalPositions[i].clone().normalize();
  // Explode outward in first half
  tl.to(part.position, { 
    x: direction.x * 3, 
    y: direction.y * 3, 
    z: direction.z * 3, 
    ease: 'power2.inOut' 
  }, 0);
  // Reassemble in second half
  tl.to(part.position, { 
    x: originalPositions[i].x, 
    y: originalPositions[i].y, 
    z: originalPositions[i].z, 
    ease: 'power2.inOut' 
  }, 0.5);
});
```

### 4. Ribbon / sway (for flat objects like coasters, cards, paper)
Gentle oscillation that tracks scroll velocity.

```js
let scrollVelocity = 0;

ScrollTrigger.create({
  trigger: '#hero',
  start: 'top top',
  end: '+=300%',
  pin: true,
  scrub: 1,
  onUpdate: (self) => {
    scrollVelocity = self.getVelocity() / 1000;
  }
});

// In render loop:
function animate() {
  requestAnimationFrame(animate);
  // Sway that dampens over time
  model.rotation.z += (scrollVelocity * 0.01 - model.rotation.z) * 0.1;
  renderer.render(scene, camera);
}
```

## Material property scrubbing

Beyond geometry, scrub *material* properties for subtle high-end touches:

```js
// Metallic finish intensifies as user scrolls deeper
tl.to(model.material, { metalness: 0.9, ease: 'none' }, 0);

// Opacity reveals wireframe underneath
tl.to(model.material, { opacity: 0.3, transparent: true, ease: 'none' }, 0.5);

// Color shift (requires animating .r .g .b separately)
tl.to(model.material.color, { r: 0.9, g: 0.3, b: 0.1, ease: 'none' }, 0);
```

## Shader uniform scrubbing (advanced)

For custom shader materials, drive uniforms directly:

```js
const material = new THREE.ShaderMaterial({
  uniforms: {
    uProgress: { value: 0 },
    uTime: { value: 0 },
  },
  vertexShader: /* glsl */ `
    uniform float uProgress;
    void main() {
      vec3 pos = position;
      pos.y += sin(pos.x * 5.0 + uProgress * 6.28) * 0.2 * uProgress;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    void main() { gl_FragColor = vec4(1.0); }
  `,
});

// Scrub the uniform
tl.to(material.uniforms.uProgress, { value: 1, ease: 'none' }, 0);
```

## The "scroll velocity" trick (signature oryzo move)

When the user scrolls fast, the model wiggles slightly more. When they stop, it settles. This is what makes scroll feel "alive."

```js
let targetRotationZ = 0;

ScrollTrigger.create({
  onUpdate: (self) => {
    // Velocity is in pixels/sec; normalize to a small rotation
    targetRotationZ = Math.max(-0.15, Math.min(0.15, self.getVelocity() / 3000));
  }
});

function animate() {
  requestAnimationFrame(animate);
  // Lerp toward target — never snap
  model.rotation.z += (targetRotationZ - model.rotation.z) * 0.08;
  // Decay target
  targetRotationZ *= 0.95;
  renderer.render(scene, camera);
}
```

## Don't do this

| Mistake | Why it's bad | Correct approach |
|---|---|---|
| `rotation.y = scrollY * 0.01` direct mapping | No easing, feels robotic | Use GSAP timeline with `scrub: 1` |
| Rotating 720° or more | Feels like a circus ride | Max one full turn (360°) per pin |
| Scrubbing on every property simultaneously | Motion soup — eye doesn't know what to track | Orchestrate: rotate THEN scale THEN tilt |
| Using Euler angles for complex rotations | Gimbal lock at edge cases | Use quaternions or axis-angle for >90° rotations |

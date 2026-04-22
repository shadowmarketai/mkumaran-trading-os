# Pattern 04 — Image Displacement Shader (obsidianassembly.com signature)

The signature move at obsidianassembly.com: images that ripple, distort, or "melt" on hover and scroll. This is done with a **displacement shader** — a custom GLSL fragment that uses a grayscale noise texture to offset the UV coordinates of the image.

## The concept

```
Original image + Displacement map + Progress value (0→1 from scroll/hover)
                          ↓
             Fragment shader offsets UV coords
                          ↓
                 Distorted image output
```

## Approach A: `hover-effect` library (fastest to ship)

If the user wants hover distortion and *nothing else*, use Robin Delaporte's `hover-effect.js`. It's 8KB and wraps Three.js for you.

```html
<div id="image-wrap" style="width: 800px; height: 500px;"></div>

<script src="https://cdn.jsdelivr.net/gh/robin-dela/hover-effect@1.1.1/js/hover-effect.umd.js"></script>
<script>
  new hoverEffect({
    parent: document.querySelector('#image-wrap'),
    intensity: 0.3,
    image1: '/images/a.jpg',
    image2: '/images/b.jpg',
    displacementImage: '/images/displacement.jpg', // grayscale cloud/noise texture
    speedIn: 1.2,
    speedOut: 1.2,
    easing: 'power3.out',
  });
</script>
```

Find good displacement maps: search "cloud displacement map grayscale" or generate one with a noise generator.

## Approach B: Custom Three.js shader (scroll-driven, Lusion-grade)

For scroll-linked displacement (not just hover), you need the real shader. Full template in `templates/displacement.html`.

### Core shader

```glsl
// Vertex shader (standard passthrough)
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
```

```glsl
// Fragment shader — the magic
uniform sampler2D uTexture;         // the image
uniform sampler2D uDisplacement;    // grayscale noise
uniform float uProgress;            // 0 → 1 from scroll
uniform float uIntensity;           // how strong (0.1 subtle, 0.5 dramatic)
uniform vec2 uResolution;
varying vec2 vUv;

void main() {
  // Sample displacement map
  vec4 disp = texture2D(uDisplacement, vUv);
  
  // Compute offset — scroll progress gates the effect
  vec2 distortedUv = vUv + (disp.rg - 0.5) * uIntensity * uProgress;
  
  // Sample the image with distorted coords
  vec4 color = texture2D(uTexture, distortedUv);
  
  // Optional: RGB split for extra chromatic aberration
  float r = texture2D(uTexture, distortedUv + vec2(0.005, 0.0) * uProgress).r;
  float g = texture2D(uTexture, distortedUv).g;
  float b = texture2D(uTexture, distortedUv - vec2(0.005, 0.0) * uProgress).b;
  
  gl_FragColor = vec4(r, g, b, color.a);
}
```

### Setup code

```js
import * as THREE from 'three';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

const canvas = document.querySelector('#displace-canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
camera.position.z = 1;

const loader = new THREE.TextureLoader();
const image = loader.load('/images/photo.jpg');
const displacement = loader.load('/images/displacement.jpg');

const material = new THREE.ShaderMaterial({
  uniforms: {
    uTexture: { value: image },
    uDisplacement: { value: displacement },
    uProgress: { value: 0 },
    uIntensity: { value: 0.3 },
    uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
  },
  vertexShader: /* string above */,
  fragmentShader: /* string above */,
});

const plane = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
scene.add(plane);

// Drive uProgress with scroll
gsap.to(material.uniforms.uProgress, {
  value: 1,
  scrollTrigger: {
    trigger: '#displace-section',
    start: 'top bottom',
    end: 'bottom top',
    scrub: 1,
  }
});

// Or drive with hover:
canvas.addEventListener('mouseenter', () => {
  gsap.to(material.uniforms.uProgress, { value: 1, duration: 1, ease: 'power3.out' });
});
canvas.addEventListener('mouseleave', () => {
  gsap.to(material.uniforms.uProgress, { value: 0, duration: 1, ease: 'power3.out' });
});

function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();
```

## Approach C: Grid of images (obsidianassembly.com style)

To recreate the image grid on the Obsidian site (where the whole grid ripples together), use **one large plane per grid cell**, each with its own displacement uniform, but share the displacement texture.

Key insight: the Obsidian site uses a **staggered onUpdate** — when you scroll, each image in the grid starts its displacement animation 0.05s after the previous one. This creates the "wave through the grid" effect.

```js
const planes = []; // populated as you create each image plane

ScrollTrigger.create({
  trigger: '#grid-section',
  start: 'top bottom',
  end: 'bottom top',
  onUpdate: (self) => {
    planes.forEach((plane, i) => {
      const delay = i * 0.05;
      const progress = Math.max(0, Math.min(1, self.progress * (planes.length + 1) - i * 0.5));
      gsap.to(plane.material.uniforms.uProgress, {
        value: progress,
        duration: 0.3,
        delay,
        overwrite: true,
      });
    });
  }
});
```

## Displacement textures — where to get them

- **Make your own**: Photoshop → Filter → Render → Clouds → Motion Blur. Save as grayscale JPG.
- **Free packs**: search "ShaderToy displacement" or use Poliigon's free fabric noise textures.
- **Procedural**: generate in-shader with simplex noise if you don't want texture assets.

For procedural noise (no texture file needed):

```glsl
// Classic simplex noise inline — add to fragment shader
vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }
float snoise(vec2 v) {
  // ... (full Ashima Arts simplex noise impl — ~30 lines)
}

// Use in main():
float n = snoise(vUv * 5.0 + uTime * 0.1);
vec2 distortedUv = vUv + vec2(n * 0.05) * uProgress;
```

## Performance notes

- **One WebGL context per page** if possible. Multiple `<canvas>` elements each with their own Three.js context will eat GPU memory. Use a single renderer and multiple scenes, or stack planes in one scene.
- Image planes should use `powerOfTwo` textures (512x512, 1024x1024) for best GPU alignment.
- If you have 20+ images, consider `InstancedMesh` with texture atlasing.
- Always call `renderer.dispose()` on unmount (React).

## Accessibility

Displacement breaks at `prefers-reduced-motion: reduce`. Hard-skip the shader entirely and render images as plain `<img>` tags in that case.

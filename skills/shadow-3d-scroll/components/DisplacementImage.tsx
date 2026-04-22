import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { gsap, ScrollTrigger } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

interface DisplacementImageProps {
  src: string;
  alt?: string;
  /** Caption rendered below the image in editorial style */
  caption?: string;
  /** Seed for the procedural noise — different values = different ripple pattern */
  seed?: number;
  /** How strong the scroll-driven distortion is (0.0–1.0). Default 0.5 */
  scrollStrength?: number;
  className?: string;
}

const VERTEX_SHADER = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = `
  precision highp float;
  uniform sampler2D uTexture;
  uniform float uProgress;
  uniform float uHover;
  uniform vec2 uMouse;
  uniform float uTime;
  uniform float uSeed;
  varying vec2 vUv;

  vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }
  float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
    vec2 i  = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.0,0.0) : vec2(0.0,1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod(i, 289.0);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
    m = m*m; m = m*m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
  }

  void main() {
    vec2 uv = vUv;
    float n = snoise(uv * 4.0 + uSeed + uTime * 0.1);
    vec2 distortion = vec2(n, snoise(uv * 4.0 + uSeed + 5.0 + uTime * 0.1));
    float d = distance(uv, uMouse);
    float hoverFalloff = smoothstep(0.5, 0.0, d) * uHover;
    float totalProgress = max(uProgress, hoverFalloff);
    vec2 distortedUv = uv + distortion * 0.08 * totalProgress;
    float r = texture2D(uTexture, distortedUv + vec2(0.006, 0.0) * totalProgress).r;
    float g = texture2D(uTexture, distortedUv).g;
    float b = texture2D(uTexture, distortedUv - vec2(0.006, 0.0) * totalProgress).b;
    gl_FragColor = vec4(r, g, b, 1.0);
  }
`;

export default function DisplacementImage({
  src,
  alt = '',
  caption,
  seed = 1.0,
  scrollStrength = 0.5,
  className = '',
}: DisplacementImageProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
    camera.position.z = 1;

    const loader = new THREE.TextureLoader();
    const texture = loader.load(src, () => resize());
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;

    const material = new THREE.ShaderMaterial({
      uniforms: {
        uTexture: { value: texture },
        uProgress: { value: 0 },
        uHover: { value: 0 },
        uMouse: { value: new THREE.Vector2(0.5, 0.5) },
        uTime: { value: 0 },
        uSeed: { value: seed },
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
    });

    const plane = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    scene.add(plane);

    const resize = () => {
      const { width, height } = wrap.getBoundingClientRect();
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    };
    resize();
    window.addEventListener('resize', resize);

    // ── Hover ─────────────────────────────────────────
    const onEnter = () => {
      gsap.to(material.uniforms.uHover, { value: 1, duration: 1, ease: 'power3.out' });
    };
    const onLeave = () => {
      gsap.to(material.uniforms.uHover, { value: 0, duration: 1, ease: 'power3.out' });
    };
    const onMove = (e: MouseEvent) => {
      const rect = wrap.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = 1.0 - (e.clientY - rect.top) / rect.height;
      gsap.to(material.uniforms.uMouse.value, { x, y, duration: 0.4, ease: 'power2.out' });
    };
    wrap.addEventListener('mouseenter', onEnter);
    wrap.addEventListener('mouseleave', onLeave);
    wrap.addEventListener('mousemove', onMove);

    // ── Scroll ────────────────────────────────────────
    const scrollTween = gsap.to(material.uniforms.uProgress, {
      value: scrollStrength,
      scrollTrigger: {
        trigger: wrap,
        start: 'top bottom',
        end: 'bottom top',
        scrub: 1,
      },
    });

    // ── Render loop ───────────────────────────────────
    const clock = new THREE.Clock();
    let raf = 0;
    const render = () => {
      raf = requestAnimationFrame(render);
      material.uniforms.uTime.value = clock.getElapsedTime();
      renderer.render(scene, camera);
    };
    render();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      wrap.removeEventListener('mouseenter', onEnter);
      wrap.removeEventListener('mouseleave', onLeave);
      wrap.removeEventListener('mousemove', onMove);
      scrollTween.scrollTrigger?.kill();
      material.dispose();
      texture.dispose();
      plane.geometry.dispose();
      renderer.dispose();
    };
  }, [src, seed, scrollStrength, reduced]);

  if (reduced) {
    return (
      <figure className={className}>
        <img src={src} alt={alt} className="w-full h-auto block" loading="lazy" />
        {caption && (
          <figcaption className="mt-3 text-[11px] tracking-[0.3em] uppercase opacity-60">
            {caption}
          </figcaption>
        )}
      </figure>
    );
  }

  return (
    <figure ref={wrapRef} className={`relative cursor-pointer ${className}`}>
      <canvas ref={canvasRef} className="w-full h-full block" />
      {caption && (
        <figcaption className="absolute -bottom-10 left-0 text-[11px] tracking-[0.3em] uppercase opacity-60">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

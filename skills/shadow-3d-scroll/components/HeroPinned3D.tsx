import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { gsap, ScrollTrigger } from './lib/gsapSetup';
import { useReducedMotion } from './lib/useReducedMotion';

interface HeroPinned3DProps {
  /** Optional GLB model URL. If omitted, renders a styled cylinder (coaster) placeholder. */
  modelUrl?: string;
  title: string;
  eyebrow?: string;
  /** Scroll distance for pin, expressed as viewport multiples. Default 3.5 (= 350vh) */
  pinScale?: number;
}

/**
 * Pinned 3D hero — the oryzo.ai opening pattern.
 *
 * The model rotates, camera pulls back, and copy fades as the user scrolls
 * through `pinScale * 100vh` of content. The section pins for the duration.
 *
 * Marketing routes only.
 */
export default function HeroPinned3D({
  modelUrl,
  title,
  eyebrow = 'SHADOW MARKET',
  pinScale = 3.5,
}: HeroPinned3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const copyRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const canvas = canvasRef.current;
    const section = sectionRef.current;
    if (!canvas || !section) return;

    // ── Scene ───────────────────────────────────────────────
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0a0a, 4, 15);

    const camera = new THREE.PerspectiveCamera(
      35,
      window.innerWidth / window.innerHeight,
      0.1,
      100
    );
    camera.position.set(0, 0, 6);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // ── Three-point lighting ─────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.25));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(4, 4, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x8899bb, 0.6);
    fill.position.set(-4, 0, 2);
    scene.add(fill);
    const rim = new THREE.DirectionalLight(0xffd5a0, 1.0);
    rim.position.set(0, -2, -4);
    scene.add(rim);

    // ── Focal group (placeholder coaster by default) ────
    const group = new THREE.Group();
    group.rotation.set(-0.3, 0.4, 0);
    scene.add(group);

    let modelDisposer: (() => void) | null = null;

    if (modelUrl) {
      // Lazy-load GLTFLoader only if a model is provided
      import('three/examples/jsm/loaders/GLTFLoader.js').then(({ GLTFLoader }) => {
        const loader = new GLTFLoader();
        loader.load(modelUrl, (gltf) => {
          group.add(gltf.scene);
          modelDisposer = () => {
            gltf.scene.traverse((obj) => {
              if ((obj as THREE.Mesh).isMesh) {
                const mesh = obj as THREE.Mesh;
                mesh.geometry?.dispose();
                const material = mesh.material as THREE.Material | THREE.Material[];
                if (Array.isArray(material)) material.forEach((m) => m.dispose());
                else material?.dispose();
              }
            });
          };
        });
      });
    } else {
      // Placeholder: cork coaster
      const body = new THREE.Mesh(
        new THREE.CylinderGeometry(1.5, 1.5, 0.18, 96),
        new THREE.MeshStandardMaterial({ color: 0xc9a074, roughness: 0.85 })
      );
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(1.3, 0.02, 16, 96),
        new THREE.MeshStandardMaterial({ color: 0x8b6a4a, roughness: 0.5 })
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.091;
      group.add(body, ring);
      modelDisposer = () => {
        body.geometry.dispose();
        (body.material as THREE.Material).dispose();
        ring.geometry.dispose();
        (ring.material as THREE.Material).dispose();
      };
    }

    // ── Render loop ─────────────────────────────────────
    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();

    // ── Scroll timeline ─────────────────────────────────
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: `+=${pinScale * 100}%`,
          pin: true,
          scrub: 1,
          anticipatePin: 1,
        },
      });

      tl.to(group.rotation, { y: group.rotation.y + Math.PI * 2, ease: 'none' }, 0);
      tl.to(group.rotation, { x: 0, ease: 'power2.inOut' }, 0);
      tl.to(camera.position, { z: 9, ease: 'power2.inOut' }, 0.3);
      tl.to(group.scale, { x: 1.15, y: 1.15, z: 1.15, ease: 'power2.out' }, 0.5);
      if (copyRef.current) {
        tl.to(copyRef.current, { opacity: 0, ease: 'none' }, 0.7);
      }
    }, section);

    // ── Resize ─────────────────────────────────────────
    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      ctx.revert();
      modelDisposer?.();
      renderer.dispose();
    };
  }, [modelUrl, pinScale, reduced]);

  // Reduced-motion fallback
  if (reduced) {
    return (
      <section className="min-h-screen flex items-center justify-center px-[5vw] py-[15vh] bg-neutral-950 text-neutral-100">
        <div>
          <div className="text-xs tracking-[0.3em] uppercase opacity-70 mb-8">{eyebrow}</div>
          <h1 className="font-serif text-5xl md:text-7xl leading-none max-w-[14ch]">{title}</h1>
        </div>
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      className="relative h-screen w-full bg-neutral-950 text-neutral-100 overflow-hidden"
    >
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      <div
        ref={copyRef}
        className="relative z-10 h-screen flex flex-col justify-between p-[5vw] pointer-events-none"
      >
        <div className="text-xs tracking-[0.3em] uppercase opacity-70">{eyebrow}</div>
        <h1 className="font-serif font-normal text-5xl md:text-7xl lg:text-8xl leading-[0.95] tracking-tight max-w-[14ch]">
          {title}
        </h1>
        <div className="text-xs tracking-[0.3em] uppercase opacity-50 self-center">
          scroll ↓
        </div>
      </div>
    </section>
  );
}

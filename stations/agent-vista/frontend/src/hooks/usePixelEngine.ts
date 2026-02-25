// Main hook: binds canvas ref → Camera + Renderer lifecycle + rAF loop

import { useEffect, useRef } from 'react';
import { Camera } from '../engine/Camera';
import { Renderer } from '../engine/Renderer';
import { useOfficeStore } from '../stores/officeStore';
import { useAgentStore } from '../stores/agentStore';

export function usePixelEngine(canvasRef: React.RefObject<HTMLCanvasElement | null>) {
  const cameraRef = useRef<Camera | null>(null);
  const rendererRef = useRef<Renderer | null>(null);
  const rafRef = useRef(0);
  const lastTimeRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const camera = new Camera();
    camera.attach(canvas);
    cameraRef.current = camera;

    const renderer = new Renderer(canvas, camera);
    rendererRef.current = renderer;

    // Center camera on office
    const { map } = useOfficeStore.getState();
    const officeW = map.width * 16 * camera.zoom;
    const officeH = map.height * 16 * camera.zoom;
    camera.x = (officeW - window.innerWidth) / 2;
    camera.y = (officeH - window.innerHeight) / 2;

    lastTimeRef.current = performance.now();

    function loop(now: number) {
      const dt = Math.min(now - lastTimeRef.current, 100);
      lastTimeRef.current = now;

      const { map, furniture, seats, restZone, editMode, selectedFurnitureIndex, selectedSeatIndex } = useOfficeStore.getState();
      const { agents } = useAgentStore.getState();

      renderer.render(dt, map, furniture, seats, agents, editMode, restZone, selectedFurnitureIndex, selectedSeatIndex);

      rafRef.current = requestAnimationFrame(loop);
    }

    rafRef.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(rafRef.current);
      camera.detach(canvas);
    };
  }, [canvasRef]);

  return { cameraRef };
}

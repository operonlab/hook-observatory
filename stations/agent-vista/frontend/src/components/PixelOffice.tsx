// Main canvas component — the pixel office viewport + interactive bubble overlay

import { useRef, useState, useEffect } from 'react';
import { usePixelEngine } from '../hooks/usePixelEngine';
import { useLayoutEditor } from '../hooks/useLayoutEditor';
import BubbleOverlay from './BubbleOverlay';
import Minimap from './Minimap';
import TimelineBar from './TimelineBar';
import GestureTutorial from './GestureTutorial';
import { useUIStore } from '../stores/uiStore';
import { useBreakpoint } from '../hooks/useBreakpoint';

export default function PixelOffice() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { cameraRef } = usePixelEngine(canvasRef);
  useLayoutEditor(canvasRef, cameraRef);

  const minimapVisible = useUIStore(s => s.minimapVisible);
  const bp = useBreakpoint();

  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // M key toggles minimap visibility
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'm' || e.key === 'M') {
        // Don't toggle if user is typing in an input
        if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;
        useUIStore.getState().toggleMinimap();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <canvas
        ref={canvasRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          imageRendering: 'pixelated',
        }}
      />
      <BubbleOverlay canvasRef={canvasRef} cameraRef={cameraRef} />
      {minimapVisible && bp !== 'mobile' && (
        <Minimap cameraRef={cameraRef} canvasWidth={size.w} canvasHeight={size.h} />
      )}
      <TimelineBar />
      <GestureTutorial />
    </>
  );
}

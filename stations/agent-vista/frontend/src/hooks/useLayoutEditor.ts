// Layout editor hook — drag furniture/seats on the canvas in edit mode
// Supports: right-click drag to move, left-click to select, keyboard shortcuts

import { useEffect, useRef, useCallback } from 'react';
import { Camera } from '../engine/Camera';
import { TILE } from '../engine/TileMap';
import { useOfficeStore } from '../stores/officeStore';

type DragTarget =
  | { kind: 'furniture'; index: number }
  | { kind: 'seat'; index: number }
  | null;

export function useLayoutEditor(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  cameraRef: React.RefObject<Camera | null>,
) {
  const dragRef = useRef<DragTarget>(null);
  const selectedRef = useRef<DragTarget>(null);
  const editMode = useOfficeStore(s => s.editMode);

  const screenToTile = useCallback((sx: number, sy: number): { tx: number; ty: number } | null => {
    const cam = cameraRef.current;
    if (!cam) return null;
    const { wx, wy } = cam.screenToWorld(sx, sy);
    return { tx: Math.floor(wx / TILE), ty: Math.floor(wy / TILE) };
  }, [cameraRef]);

  // Hit-test furniture using rotation-aware dimensions
  const hitTestFurniture = useCallback((tx: number, ty: number): number => {
    const { furniture } = useOfficeStore.getState();
    for (let i = 0; i < furniture.length; i++) {
      const f = furniture[i];
      const rot = f.rotation ?? 0;
      const rw = (rot === 90 || rot === 270) ? f.h : f.w;
      const rh = (rot === 90 || rot === 270) ? f.w : f.h;
      if (tx >= f.tileX && tx < f.tileX + rw &&
          ty >= f.tileY && ty < f.tileY + rh) {
        return i;
      }
    }
    return -1;
  }, []);

  // Hit-test seats
  const hitTestSeat = useCallback((tx: number, ty: number): number => {
    const { seats } = useOfficeStore.getState();
    for (let i = 0; i < seats.length; i++) {
      if (seats[i].tileX === tx && seats[i].tileY === ty) {
        return i;
      }
    }
    return -1;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !editMode) return;

    const onDown = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const tile = screenToTile(e.clientX - rect.left, e.clientY - rect.top);
      if (!tile) return;

      const { selectFurniture, selectSeat } = useOfficeStore.getState();

      if (e.button === 2) {
        // Right-click: start drag for moving
        e.preventDefault();
        const fi = hitTestFurniture(tile.tx, tile.ty);
        if (fi !== -1) {
          dragRef.current = { kind: 'furniture', index: fi };
          return;
        }
        const si = hitTestSeat(tile.tx, tile.ty);
        if (si !== -1) {
          dragRef.current = { kind: 'seat', index: si };
          return;
        }
      } else if (e.button === 0) {
        // Left-click: select furniture or seat
        const fi = hitTestFurniture(tile.tx, tile.ty);
        if (fi !== -1) {
          selectedRef.current = { kind: 'furniture', index: fi };
          selectFurniture(fi);
          return;
        }
        const si = hitTestSeat(tile.tx, tile.ty);
        if (si !== -1) {
          selectedRef.current = { kind: 'seat', index: si };
          selectSeat(si);
          return;
        }
        // Click on empty tile — deselect
        selectedRef.current = null;
        selectFurniture(-1);
        selectSeat(-1);
      }
    };

    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const rect = canvas.getBoundingClientRect();
      const tile = screenToTile(e.clientX - rect.left, e.clientY - rect.top);
      if (!tile) return;

      const { moveFurniture, moveSeat } = useOfficeStore.getState();
      if (dragRef.current.kind === 'furniture') {
        moveFurniture(dragRef.current.index, tile.tx, tile.ty);
      } else {
        moveSeat(dragRef.current.index, tile.tx, tile.ty);
      }
    };

    const onUp = () => {
      dragRef.current = null;
    };

    const onCtx = (e: MouseEvent) => {
      if (editMode) e.preventDefault();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      const sel = selectedRef.current;
      if (!sel) return;

      const { rotateFurniture, resizeFurniture, selectFurniture, selectSeat } =
        useOfficeStore.getState();

      if (e.key === 'Escape') {
        // Deselect
        selectedRef.current = null;
        selectFurniture(-1);
        selectSeat(-1);
        return;
      }

      // Keyboard shortcuts only apply to furniture
      if (sel.kind !== 'furniture') return;

      if (e.key === 'r' || e.key === 'R') {
        rotateFurniture(sel.index);
        return;
      }

      // Resize: ] increases width, [ decreases width
      // Shift+] (i.e. }) increases height, Shift+[ (i.e. {) decreases height
      if (e.key === ']') {
        resizeFurniture(sel.index, 1, 0);
        return;
      }
      if (e.key === '[') {
        resizeFurniture(sel.index, -1, 0);
        return;
      }
      if (e.key === '}') {
        resizeFurniture(sel.index, 0, 1);
        return;
      }
      if (e.key === '{') {
        resizeFurniture(sel.index, 0, -1);
        return;
      }
    };

    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    canvas.addEventListener('contextmenu', onCtx);
    window.addEventListener('keydown', onKeyDown);

    return () => {
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      canvas.removeEventListener('contextmenu', onCtx);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [canvasRef, editMode, screenToTile, hitTestFurniture, hitTestSeat]);
}

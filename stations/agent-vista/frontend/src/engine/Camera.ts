// Camera with integer zoom + pan (drag) + touch support + inertia + double-tap zoom

export class Camera {
  x = 0;
  y = 0;
  zoom = 2;

  private minZoom = 1;
  private maxZoom = 4;
  private dragging = false;
  private lastX = 0;
  private lastY = 0;

  // Touch state
  private touchDragging = false;
  private touchLastX = 0;
  private touchLastY = 0;
  private pinchDist = 0;

  // Inertia state
  private velocityX = 0;
  private velocityY = 0;
  private inertiaRaf = 0;
  private static readonly FRICTION = 0.92;
  private static readonly MIN_VELOCITY = 0.5;

  // Double-tap state
  private lastTapTime = 0;
  private lastTapX = 0;
  private lastTapY = 0;
  private touchStartX = 0;
  private touchStartY = 0;
  private static readonly DOUBLE_TAP_MS = 300;
  private static readonly TAP_MOVE_THRESHOLD = 10;

  attach(canvas: HTMLCanvasElement) {
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('mousedown', this.onDown);
    window.addEventListener('mousemove', this.onMove);
    window.addEventListener('mouseup', this.onUp);
    // Touch
    canvas.addEventListener('touchstart', this.onTouchStart, { passive: false });
    canvas.addEventListener('touchmove', this.onTouchMove, { passive: false });
    canvas.addEventListener('touchend', this.onTouchEnd);
    canvas.addEventListener('touchcancel', this.onTouchEnd);
  }

  detach(canvas: HTMLCanvasElement) {
    cancelAnimationFrame(this.inertiaRaf);
    canvas.removeEventListener('wheel', this.onWheel);
    canvas.removeEventListener('mousedown', this.onDown);
    window.removeEventListener('mousemove', this.onMove);
    window.removeEventListener('mouseup', this.onUp);
    canvas.removeEventListener('touchstart', this.onTouchStart);
    canvas.removeEventListener('touchmove', this.onTouchMove);
    canvas.removeEventListener('touchend', this.onTouchEnd);
    canvas.removeEventListener('touchcancel', this.onTouchEnd);
  }

  /** Screen pixel → world pixel (before tile division) */
  screenToWorld(sx: number, sy: number): { wx: number; wy: number } {
    return { wx: (sx + this.x) / this.zoom, wy: (sy + this.y) / this.zoom };
  }

  /** World pixel → screen pixel */
  worldToScreen(wx: number, wy: number): { sx: number; sy: number } {
    return { sx: wx * this.zoom - this.x, sy: wy * this.zoom - this.y };
  }

  /** Get current viewport rectangle in world coordinates */
  getViewportRect(canvasWidth: number, canvasHeight: number): { x: number; y: number; w: number; h: number } {
    const { wx: x, wy: y } = this.screenToWorld(0, 0);
    const { wx: x2, wy: y2 } = this.screenToWorld(canvasWidth, canvasHeight);
    return { x, y, w: x2 - x, h: y2 - y };
  }

  /** Set camera position to center on world coordinates */
  centerOn(wx: number, wy: number, canvasWidth: number, canvasHeight: number) {
    this.x = wx * this.zoom - canvasWidth / 2;
    this.y = wy * this.zoom - canvasHeight / 2;
  }

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const prev = this.zoom;
    this.zoom = e.deltaY < 0
      ? Math.min(this.maxZoom, this.zoom + 1)
      : Math.max(this.minZoom, this.zoom - 1);
    // Keep cursor point stable
    if (this.zoom !== prev) {
      const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      this.x = (this.x + cx) * this.zoom / prev - cx;
      this.y = (this.y + cy) * this.zoom / prev - cy;
    }
  };

  private onDown = (e: MouseEvent) => {
    if (e.button === 0) {
      this.dragging = true;
      this.lastX = e.clientX;
      this.lastY = e.clientY;
    }
  };

  private onMove = (e: MouseEvent) => {
    if (!this.dragging) return;
    this.x -= e.clientX - this.lastX;
    this.y -= e.clientY - this.lastY;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
  };

  private onUp = () => {
    this.dragging = false;
  };

  // ── Touch handlers ──

  private onTouchStart = (e: TouchEvent) => {
    e.preventDefault();
    // Cancel inertia on new touch
    cancelAnimationFrame(this.inertiaRaf);
    this.velocityX = 0;
    this.velocityY = 0;

    if (e.touches.length === 1) {
      this.touchDragging = true;
      this.touchLastX = e.touches[0].clientX;
      this.touchLastY = e.touches[0].clientY;
      this.touchStartX = e.touches[0].clientX;
      this.touchStartY = e.touches[0].clientY;
    } else if (e.touches.length === 2) {
      this.touchDragging = false;
      this.pinchDist = this.getTouchDist(e.touches);
      // Store midpoint for zoom anchor
      this.touchLastX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
      this.touchLastY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    }
  };

  private onTouchMove = (e: TouchEvent) => {
    e.preventDefault();
    if (e.touches.length === 1 && this.touchDragging) {
      // Single finger pan + track velocity for inertia
      const tx = e.touches[0].clientX;
      const ty = e.touches[0].clientY;
      const dx = tx - this.touchLastX;
      const dy = ty - this.touchLastY;
      this.x -= dx;
      this.y -= dy;
      // Exponential moving average for smooth velocity
      this.velocityX = 0.6 * dx + 0.4 * this.velocityX;
      this.velocityY = 0.6 * dy + 0.4 * this.velocityY;
      this.touchLastX = tx;
      this.touchLastY = ty;
    } else if (e.touches.length === 2) {
      // Pinch zoom (integer steps)
      const newDist = this.getTouchDist(e.touches);
      const ratio = newDist / this.pinchDist;
      const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
      const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;

      if (ratio > 1.3 && this.zoom < this.maxZoom) {
        const prev = this.zoom;
        this.zoom = Math.min(this.maxZoom, this.zoom + 1);
        this.x = (this.x + midX) * this.zoom / prev - midX;
        this.y = (this.y + midY) * this.zoom / prev - midY;
        this.pinchDist = newDist;
      } else if (ratio < 0.7 && this.zoom > this.minZoom) {
        const prev = this.zoom;
        this.zoom = Math.max(this.minZoom, this.zoom - 1);
        this.x = (this.x + midX) * this.zoom / prev - midX;
        this.y = (this.y + midY) * this.zoom / prev - midY;
        this.pinchDist = newDist;
      }

      // Also pan with pinch midpoint
      this.x -= midX - this.touchLastX;
      this.y -= midY - this.touchLastY;
      this.touchLastX = midX;
      this.touchLastY = midY;
    }
  };

  private onTouchEnd = (e: TouchEvent) => {
    // Double-tap detection (single finger, small displacement = tap)
    if (e.changedTouches.length === 1 && this.touchDragging) {
      const tx = e.changedTouches[0].clientX;
      const ty = e.changedTouches[0].clientY;
      const moved = Math.sqrt(
        (tx - this.touchStartX) ** 2 + (ty - this.touchStartY) ** 2,
      );
      if (moved < Camera.TAP_MOVE_THRESHOLD) {
        const now = performance.now();
        const elapsed = now - this.lastTapTime;
        const tapDist = Math.sqrt(
          (tx - this.lastTapX) ** 2 + (ty - this.lastTapY) ** 2,
        );
        if (elapsed < Camera.DOUBLE_TAP_MS && tapDist < 50) {
          // Double-tap: toggle zoom 1↔2, centered on tap point
          const prev = this.zoom;
          this.zoom = prev === 1 ? 2 : 1;
          this.x = (this.x + tx) * this.zoom / prev - tx;
          this.y = (this.y + ty) * this.zoom / prev - ty;
          this.lastTapTime = 0; // Reset to prevent triple-tap
          this.velocityX = 0;
          this.velocityY = 0;
        } else {
          this.lastTapTime = now;
          this.lastTapX = tx;
          this.lastTapY = ty;
        }
      }
    }

    // Launch inertia if velocity is significant
    if (this.touchDragging && (Math.abs(this.velocityX) > Camera.MIN_VELOCITY || Math.abs(this.velocityY) > Camera.MIN_VELOCITY)) {
      this.startInertia();
    } else {
      this.velocityX = 0;
      this.velocityY = 0;
    }

    this.touchDragging = false;
    this.pinchDist = 0;
  };

  private startInertia() {
    const step = () => {
      this.x -= this.velocityX;
      this.y -= this.velocityY;
      this.velocityX *= Camera.FRICTION;
      this.velocityY *= Camera.FRICTION;
      if (Math.abs(this.velocityX) > Camera.MIN_VELOCITY || Math.abs(this.velocityY) > Camera.MIN_VELOCITY) {
        this.inertiaRaf = requestAnimationFrame(step);
      }
    };
    this.inertiaRaf = requestAnimationFrame(step);
  }

  private getTouchDist(touches: TouchList): number {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }
}

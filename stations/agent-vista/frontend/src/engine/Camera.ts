// Camera with integer zoom + pan (drag)

export class Camera {
  x = 0;
  y = 0;
  zoom = 2;

  private minZoom = 1;
  private maxZoom = 4;
  private dragging = false;
  private lastX = 0;
  private lastY = 0;

  attach(canvas: HTMLCanvasElement) {
    canvas.addEventListener('wheel', this.onWheel, { passive: false });
    canvas.addEventListener('mousedown', this.onDown);
    window.addEventListener('mousemove', this.onMove);
    window.addEventListener('mouseup', this.onUp);
  }

  detach(canvas: HTMLCanvasElement) {
    canvas.removeEventListener('wheel', this.onWheel);
    canvas.removeEventListener('mousedown', this.onDown);
    window.removeEventListener('mousemove', this.onMove);
    window.removeEventListener('mouseup', this.onUp);
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
}

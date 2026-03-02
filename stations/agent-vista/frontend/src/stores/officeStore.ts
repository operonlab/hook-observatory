// Office layout store — tile map, furniture, seats, rest zone, edit mode

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  createDefaultOffice,
  rebuildWalkableGrid,
  type TileMapData,
  type FurnitureDef,
  type SeatDef,
  type RestZone,
  type DoorDef,
  type RoomId,
} from '../engine/TileMap';

interface OfficeState {
  map: TileMapData;
  furniture: FurnitureDef[];
  seats: SeatDef[];
  restZone: RestZone;
  door: DoorDef;
  seatAssignments: Map<string, number>;
  restAssignments: Map<string, number>; // agentId → rest seat index

  // Edit mode
  editMode: boolean;
  toggleEditMode: () => void;
  moveFurniture: (index: number, tileX: number, tileY: number) => void;
  moveSeat: (index: number, tileX: number, tileY: number) => void;
  rotateFurniture: (index: number) => void;
  resizeFurniture: (index: number, dw: number, dh: number) => void;

  // Selection state for highlighting in renderer
  selectedFurnitureIndex: number;
  selectedSeatIndex: number;
  selectFurniture: (index: number) => void;
  selectSeat: (index: number) => void;

  // Persistence
  saveLayout: () => Promise<boolean>;
  loadLayout: () => Promise<boolean>;
  layoutVersion: number;
  layoutSaving: boolean;

  claimSeat: (agentId: string, preferredRoom?: RoomId) => SeatDef | null;
  releaseSeat: (agentId: string) => void;
  claimRestSpot: (agentId: string) => { x: number; y: number } | null;
  releaseRestSpot: (agentId: string) => void;
}

const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '');
const defaults = createDefaultOffice();

export const useOfficeStore = create<OfficeState>()(persist((set, get) => ({
  map: defaults.map,
  furniture: defaults.furniture,
  seats: defaults.seats,
  restZone: defaults.restZone,
  door: defaults.door,
  seatAssignments: new Map(),
  restAssignments: new Map(),
  editMode: false,
  selectedFurnitureIndex: -1,
  selectedSeatIndex: -1,
  layoutVersion: 0,
  layoutSaving: false,

  toggleEditMode() {
    set({ editMode: !get().editMode });
  },

  moveFurniture(index, tileX, tileY) {
    const { furniture, map } = get();
    if (index < 0 || index >= furniture.length) return;
    if (tileX < 0 || tileY < 0 || tileX >= map.width || tileY >= map.height) return;

    const next = [...furniture];
    const old = next[index];

    // Compute rotation-aware physical footprint for old position
    const rot = old.rotation ?? 0;
    const rw = (rot === 90 || rot === 270) ? old.h : old.w;
    const rh = (rot === 90 || rot === 270) ? old.w : old.h;

    // Restore old tiles as walkable
    const walkable = map.walkable.map(row => [...row]);
    for (let dy = 0; dy < rh; dy++) {
      for (let dx = 0; dx < rw; dx++) {
        walkable[old.tileY + dy][old.tileX + dx] = true;
      }
    }
    // Mark new tiles as non-walkable (same rotation, same physical footprint)
    for (let dy = 0; dy < rh; dy++) {
      for (let dx = 0; dx < rw; dx++) {
        const ny = tileY + dy, nx = tileX + dx;
        if (ny >= map.height || nx >= map.width) return; // out of bounds
        walkable[ny][nx] = false;
      }
    }

    next[index] = { ...old, tileX, tileY };
    set({ furniture: next, map: { ...map, walkable } });
  },

  moveSeat(index, tileX, tileY) {
    const { seats, map } = get();
    if (index < 0 || index >= seats.length) return;
    if (tileX < 0 || tileY < 0 || tileX >= map.width || tileY >= map.height) return;
    if (!map.walkable[tileY][tileX]) return; // can't place seat on non-walkable

    const next = [...seats];
    next[index] = { ...next[index], tileX, tileY };
    set({ seats: next });
  },

  rotateFurniture(index) {
    const { furniture, map } = get();
    if (index < 0 || index >= furniture.length) return;

    const next = [...furniture];
    const old = next[index];

    // Current rotation-aware footprint (before rotation)
    const oldRot = old.rotation ?? 0;
    const oldRw = (oldRot === 90 || oldRot === 270) ? old.h : old.w;
    const oldRh = (oldRot === 90 || oldRot === 270) ? old.w : old.h;

    // Cycle rotation: 0→90→180→270→0
    const rotationMap: Record<number, 0 | 90 | 180 | 270> = { 0: 90, 90: 180, 180: 270, 270: 0 };
    const newRot = rotationMap[oldRot];

    // New rotation-aware footprint (after rotation)
    const newRw = (newRot === 90 || newRot === 270) ? old.h : old.w;
    const newRh = (newRot === 90 || newRot === 270) ? old.w : old.h;

    // Bounds check: new footprint must fit within map
    if (old.tileX + newRw > map.width || old.tileY + newRh > map.height) return;

    // Restore old footprint as walkable
    const walkable = map.walkable.map(row => [...row]);
    for (let dy = 0; dy < oldRh; dy++) {
      for (let dx = 0; dx < oldRw; dx++) {
        walkable[old.tileY + dy][old.tileX + dx] = true;
      }
    }
    // Mark new footprint as non-walkable
    for (let dy = 0; dy < newRh; dy++) {
      for (let dx = 0; dx < newRw; dx++) {
        walkable[old.tileY + dy][old.tileX + dx] = false;
      }
    }

    next[index] = { ...old, rotation: newRot };
    set({ furniture: next, map: { ...map, walkable } });
  },

  resizeFurniture(index, dw, dh) {
    const { furniture, map } = get();
    if (index < 0 || index >= furniture.length) return;

    const next = [...furniture];
    const old = next[index];

    const newW = Math.max(1, old.w + dw);
    const newH = Math.max(1, old.h + dh);

    // Compute rotation-aware physical footprint for old and new sizes
    const rot = old.rotation ?? 0;
    const oldRw = (rot === 90 || rot === 270) ? old.h : old.w;
    const oldRh = (rot === 90 || rot === 270) ? old.w : old.h;
    const newRw = (rot === 90 || rot === 270) ? newH : newW;
    const newRh = (rot === 90 || rot === 270) ? newW : newH;

    // Bounds check: new footprint must fit within map
    if (old.tileX + newRw > map.width || old.tileY + newRh > map.height) return;

    // Restore old footprint as walkable
    const walkable = map.walkable.map(row => [...row]);
    for (let dy = 0; dy < oldRh; dy++) {
      for (let dx = 0; dx < oldRw; dx++) {
        walkable[old.tileY + dy][old.tileX + dx] = true;
      }
    }
    // Mark new footprint as non-walkable
    for (let dy = 0; dy < newRh; dy++) {
      for (let dx = 0; dx < newRw; dx++) {
        const ny = old.tileY + dy, nx = old.tileX + dx;
        if (ny >= map.height || nx >= map.width) return; // out of bounds mid-loop, abort
        walkable[ny][nx] = false;
      }
    }

    next[index] = { ...old, w: newW, h: newH };
    set({ furniture: next, map: { ...map, walkable } });
  },

  selectFurniture(index) {
    set({ selectedFurnitureIndex: index, selectedSeatIndex: -1 });
  },

  selectSeat(index) {
    set({ selectedSeatIndex: index, selectedFurnitureIndex: -1 });
  },

  async saveLayout() {
    const { furniture, seats, restZone, door, map } = get();
    set({ layoutSaving: true });
    try {
      const body = {
        grid_width: map.width,
        grid_height: map.height,
        furniture: furniture.map(f => ({
          type: f.type, tileX: f.tileX, tileY: f.tileY,
          w: f.w, h: f.h, rotation: f.rotation ?? 0,
        })),
        seats: seats.map(s => ({
          tileX: s.tileX, tileY: s.tileY, direction: s.direction, room: s.room,
        })),
        rest_zone: restZone,
        door_x: door.x,
        door_y: door.y,
      };
      const res = await fetch(`${API_BASE}/api/layout`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const row = await res.json();
        set({ layoutVersion: row.version, layoutSaving: false });
        return true;
      }
      set({ layoutSaving: false });
      return false;
    } catch {
      set({ layoutSaving: false });
      return false;
    }
  },

  async loadLayout() {
    try {
      const res = await fetch(`${API_BASE}/api/layout`);
      if (res.status === 404) return false; // no saved layout
      if (!res.ok) return false;
      const row = await res.json();
      const data = row.data;
      const furniture: FurnitureDef[] = (data.furniture ?? []).map((f: Record<string, unknown>) => ({
        type: f.type as string,
        tileX: f.tileX as number,
        tileY: f.tileY as number,
        w: f.w as number,
        h: f.h as number,
        rotation: (f.rotation as number) || 0,
      }));
      const seats: SeatDef[] = (data.seats ?? []).map((s: Record<string, unknown>) => ({
        tileX: s.tileX as number,
        tileY: s.tileY as number,
        direction: s.direction as SeatDef['direction'],
        room: (s.room as RoomId) ?? 'claude_studio',
      }));
      const restZone: RestZone = data.rest_zone ?? { seats: [] };
      const door: DoorDef = { x: data.door_x ?? 24, y: data.door_y ?? 0 };
      const W = data.grid_width ?? 50;
      const H = data.grid_height ?? 34;
      const walkable = rebuildWalkableGrid(W, H, furniture);
      set({
        furniture, seats, restZone, door,
        map: { width: W, height: H, walkable },
        layoutVersion: row.version,
      });
      return true;
    } catch {
      return false;
    }
  },

  claimSeat(agentId: string, preferredRoom?: RoomId) {
    const { seats, seatAssignments } = get();
    if (seatAssignments.has(agentId)) {
      return seats[seatAssignments.get(agentId)!];
    }
    const taken = new Set(seatAssignments.values());

    // First pass: try preferred room
    if (preferredRoom) {
      for (let i = 0; i < seats.length; i++) {
        if (!taken.has(i) && seats[i].room === preferredRoom) {
          const next = new Map(seatAssignments);
          next.set(agentId, i);
          set({ seatAssignments: next });
          return seats[i];
        }
      }
    }

    // Second pass: any available seat
    for (let i = 0; i < seats.length; i++) {
      if (!taken.has(i)) {
        const next = new Map(seatAssignments);
        next.set(agentId, i);
        set({ seatAssignments: next });
        return seats[i];
      }
    }
    return null;
  },

  releaseSeat(agentId: string) {
    const next = new Map(get().seatAssignments);
    next.delete(agentId);
    set({ seatAssignments: next });
  },

  claimRestSpot(agentId: string) {
    const { restZone, restAssignments } = get();
    if (restAssignments.has(agentId)) {
      return restZone.seats[restAssignments.get(agentId)!];
    }
    const taken = new Set(restAssignments.values());
    for (let i = 0; i < restZone.seats.length; i++) {
      if (!taken.has(i)) {
        const next = new Map(restAssignments);
        next.set(agentId, i);
        set({ restAssignments: next });
        return restZone.seats[i];
      }
    }
    // Overflow: pick a random rest spot
    const idx = Math.floor(Math.random() * restZone.seats.length);
    return restZone.seats[idx];
  },

  releaseRestSpot(agentId: string) {
    const next = new Map(get().restAssignments);
    next.delete(agentId);
    set({ restAssignments: next });
  },
}), {
  name: 'agent-vista-office',
  partialize: (state) => ({
    furniture: state.furniture,
    seats: state.seats,
    restZone: state.restZone,
    door: state.door,
    layoutVersion: state.layoutVersion,
  }),
  onRehydrateStorage: () => (state) => {
    if (!state) return;
    const { furniture } = state;
    const W = state.map.width;
    const H = state.map.height;
    state.map = { width: W, height: H, walkable: rebuildWalkableGrid(W, H, furniture) };
  },
}));

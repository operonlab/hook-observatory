// Main Canvas 2D renderer — tiles, furniture, characters, bubbles, effects

import { Camera } from './Camera';
import { TILE, DOOR_POS, REST_AREA, ROOMS, ROOM_DOORS, isInCorridor, type TileMapData, type FurnitureDef, type SeatDef, type RestZone, type RoomId } from './TileMap';
import { type FSMCtx, directionTo, promoteBubble, shortCanvasLabel } from './CharacterFSM';
import { bfsPath, randomWalkableInZone } from './Pathfinding';
import { getSpriteSheet, CHAR_W, CHAR_H, DESK_SPRITE, PLANT_SPRITE, SOFA_SPRITE, CLOCK_SPRITE, BOOKSHELF_SPRITE, BED_SPRITE, WATER_SPRITE, COFFEE_SPRITE, WHITEBOARD_SPRITE, PRINTER_SPRITE, CABINET_SPRITE, type AnimKey, type SpriteFrame } from '../sprites/templates';
import { renderSprite, renderFurniture, clearSpriteCache } from '../sprites/cache';
import { CLI_PALETTES, shiftPalette, type ColorPalette } from '../sprites/palette';
import { getCustomSprite } from '../sprites/custom';
import type { AgentEntry } from '../stores/agentStore';
import { tryMonologue } from './Monologue';
import { useUIStore } from '../stores/uiStore';
import { getDayNightState, type DayNightState } from './DayNight';

const FLOOR_A = '#2A2A3E';        // claude_studio floor (blue-dark)
const FLOOR_B = '#24243A';
const GEMINI_A = '#2E2A3E';       // gemini_lab floor (purple-dark)
const GEMINI_B = '#2A243A';
const CODEX_A = '#2A3E2E';        // codex_lab floor (green-dark)
const CODEX_B = '#243A2A';
const LOUNGE_A = '#2A1832';       // rest_room floor — distinct warm purple
const LOUNGE_B = '#22142C';
const CORRIDOR_A = '#282838';     // corridor floor (neutral)
const CORRIDOR_B = '#222234';
const WALL_COLOR = '#1A1A2E';
const SEAT_COLOR = 'rgba(255,255,255,0.06)';
const REST_SEAT_COLOR = 'rgba(180,140,255,0.08)';
const EDIT_HIGHLIGHT = 'rgba(255,200,50,0.35)';
const EDIT_SEAT_HIGHLIGHT = 'rgba(100,200,255,0.35)';

const WALK_SPEED = 3;
const SPAWN_MS = 800;

/** Derive the visual animation key: use WALK when physically moving during IDLE. */
function visualAnim(fsm: FSMCtx): AnimKey {
  if (fsm.state === 'IDLE' && fsm.path.length > 0 && fsm.pathIdx < fsm.path.length) {
    return 'WALK';
  }
  return fsm.state as AnimKey;
}

export class Renderer {
  private ctx: CanvasRenderingContext2D;
  private prevZoom = -1;
  private cliSessionCounters = new Map<string, number>();

  constructor(
    private canvas: HTMLCanvasElement,
    private camera: Camera,
  ) {
    this.ctx = canvas.getContext('2d')!;
    this.ctx.imageSmoothingEnabled = false;
  }

  render(
    dt: number,
    map: TileMapData,
    furniture: FurnitureDef[],
    seats: SeatDef[],
    agents: Map<string, AgentEntry>,
    editMode = false,
    restZone?: RestZone,
    selectedFurnitureIndex = -1,
    selectedSeatIndex = -1,
  ) {
    const { ctx, camera } = this;
    const { zoom } = camera;

    if (zoom !== this.prevZoom) {
      clearSpriteCache();
      this.prevZoom = zoom;
    }

    const cw = window.innerWidth;
    const ch = window.innerHeight;
    if (this.canvas.width !== cw || this.canvas.height !== ch) {
      this.canvas.width = cw;
      this.canvas.height = ch;
      ctx.imageSmoothingEnabled = false;
    }

    ctx.clearRect(0, 0, cw, ch);

    // 1. Floor
    this.drawFloor(map);

    // 1b. Door portal at entrance + all room door portals
    this.drawDoor(map);
    this.drawRoomDoors();

    // 2. Seat indicators (work desks + rest zone)
    for (let si = 0; si < seats.length; si++) {
      const s = seats[si];
      const { sx, sy } = camera.worldToScreen(s.tileX * TILE, s.tileY * TILE);
      const isSel = editMode && si === selectedSeatIndex;
      ctx.fillStyle = isSel ? 'rgba(100,200,255,0.4)' : editMode ? EDIT_SEAT_HIGHLIGHT : SEAT_COLOR;
      ctx.fillRect(sx, sy, TILE * zoom, TILE * zoom);
    }
    if (restZone) {
      for (const s of restZone.seats) {
        const { sx, sy } = camera.worldToScreen(s.x * TILE, s.y * TILE);
        ctx.fillStyle = editMode ? EDIT_SEAT_HIGHLIGHT : REST_SEAT_COLOR;
        ctx.fillRect(sx, sy, TILE * zoom, TILE * zoom);
      }
    }

    // 3. Z-sort scene
    type SceneObj = { y: number; draw: () => void };
    const scene: SceneObj[] = [];

    for (let fi = 0; fi < furniture.length; fi++) {
      const f = furniture[fi];
      const isSelected = editMode && fi === selectedFurnitureIndex;
      scene.push({ y: f.tileY, draw: () => this.drawFurniture(f, editMode, isSelected) });
    }

    const blocked = new Set<string>();
    for (const [, entry] of agents) {
      blocked.add(`${entry.fsm.pos.x},${entry.fsm.pos.y}`);
    }

    // Update and draw all agents
    for (const [id, entry] of agents) {
      this.updateFSM(entry.fsm, dt, map, blocked);
      tryMonologue(id, entry);
      const customImg = getCustomSprite(entry.agent.cli_type, entry.agent.session_id);
      if (customImg) {
        scene.push({
          y: entry.fsm.pixelY,
          draw: () => {
            this.drawCustomCharacter(entry.fsm, customImg, 1);
            this.drawSelectionHighlight(id, entry.fsm, 1);
          },
        });
      } else {
        const palette = this.getPalette(entry.agent.cli_type, id);
        scene.push({
          y: entry.fsm.pixelY,
          draw: () => {
            this.drawCharacter(entry.fsm, palette, 1);
            this.drawSelectionHighlight(id, entry.fsm, 1);
          },
        });
      }
    }

    scene.sort((a, b) => a.y - b.y);
    for (const obj of scene) obj.draw();

    // 3b. Room door labels + room name labels (above Z-sorted scene)
    this.drawRoomDoorLabels();
    this.drawRoomLabels();

    // 4. Name labels (CLI type + session ID first 4 chars above head)
    for (const [, entry] of agents) {
      this.drawNameLabel(entry);
    }

    // 5. Bubbles (short status label on canvas; full text in expanded overlay)
    for (const [, entry] of agents) {
      const { fsm } = entry;
      if (!fsm.spawning && !fsm.despawning && !fsm.exitTarget) {
        this.drawBubble(entry);
      }
    }

    // 6. Spawn/despawn
    for (const [, entry] of agents) {
      if (entry.fsm.spawning || entry.fsm.despawning) this.drawSpawnEffect(entry.fsm);
    }

    // 7. Sub-agent angels (topmost character layer)
    for (const [, entry] of agents) {
      if (entry.fsm.subAgents.length > 0) {
        this.drawAngels(entry);
      }
    }

    // 8. CLI legend (bottom-left)
    this.drawLegend(agents);

    // 9. Day/Night cycle overlay + window glow + desk lamps
    const dayNight = getDayNightState();
    if (dayNight.overlayA > 0.005) {
      this.drawDayNightOverlay(dayNight);
    }
    if (dayNight.windowGlowIntensity > 0.01) {
      this.drawWindowGlow(map, dayNight);
      this.drawDeskLamps(agents, dayNight);
    }

    // 10. Agent proximity interactions (C2: wave when passing in corridor)
    this.drawProximityInteractions(agents);

    // 11. Edit mode overlay
    if (editMode) this.drawEditOverlay(map);
  }

  // ── Floor ──────────────────────────────────

  private drawFloor(map: TileMapData) {
    const { ctx, camera } = this;
    const z = camera.zoom;

    // Build a set of door-gap positions for fast lookup
    const doorGaps = new Set<string>();
    for (const door of Object.values(ROOM_DOORS)) {
      doorGaps.add(`${door.x},${door.y}`);
    }
    // Main entrance door (2 tiles wide at y=0)
    doorGaps.add(`${DOOR_POS.x},${DOOR_POS.y}`);
    doorGaps.add(`${DOOR_POS.x + 1},${DOOR_POS.y}`);

    for (let ty = 0; ty < map.height; ty++) {
      for (let tx = 0; tx < map.width; tx++) {
        // Determine which zone this tile belongs to
        const inRoom = ROOMS.find(r => tx >= r.x0 && tx <= r.x1 && ty >= r.y0 && ty <= r.y1);
        const inCorr = isInCorridor(tx, ty);

        // Outer boundary walls: x=0, x=49, y=0, y=33
        const isOuterWall = tx === 0 || tx === map.width - 1 || ty === 0 || ty === map.height - 1;

        // Vertical partition walls: x=22 (left side) or x=27 (right side)
        //   within the room y-ranges (y=1..13 for top rooms, y=20..32 for bottom rooms)
        const isPartitionV =
          (tx === 22 || tx === 27) &&
          ((ty >= 1 && ty <= 13) || (ty >= 20 && ty <= 32));

        // Horizontal partition walls: y=14 (top rooms bottom edge) or y=19 (bottom rooms top edge)
        //   within the room x-ranges (x=1..21 for left rooms, x=28..48 for right rooms)
        const isPartitionH =
          (ty === 14 || ty === 19) &&
          ((tx >= 1 && tx <= 21) || (tx >= 28 && tx <= 48));

        const isDoorGap = doorGaps.has(`${tx},${ty}`);
        const isPartitionWall = (isPartitionV || isPartitionH) && !isDoorGap;

        // Skip void tiles (not outer wall, not room, not corridor, not partition)
        if (!isOuterWall && !inRoom && !inCorr && !isPartitionWall) continue;

        const { sx, sy } = camera.worldToScreen(tx * TILE, ty * TILE);
        if (sx + TILE * z < 0 || sy + TILE * z < 0) continue;
        if (sx > this.canvas.width || sy > this.canvas.height) continue;

        if (isOuterWall || isPartitionWall) {
          ctx.fillStyle = WALL_COLOR;
        } else if (inRoom) {
          const id = inRoom.id as RoomId;
          if (id === 'rest_room') {
            ctx.fillStyle = (tx + ty) % 2 === 0 ? LOUNGE_A : LOUNGE_B;
          } else if (id === 'gemini_lab') {
            ctx.fillStyle = (tx + ty) % 2 === 0 ? GEMINI_A : GEMINI_B;
          } else if (id === 'codex_lab') {
            ctx.fillStyle = (tx + ty) % 2 === 0 ? CODEX_A : CODEX_B;
          } else {
            // claude_studio (default blue)
            ctx.fillStyle = (tx + ty) % 2 === 0 ? FLOOR_A : FLOOR_B;
          }
        } else {
          // corridor
          ctx.fillStyle = (tx + ty) % 2 === 0 ? CORRIDOR_A : CORRIDOR_B;
        }

        ctx.fillRect(sx, sy, TILE * z, TILE * z);
        ctx.strokeStyle = 'rgba(255,255,255,0.03)';
        ctx.strokeRect(sx, sy, TILE * z, TILE * z);
      }
    }
  }

  // ── Door Portal ──────────────────────────────

  private drawDoor(_map: TileMapData) {
    const { ctx, camera } = this;
    const z = camera.zoom;
    const dx = DOOR_POS.x;
    const dy = DOOR_POS.y;

    // Door frame (2 tiles wide)
    for (let i = 0; i < 2; i++) {
      const { sx, sy } = camera.worldToScreen((dx + i) * TILE, dy * TILE);
      const tw = TILE * z;
      const th = TILE * z;

      // Outer frame
      ctx.fillStyle = '#3A2A1E';
      ctx.fillRect(sx, sy, tw, th);

      // Inner portal glow
      const inset = tw * 0.15;
      ctx.fillStyle = '#1A0A2E';
      ctx.fillRect(sx + inset, sy + inset * 0.5, tw - inset * 2, th - inset);

      // Portal shimmer effect
      const t = Date.now() / 1000;
      const shimmer = 0.3 + 0.15 * Math.sin(t * 2 + i);
      ctx.fillStyle = `rgba(100, 140, 255, ${shimmer})`;
      ctx.fillRect(sx + inset, sy + inset * 0.5, tw - inset * 2, th - inset);

      // Small light particles
      ctx.fillStyle = `rgba(180, 200, 255, ${0.4 + 0.3 * Math.sin(t * 3 + i * 2)})`;
      const px = sx + tw * 0.3 + Math.sin(t * 1.5 + i) * tw * 0.15;
      const py = sy + th * 0.3 + Math.cos(t * 2 + i) * th * 0.15;
      ctx.fillRect(px, py, z * 2, z * 2);

      const px2 = sx + tw * 0.6 + Math.cos(t * 1.8 + i) * tw * 0.1;
      const py2 = sy + th * 0.6 + Math.sin(t * 2.5 + i) * th * 0.1;
      ctx.fillRect(px2, py2, z * 1.5, z * 1.5);
    }

    // "ENTER" label above door
    const { sx: lx, sy: ly } = camera.worldToScreen((dx + 0.5) * TILE, (dy - 0.3) * TILE);
    const fontSize = Math.max(6, 4 * z);
    ctx.font = `bold ${fontSize}px monospace`;
    ctx.fillStyle = 'rgba(150, 180, 255, 0.6)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText('ENTER', lx + TILE * z * 0.5, ly);
    ctx.textAlign = 'start';
  }

  // ── Room Door Portals (all 8 ROOM_DOORS) ────────────────────────────────

  private drawRoomDoors() {
    const { ctx, camera } = this;
    const z = camera.zoom;
    const t = Date.now() / 1000;

    // Door configurations: [key, isVertical, glowColor]
    const doorDefs: Array<{ key: keyof typeof ROOM_DOORS; isVertical: boolean; glowColor: string }> = [
      // Vertical doors (x=22 or x=27): flush right/left edge of tile
      { key: 'claude_v',  isVertical: true,  glowColor: '100, 140, 255' },
      { key: 'gemini_v',  isVertical: true,  glowColor: '160, 100, 220' },
      { key: 'codex_v',   isVertical: true,  glowColor: '80, 200, 120' },
      { key: 'rest_v',    isVertical: true,  glowColor: '160, 100, 220' },
      // Horizontal doors (y=14 or y=19): flush bottom/top edge of tile
      { key: 'claude_h',  isVertical: false, glowColor: '100, 140, 255' },
      { key: 'gemini_h',  isVertical: false, glowColor: '160, 100, 220' },
      { key: 'codex_h',   isVertical: false, glowColor: '80, 200, 120' },
      { key: 'rest_h',    isVertical: false, glowColor: '160, 100, 220' },
    ];

    for (let di = 0; di < doorDefs.length; di++) {
      const { key, isVertical, glowColor } = doorDefs[di];
      const door = ROOM_DOORS[key];
      const { sx, sy } = camera.worldToScreen(door.x * TILE, door.y * TILE);
      const tw = TILE * z;
      const th = TILE * z;
      const wallFrac = 0.35;
      const inset = Math.max(2, Math.round(z * 1.2));

      if (isVertical) {
        // Vertical wall door — partition is on right 35% (rotation=90) or left 35% (x=27, rotation=270)
        // x=22 doors: partition on RIGHT side (rotation=90), flush right
        // x=27 doors: partition on LEFT side (rotation=270), flush left
        const wallW = Math.round(tw * wallFrac);
        const flushRight = door.x === 22;
        const doorLeft = flushRight ? sx + tw - wallW : sx;

        // Door frame
        ctx.fillStyle = '#3A2518';
        ctx.fillRect(doorLeft, sy, wallW, th);

        // Inner opening
        ctx.fillStyle = '#0E0E1A';
        ctx.fillRect(doorLeft + inset, sy + inset, wallW - inset * 2, th - inset * 2);

        // Portal pulse
        const pulse = 0.2 + 0.1 * Math.sin(t * 1.5 + di);
        ctx.fillStyle = `rgba(${glowColor}, ${pulse})`;
        ctx.fillRect(doorLeft + inset, sy + inset, wallW - inset * 2, th - inset * 2);

        // Particle
        ctx.fillStyle = `rgba(${glowColor}, ${0.35 + 0.2 * Math.sin(t * 2.5 + di)})`;
        const px = doorLeft + wallW * 0.35 + Math.sin(t * 1.8 + di) * wallW * 0.1;
        const py = sy + th * 0.35 + Math.cos(t * 2.2 + di) * th * 0.15;
        ctx.fillRect(px, py, z * 1.5, z * 1.5);
      } else {
        // Horizontal wall door — partition is on bottom 35% (rotation=0, y=14) or top 35% (rotation=180, y=19)
        const wallH = Math.round(th * wallFrac);
        const flushBottom = door.y === 14;
        const doorTop = flushBottom ? sy + th - wallH : sy;

        // Door frame
        ctx.fillStyle = '#3A2518';
        ctx.fillRect(sx, doorTop, tw, wallH);

        // Inner opening
        ctx.fillStyle = '#0E0E1A';
        ctx.fillRect(sx + inset, doorTop + inset, tw - inset * 2, wallH - inset * 2);

        // Portal pulse
        const pulse = 0.2 + 0.1 * Math.sin(t * 1.5 + di);
        ctx.fillStyle = `rgba(${glowColor}, ${pulse})`;
        ctx.fillRect(sx + inset, doorTop + inset, tw - inset * 2, wallH - inset * 2);

        // Particle
        ctx.fillStyle = `rgba(${glowColor}, ${0.35 + 0.2 * Math.sin(t * 2.5 + di)})`;
        const px = sx + tw * 0.35 + Math.sin(t * 1.8 + di) * tw * 0.1;
        const py = doorTop + wallH * 0.35 + Math.cos(t * 2.2 + di) * wallH * 0.15;
        ctx.fillRect(px, py, z * 1.5, z * 1.5);
      }
    }
  }

  /** Door labels for all 8 room doors — drawn after Z-sort so walls don't cover them */
  private drawRoomDoorLabels() {
    const { ctx, camera } = this;
    const z = camera.zoom;

    const labelDefs: Array<{ key: keyof typeof ROOM_DOORS; isVertical: boolean; label: string; color: string }> = [
      { key: 'claude_v',  isVertical: true,  label: 'CODE',     color: 'rgba(100, 160, 255, 0.7)' },
      { key: 'gemini_v',  isVertical: true,  label: 'RESEARCH', color: 'rgba(180, 140, 255, 0.7)' },
      { key: 'codex_v',   isVertical: true,  label: 'BUILD',    color: 'rgba(80, 220, 120, 0.7)' },
      { key: 'rest_v',    isVertical: true,  label: 'REST',     color: 'rgba(180, 140, 255, 0.7)' },
      { key: 'claude_h',  isVertical: false, label: 'CODE',     color: 'rgba(100, 160, 255, 0.7)' },
      { key: 'gemini_h',  isVertical: false, label: 'RESEARCH', color: 'rgba(180, 140, 255, 0.7)' },
      { key: 'codex_h',   isVertical: false, label: 'BUILD',    color: 'rgba(80, 220, 120, 0.7)' },
      { key: 'rest_h',    isVertical: false, label: 'REST',     color: 'rgba(180, 140, 255, 0.7)' },
    ];

    const fontSize = Math.max(6, 3.5 * z);
    ctx.font = `bold ${fontSize}px monospace`;
    ctx.textBaseline = 'bottom';

    for (const { key, isVertical, label, color } of labelDefs) {
      const door = ROOM_DOORS[key];
      const { sx, sy } = camera.worldToScreen(door.x * TILE, door.y * TILE);
      const tw = TILE * z;
      const wallFrac = 0.35;

      ctx.fillStyle = color;
      ctx.textAlign = 'center';

      if (isVertical) {
        const wallW = Math.round(tw * wallFrac);
        const flushRight = door.x === 22;
        const doorCx = flushRight ? sx + tw - wallW / 2 : sx + wallW / 2;
        ctx.fillText(label, doorCx, sy - z * 1.5);
      } else {
        const wallH = Math.round((TILE * z) * wallFrac);
        const flushBottom = door.y === 14;
        const doorCy = flushBottom ? sy + TILE * z - wallH / 2 : sy + wallH / 2;
        ctx.save();
        ctx.translate(sx + tw / 2, doorCy);
        ctx.fillText(label, 0, -z * 1.5);
        ctx.restore();
      }
    }
    ctx.textAlign = 'start';
  }

  /** Room name labels near each room's top wall, drawn above everything */
  private drawRoomLabels() {
    const { ctx, camera } = this;
    const z = camera.zoom;

    // [centerTileX, labelTileY (on the wall tile), displayLabel, color]
    const roomLabels: Array<{ cx: number; ty: number; label: string; color: string }> = [
      { cx: 11,  ty: 0,  label: 'Claude Code Studio', color: 'rgba(120, 180, 255, 0.75)' },
      { cx: 38,  ty: 0,  label: 'Gemini Research Lab', color: 'rgba(200, 160, 255, 0.75)' },
      { cx: 11,  ty: 19, label: 'Codex Build Lab',     color: 'rgba(100, 230, 140, 0.75)' },
      { cx: 38,  ty: 19, label: 'Rest Break Room',     color: 'rgba(200, 140, 255, 0.75)' },
    ];

    const fontSize = Math.max(7, 4.5 * z);
    ctx.font = `bold ${fontSize}px monospace`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';

    for (const { cx, ty, label, color } of roomLabels) {
      const { sx, sy } = camera.worldToScreen(cx * TILE, ty * TILE);
      const midY = sy + (TILE * z) / 2;

      // Background pill
      const tw = ctx.measureText(label).width;
      const pad = 3 * z;
      ctx.fillStyle = 'rgba(10, 10, 20, 0.6)';
      ctx.beginPath();
      ctx.roundRect(sx - tw / 2 - pad, midY - fontSize / 2 - pad * 0.4, tw + pad * 2, fontSize + pad * 0.8, [3]);
      ctx.fill();

      ctx.fillStyle = color;
      ctx.fillText(label, sx, midY);
    }

    ctx.textAlign = 'start';
  }

  // ── Furniture ──────────────────────────────

  private drawFurniture(f: FurnitureDef, editMode: boolean, isSelected = false) {
    const { ctx, camera } = this;
    const z = camera.zoom;
    const rot = f.rotation ?? 0;
    const { sx, sy } = camera.worldToScreen(f.tileX * TILE, f.tileY * TILE);
    // Rotated footprint dimensions
    const rw = (rot === 90 || rot === 270) ? f.h : f.w;
    const rh = (rot === 90 || rot === 270) ? f.w : f.h;

    if (f.type === 'wall') {
      this.drawWallBlock(sx, sy, rot);
    } else {
      const spriteMap: Record<string, SpriteFrame> = {
        desk: DESK_SPRITE, plant: PLANT_SPRITE, sofa: SOFA_SPRITE,
        clock: CLOCK_SPRITE, bookshelf: BOOKSHELF_SPRITE, bed: BED_SPRITE,
        water_dispenser: WATER_SPRITE, coffee_machine: COFFEE_SPRITE,
        whiteboard: WHITEBOARD_SPRITE, printer: PRINTER_SPRITE, cabinet: CABINET_SPRITE,
      };
      const sprite = spriteMap[f.type] ?? DESK_SPRITE;
      const rendered = renderFurniture(sprite, f.type, z);

      if (rot !== 0) {
        const pw = rw * TILE * z;
        const ph = rh * TILE * z;
        ctx.save();
        ctx.translate(sx + pw / 2, sy + ph / 2);
        ctx.rotate((rot * Math.PI) / 180);
        ctx.translate(-(sx + f.w * TILE * z / 2), -(sy + f.h * TILE * z / 2));
        ctx.drawImage(rendered, sx, sy);
        ctx.restore();
      } else {
        ctx.drawImage(rendered, sx, sy);
      }

      // Dynamic clock hands — sync to system time
      if (f.type === 'clock') {
        this.drawClockHands(sx, sy, z);
      }
    }

    if (editMode) {
      ctx.strokeStyle = isSelected ? 'rgba(100,200,255,0.8)' : EDIT_HIGHLIGHT;
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeRect(sx, sy, rw * TILE * z, rh * TILE * z);
      if (isSelected) {
        ctx.fillStyle = 'rgba(100,200,255,0.12)';
        ctx.fillRect(sx, sy, rw * TILE * z, rh * TILE * z);
      }
      ctx.lineWidth = 1;
    }
  }

  /** Half-slab wall block — Minecraft style, 50% fill, flush against tile edge. */
  private drawWallBlock(sx: number, sy: number, rotation: number) {
    const { ctx } = this;
    const z = this.camera.zoom;
    const tw = TILE * z;
    const th = TILE * z;
    const wallFrac = 0.35; // slim partition wall

    if (rotation === 90 || rotation === 270) {
      // Vertical wall — half tile width, full tile height
      const wallW = Math.round(tw * wallFrac);
      // 90: flush right edge; 270: flush left edge
      const wallLeft = rotation === 90 ? sx + tw - wallW : sx;
      const capH = Math.max(2, Math.round(z * 1.5)); // top cap for 3D depth

      // Top cap (lighter — simulates top face)
      ctx.fillStyle = '#484268';
      ctx.fillRect(wallLeft, sy, wallW, capH);

      // Main body
      ctx.fillStyle = '#2C2845';
      ctx.fillRect(wallLeft, sy + capH, wallW, th - capH);

      // Side face (depth strip on exposed side)
      const sideW = Math.max(2, Math.round(z * 1.2));
      ctx.fillStyle = '#363050';
      if (rotation === 90) {
        ctx.fillRect(wallLeft, sy + capH, sideW, th - capH); // left = exposed
      } else {
        ctx.fillRect(wallLeft + wallW - sideW, sy + capH, sideW, th - capH); // right = exposed
      }

      // Top highlight edge
      ctx.fillStyle = 'rgba(255,255,255,0.1)';
      ctx.fillRect(wallLeft, sy, wallW, Math.max(1, z * 0.5));

      // Bottom edge shadow
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(wallLeft, sy + th - Math.max(1, z * 0.5), wallW, Math.max(1, z * 0.5));
    } else {
      // Horizontal wall — full tile width, half tile height
      const wallH = Math.round(th * wallFrac);
      // 0: flush bottom edge; 180: flush top edge
      const wallTop = rotation === 180 ? sy : sy + th - wallH;
      const capH = Math.max(2, Math.round(z * 1.5));

      // Top cap (lighter)
      ctx.fillStyle = '#484268';
      ctx.fillRect(sx, wallTop, tw, capH);

      // Main body
      ctx.fillStyle = '#2C2845';
      ctx.fillRect(sx, wallTop + capH, tw, wallH - capH);

      // Top highlight
      ctx.fillStyle = 'rgba(255,255,255,0.1)';
      ctx.fillRect(sx, wallTop, tw, Math.max(1, z * 0.5));

      // Bottom shadow
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(sx, wallTop + wallH - Math.max(1, z * 0.5), tw, Math.max(1, z * 0.5));
    }
  }

  // ── Dynamic Clock Hands ──────────────────────

  private drawClockHands(sx: number, sy: number, z: number) {
    const { ctx } = this;
    const now = new Date();
    const hours = now.getHours() % 12;
    const minutes = now.getMinutes();

    // Clock sprite is 16×16; center at pixel (7.5, 7) in sprite coordinates
    const cx = sx + 7.5 * z;
    const cy = sy + 7 * z;

    // Hand lengths (in zoomed pixels)
    const hourLen = 3.0 * z;
    const minLen = 4.5 * z;

    // Angles (12 o'clock = -PI/2, clockwise)
    const hourAngle = ((hours + minutes / 60) / 12) * Math.PI * 2 - Math.PI / 2;
    const minAngle = (minutes / 60) * Math.PI * 2 - Math.PI / 2;

    ctx.save();
    ctx.lineCap = 'round';

    // Hour hand (thick, dark)
    ctx.strokeStyle = '#2C2C2C';
    ctx.lineWidth = Math.max(1.5, z * 0.8);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(hourAngle) * hourLen, cy + Math.sin(hourAngle) * hourLen);
    ctx.stroke();

    // Minute hand (thin, red)
    ctx.strokeStyle = '#CC3333';
    ctx.lineWidth = Math.max(1, z * 0.5);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(minAngle) * minLen, cy + Math.sin(minAngle) * minLen);
    ctx.stroke();

    // Center dot
    ctx.fillStyle = '#2C2C2C';
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max(1, z * 0.4), 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
  }

  // ── Character ──────────────────────────────

  private drawCharacter(fsm: FSMCtx, palette: ColorPalette, scale: number) {
    const z = this.camera.zoom;
    const effectiveZoom = Math.max(1, Math.round(z * scale));
    const sheet = getSpriteSheet(visualAnim(fsm), fsm.dir);
    const frame = sheet.frames[fsm.frameIdx % sheet.frames.length];
    const flipH = fsm.dir === 'left';

    const rendered = renderSprite(frame, palette, effectiveZoom, flipH);

    const wx = fsm.pixelX * TILE + (TILE - CHAR_W * scale) / 2;
    const wy = fsm.pixelY * TILE + (TILE - CHAR_H * scale);
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    let alpha = 1;
    if (fsm.spawning) alpha = fsm.spawnT;
    if (fsm.despawning) alpha = 1 - fsm.spawnT;

    if (alpha < 1) this.ctx.globalAlpha = alpha;
    this.ctx.drawImage(rendered, sx, sy);
    if (alpha < 1) this.ctx.globalAlpha = 1;
  }

  // ── Selection Highlight ─────────────────────

  private drawSelectionHighlight(agentId: string, fsm: FSMCtx, scale: number) {
    const selectedAgentId = useUIStore.getState().selectedAgentId;
    if (agentId !== selectedAgentId) return;

    const z = this.camera.zoom;
    const effectiveZoom = Math.max(1, Math.round(z * scale));

    const wx = fsm.pixelX * TILE + (TILE - CHAR_W * scale) / 2;
    const wy = fsm.pixelY * TILE + (TILE - CHAR_H * scale);
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    const rw = CHAR_W * effectiveZoom;
    const rh = CHAR_H * effectiveZoom;
    const highlightSize = Math.max(rw, rh) + 4;
    const hx = sx - 2;
    const hy = sy - 2;

    const alpha = 0.5 + 0.3 * Math.sin(Date.now() / 300);
    this.ctx.strokeStyle = `rgba(74, 144, 217, ${alpha})`;
    this.ctx.lineWidth = 2;
    this.ctx.strokeRect(hx, hy, highlightSize, highlightSize);
    this.ctx.lineWidth = 1;
  }

  // ── Custom Character (user-provided image) ─

  private drawCustomCharacter(fsm: FSMCtx, img: HTMLImageElement, scale: number) {
    const z = this.camera.zoom;
    // Scale image to fit one tile, maintaining aspect ratio
    const maxW = TILE * z * scale;
    const maxH = TILE * z * scale * 1.4; // characters are taller than wide
    const aspect = img.naturalWidth / img.naturalHeight;
    let drawW: number, drawH: number;
    if (aspect > maxW / maxH) {
      drawW = maxW;
      drawH = maxW / aspect;
    } else {
      drawH = maxH;
      drawW = maxH * aspect;
    }

    const wx = fsm.pixelX * TILE + (TILE - drawW / z) / 2;
    const wy = fsm.pixelY * TILE + (TILE - drawH / z);
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    let alpha = 1;
    if (fsm.spawning) alpha = fsm.spawnT;
    if (fsm.despawning) alpha = 1 - fsm.spawnT;

    if (alpha < 1) this.ctx.globalAlpha = alpha;

    // Flip horizontally for left-facing
    if (fsm.dir === 'left') {
      this.ctx.save();
      this.ctx.translate(sx + drawW, sy);
      this.ctx.scale(-1, 1);
      this.ctx.drawImage(img, 0, 0, drawW, drawH);
      this.ctx.restore();
    } else {
      this.ctx.drawImage(img, sx, sy, drawW, drawH);
    }

    if (alpha < 1) this.ctx.globalAlpha = 1;
  }

  // ── FSM Update ─────────────────────────────

  private updateFSM(fsm: FSMCtx, dt: number, map: TileMapData, blocked: Set<string>) {
    fsm.stateTime += dt;
    fsm.frameTimer += dt;

    const sheet = getSpriteSheet(visualAnim(fsm), fsm.dir);
    const interval = 1000 / sheet.fps;
    if (fsm.frameTimer >= interval) {
      fsm.frameTimer -= interval;
      fsm.frameIdx = (fsm.frameIdx + 1) % sheet.frames.length;
    }

    if (fsm.bubbleTimer > 0) {
      fsm.bubbleTimer -= dt;
      if (fsm.bubbleTimer <= 0) {
        // Try to promote next queued message instead of clearing
        if (!promoteBubble(fsm)) {
          fsm.bubble = null;
          fsm.bubbleFull = null;
          fsm.bubbleTimer = 0;
        }
      }
    }
    // Promote queued bubble after 3s minimum hold
    if (fsm.bubbleQueue.length > 0 && Date.now() - fsm.bubbleSetAt >= 3000) {
      promoteBubble(fsm);
    }

    if (fsm.spawning) {
      fsm.spawnT = Math.min(1, fsm.spawnT + dt / SPAWN_MS);
      if (fsm.spawnT >= 1) fsm.spawning = false;
      return;
    }
    if (fsm.despawning) {
      fsm.spawnT = Math.min(1, fsm.spawnT + dt / SPAWN_MS);
      return;
    }

    // Walk to door for offline exit
    if (fsm.exitTarget && fsm.path.length === 0 &&
        (fsm.pos.x !== fsm.exitTarget.x || fsm.pos.y !== fsm.exitTarget.y)) {
      fsm.state = 'WALK';
      fsm.path = bfsPath(map, fsm.pos, fsm.exitTarget, blocked) ?? [];
      fsm.pathIdx = 0;
    }

    switch (fsm.state) {
      case 'IDLE':
        this.updateIdle(fsm, dt, map, blocked);
        break;
      case 'WALK':
        this.updateWalk(fsm, dt);
        break;
      case 'TYPE':
      case 'THINK':
      case 'WAIT':
      case 'ERROR':
        if (fsm.seat && (fsm.pos.x !== fsm.seat.x || fsm.pos.y !== fsm.seat.y)) {
          fsm.state = 'WALK';
          fsm.target = fsm.seat;
          fsm.path = bfsPath(map, fsm.pos, fsm.seat, blocked) ?? [];
          fsm.pathIdx = 0;
        }
        break;
    }
  }

  private updateIdle(fsm: FSMCtx, dt: number, map: TileMapData, blocked: Set<string>) {
    // Waiting at door for despawn — don't wander
    if (fsm.exitTarget) return;

    if (fsm.path.length > 0) {
      this.updateWalk(fsm, dt);
      return;
    }
    // Newly spawned agents: walk to assigned seat first
    if (fsm.seat && (fsm.pos.x !== fsm.seat.x || fsm.pos.y !== fsm.seat.y)) {
      const path = bfsPath(map, fsm.pos, fsm.seat, blocked);
      if (path && path.length > 0) {
        fsm.path = path;
        fsm.pathIdx = 0;
        return;
      }
    }
    fsm.wanderCd -= dt;
    if (fsm.wanderCd <= 0) {
      fsm.wanderCd = 3000 + Math.random() * 5000;
      const dest = randomWalkableInZone(map, blocked, fsm.zone ?? 'work', REST_AREA);
      if (dest) {
        const path = bfsPath(map, fsm.pos, dest, blocked);
        if (path && path.length > 0) {
          fsm.path = path.slice(0, 5);
          fsm.pathIdx = 0;
        }
      }
    }
  }

  private updateWalk(fsm: FSMCtx, dt: number) {
    if (fsm.pathIdx >= fsm.path.length) {
      fsm.path = [];
      fsm.pathIdx = 0;
      if (fsm.exitTarget) {
        // Reached exit door — trigger despawn animation immediately
        fsm.state = 'IDLE';
        fsm.despawning = true;
        fsm.spawnT = 0;
        fsm.exitTarget = null;
      } else if (fsm.state === 'WALK') {
        fsm.state = 'TYPE';
      }
      return;
    }

    const next = fsm.path[fsm.pathIdx];
    fsm.dir = directionTo(fsm.pos, next);

    const speedMul = (fsm.zone === 'rest' && !fsm.exitTarget) ? 0.5 : 1;
    const speed = WALK_SPEED * speedMul * dt / 1000;
    const dx = next.x - fsm.pixelX;
    const dy = next.y - fsm.pixelY;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist <= speed) {
      fsm.pixelX = next.x;
      fsm.pixelY = next.y;
      fsm.pos = { ...next };
      fsm.pathIdx++;
    } else {
      fsm.pixelX += (dx / dist) * speed;
      fsm.pixelY += (dy / dist) * speed;
    }
  }

  // ── Name Label (session ID first 4 chars) ──

  private drawNameLabel(entry: AgentEntry) {
    const { fsm, agent } = entry;
    if (fsm.despawning) return;
    const z = this.camera.zoom;

    // Extract last 4 chars of session_id (random portion of UUID v7)
    const label = agent.session_id?.slice(-4) ?? agent.id.slice(-4);

    const wx = fsm.pixelX * TILE + TILE / 2;
    const wy = fsm.pixelY * TILE - 2;
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    const fontSize = Math.max(7, 5 * z);
    this.ctx.font = `bold ${fontSize}px monospace`;
    const tw = this.ctx.measureText(label).width;

    // Background pill
    const pad = 2 * z;
    const bx = sx - tw / 2 - pad;
    const by = sy - fontSize - pad;
    const color = CLI_PALETTES[agent.cli_type]?.badge ?? '#666';

    this.ctx.fillStyle = color;
    this.ctx.globalAlpha = 0.85;
    this.ctx.beginPath();
    this.ctx.roundRect(bx, by, tw + pad * 2, fontSize + pad, [3]);
    this.ctx.fill();
    this.ctx.globalAlpha = 1;

    // Text
    this.ctx.fillStyle = '#FFF';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'top';
    this.ctx.fillText(label, sx, by + pad / 2);
    this.ctx.textAlign = 'start';
  }

  // ── CLI Legend (bottom-left) ────────────────

  private drawLegend(agents: Map<string, AgentEntry>) {
    const { ctx } = this;

    // Collect active CLI types
    const cliCounts = new Map<string, number>();
    for (const [, entry] of agents) {
      const cli = entry.agent.cli_type;
      cliCounts.set(cli, (cliCounts.get(cli) ?? 0) + 1);
    }
    if (cliCounts.size === 0) return;

    const legendItems: { cli: string; label: string; color: string; count: number }[] = [
      { cli: 'claude', label: 'Claude Code', color: '#4A90D9', count: 0 },
      { cli: 'codex', label: 'Codex CLI', color: '#4CAF50', count: 0 },
      { cli: 'gemini', label: 'Gemini CLI', color: '#9C27B0', count: 0 },
    ].filter(item => {
      const count = cliCounts.get(item.cli);
      if (count) { item.count = count; return true; }
      return false;
    });

    const x = 12;
    const y = this.canvas.height - 12 - legendItems.length * 20;
    const fontSize = 11;

    // Background
    ctx.fillStyle = 'rgba(20, 20, 35, 0.85)';
    const bgW = 140;
    const bgH = legendItems.length * 20 + 8;
    ctx.beginPath();
    ctx.roundRect(x - 4, y - 4, bgW, bgH, [6]);
    ctx.fill();

    ctx.font = `${fontSize}px monospace`;
    for (let i = 0; i < legendItems.length; i++) {
      const item = legendItems[i];
      const iy = y + i * 20;

      // Color square
      ctx.fillStyle = item.color;
      ctx.fillRect(x, iy, 10, 10);

      // Label + count
      ctx.fillStyle = '#CCC';
      ctx.textBaseline = 'top';
      ctx.fillText(`${item.label} (${item.count})`, x + 16, iy);
    }
  }

  // ── Speech Bubble ──────────────────────────

  private drawBubble(entry: AgentEntry) {
    const { fsm, agent } = entry;
    if (fsm.despawning) return;

    // Determine short label for canvas: status only, details in expanded overlay
    let text: string | null = null;
    // Special transient bubbles shown as-is
    if (fsm.bubble === '✓ 完成' || fsm.bubble === '✗ 失敗') {
      text = fsm.bubble;
    } else if (fsm.bubble === 'zzZ') {
      text = 'zzZ';
    } else if (fsm.bubble === '需要授權！') {
      text = '需要授權！';
    } else {
      // Short status derived from FSM state + tool
      text = shortCanvasLabel(fsm.state, agent.current_tool);
    }
    if (!text) return;

    const z = this.camera.zoom;
    const wx = fsm.pixelX * TILE + TILE / 2;
    const wy = fsm.pixelY * TILE - 8;
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    // 30% smaller font
    const fontSize = Math.max(6, 4.2 * z);
    this.ctx.font = `${fontSize}px monospace`;
    const metrics = this.ctx.measureText(text);
    const tw = metrics.width;
    const th = fontSize + 3;
    const pad = 3 * z;

    const bx = sx - tw / 2 - pad;
    const by = sy - th - pad * 2;

    this.ctx.fillStyle = 'rgba(0,0,0,0.65)';
    this.ctx.beginPath();
    this.ctx.roundRect(bx, by, tw + pad * 2, th + pad, [3]);
    this.ctx.fill();

    this.ctx.fillStyle = '#D0D0D0';
    this.ctx.textAlign = 'center';
    this.ctx.textBaseline = 'top';
    this.ctx.fillText(text, sx, by + pad / 2);
    this.ctx.textAlign = 'start';
  }

  // ── Spawn / Despawn Effect ─────────────────

  private drawSpawnEffect(fsm: FSMCtx) {
    const z = this.camera.zoom;
    const wx = fsm.pixelX * TILE + TILE / 2;
    const wy = fsm.pixelY * TILE;
    const { sx, sy } = this.camera.worldToScreen(wx, wy);

    const t = fsm.spawning ? fsm.spawnT : fsm.despawning ? 1 - fsm.spawnT : 0;
    if (t <= 0) return;

    this.ctx.save();
    const alpha = fsm.spawning ? 1 - fsm.spawnT : fsm.spawnT;
    this.ctx.globalAlpha = alpha * 0.7;

    const chars = '01アイウエオカキクケコ';
    const fontSize = Math.max(6, 4 * z);
    this.ctx.font = `${fontSize}px monospace`;
    this.ctx.fillStyle = '#00FF41';

    const cols = 3;
    for (let c = 0; c < cols; c++) {
      const cx = sx + (c - 1) * fontSize * 1.2;
      const rows = Math.floor(4 * (1 - t));
      for (let r = 0; r < rows; r++) {
        const char = chars[Math.floor(Math.random() * chars.length)];
        this.ctx.fillText(char, cx, sy - r * fontSize);
      }
    }

    this.ctx.restore();
  }

  // ── Sub-agent Angels ─────────────────────────

  private drawAngels(entry: AgentEntry) {
    const { fsm } = entry;
    const { ctx, camera } = this;
    const z = camera.zoom;
    const t = Date.now() / 1000;
    const now = Date.now();
    const subs = fsm.subAgents;
    if (subs.length === 0) return;

    // Show up to 3 angel icons in an arc above the character
    const maxShow = Math.min(subs.length, 3);
    const baseWx = fsm.pixelX * TILE + TILE * 0.5;
    const baseWy = fsm.pixelY * TILE - TILE * 0.5;

    for (let i = 0; i < maxShow; i++) {
      const angle = -Math.PI / 2 + (i - (maxShow - 1) / 2) * 0.6;
      const radius = TILE * 0.55;
      const bobY = Math.sin(t * 2 + i * 1.2) * 1.5;
      const wx = baseWx + Math.cos(angle) * radius;
      const wy = baseWy + Math.sin(angle) * radius + bobY;
      const { sx, sy } = camera.worldToScreen(wx, wy);

      const size = Math.max(4, 3 * z);
      ctx.globalAlpha = i === 0 ? 0.95 : 0.6;

      // Halo glow
      const glowR = size * 1.2;
      const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, glowR);
      glow.addColorStop(0, 'rgba(255, 220, 100, 0.35)');
      glow.addColorStop(1, 'rgba(255, 220, 100, 0)');
      ctx.fillStyle = glow;
      ctx.fillRect(sx - glowR, sy - glowR, glowR * 2, glowR * 2);

      // Body
      ctx.fillStyle = '#FFE8A0';
      ctx.beginPath();
      ctx.arc(sx, sy, size * 0.5, 0, Math.PI * 2);
      ctx.fill();

      // Wings
      const wingW = size * 0.4;
      const wingH = size * 0.25;
      const wingFlap = Math.sin(t * 6 + i * 2) * wingH * 0.3;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
      ctx.beginPath();
      ctx.ellipse(sx - size * 0.4, sy - wingFlap, wingW, wingH, -0.3, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(sx + size * 0.4, sy - wingFlap, wingW, wingH, 0.3, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;

    // Task label: show newest sub-agent's label + elapsed time
    const newest = subs[subs.length - 1];
    const elapsed = Math.floor((now - newest.startTime) / 1000);
    const timeStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m${elapsed % 60}s`;
    const labelText = subs.length > 1
      ? `${newest.label} +${subs.length - 1} (${timeStr})`
      : `${newest.label} (${timeStr})`;

    const { sx: labelX, sy: labelY } = camera.worldToScreen(baseWx, baseWy - TILE * 0.85);
    const fontSize = Math.max(6, 3.5 * z);
    ctx.font = `${fontSize}px monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';

    // Background pill
    const tw = ctx.measureText(labelText).width;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    const px = 3 * z / 2;
    const py = 1.5 * z / 2;
    ctx.beginPath();
    const rr = 2 * z / 2;
    ctx.roundRect(labelX - tw / 2 - px, labelY - fontSize - py, tw + px * 2, fontSize + py * 2, rr);
    ctx.fill();

    ctx.fillStyle = '#FFE8A0';
    ctx.fillText(labelText, labelX, labelY);
    ctx.textAlign = 'start';
  }

  // ── Day/Night Cycle (C1) ──────────────────────

  private drawDayNightOverlay(dn: DayNightState) {
    const { ctx } = this;
    const { overlayR, overlayG, overlayB, overlayA } = dn;
    ctx.save();
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = `rgba(${Math.round(overlayR)}, ${Math.round(overlayG)}, ${Math.round(overlayB)}, ${overlayA})`;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.restore();
  }

  /** Warm glow along outer walls — simulates light from office windows at night */
  private drawWindowGlow(map: TileMapData, dn: DayNightState) {
    const { ctx, camera } = this;
    const z = camera.zoom;
    const intensity = dn.windowGlowIntensity;
    if (intensity < 0.01) return;

    ctx.save();
    ctx.globalCompositeOperation = 'screen';

    // Glow along outer walls (y=0 top wall, y=max-1 bottom wall)
    const glowSize = TILE * z * 1.5;
    const alpha = intensity * 0.15;

    // Top wall windows (every 4 tiles)
    for (let tx = 2; tx < map.width - 2; tx += 4) {
      if (tx === DOOR_POS.x || tx === DOOR_POS.x + 1) continue; // skip door
      const { sx, sy } = camera.worldToScreen(tx * TILE, 0);
      if (sx + glowSize < 0 || sx > this.canvas.width) continue;
      const grad = ctx.createRadialGradient(
        sx + TILE * z / 2, sy + TILE * z, 0,
        sx + TILE * z / 2, sy + TILE * z, glowSize,
      );
      grad.addColorStop(0, `rgba(255, 220, 140, ${alpha})`);
      grad.addColorStop(1, 'rgba(255, 220, 140, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(sx - glowSize, sy, glowSize * 3, glowSize * 2);
    }

    // Bottom wall windows
    const bottomY = (map.height - 1);
    for (let tx = 2; tx < map.width - 2; tx += 4) {
      const { sx, sy } = camera.worldToScreen(tx * TILE, bottomY * TILE);
      if (sx + glowSize < 0 || sx > this.canvas.width) continue;
      const grad = ctx.createRadialGradient(
        sx + TILE * z / 2, sy, 0,
        sx + TILE * z / 2, sy, glowSize,
      );
      grad.addColorStop(0, `rgba(255, 220, 140, ${alpha * 0.7})`);
      grad.addColorStop(1, 'rgba(255, 220, 140, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(sx - glowSize, sy - glowSize * 2, glowSize * 3, glowSize * 2);
    }

    ctx.restore();
  }

  /** Desk lamp glow near typing/working agents during evening/night */
  private drawDeskLamps(agents: Map<string, AgentEntry>, dn: DayNightState) {
    const { ctx, camera } = this;
    const z = camera.zoom;
    const intensity = dn.windowGlowIntensity;
    if (intensity < 0.1) return;

    ctx.save();
    ctx.globalCompositeOperation = 'screen';

    for (const [, entry] of agents) {
      const { fsm } = entry;
      // Only show desk lamp for seated, active agents
      if (fsm.state !== 'TYPE' && fsm.state !== 'THINK') continue;
      if (fsm.despawning || fsm.spawning) continue;

      const wx = fsm.pixelX * TILE + TILE / 2;
      const wy = fsm.pixelY * TILE;
      const { sx, sy } = camera.worldToScreen(wx, wy);

      const lampR = TILE * z * 1.8;
      const alpha = intensity * 0.12;
      const grad = ctx.createRadialGradient(sx, sy, 0, sx, sy, lampR);
      grad.addColorStop(0, `rgba(255, 240, 180, ${alpha})`);
      grad.addColorStop(0.6, `rgba(255, 220, 140, ${alpha * 0.4})`);
      grad.addColorStop(1, 'rgba(255, 220, 140, 0)');
      ctx.fillStyle = grad;
      ctx.fillRect(sx - lampR, sy - lampR, lampR * 2, lampR * 2);
    }

    ctx.restore();
  }

  // ── Proximity Interactions (C2) ──────────────────

  private interactionCooldowns = new Map<string, number>();

  private drawProximityInteractions(agents: Map<string, AgentEntry>) {
    const now = Date.now();

    // Check pairs of IDLE agents near each other in corridors
    const idleAgents: AgentEntry[] = [];
    for (const [, entry] of agents) {
      const { fsm } = entry;
      if (fsm.state === 'IDLE' && !fsm.spawning && !fsm.despawning && !fsm.exitTarget) {
        if (isInCorridor(Math.round(fsm.pixelX), Math.round(fsm.pixelY))) {
          idleAgents.push(entry);
        }
      }
    }

    for (let i = 0; i < idleAgents.length; i++) {
      for (let j = i + 1; j < idleAgents.length; j++) {
        const a = idleAgents[i].fsm;
        const b = idleAgents[j].fsm;
        const dx = a.pixelX - b.pixelX;
        const dy = a.pixelY - b.pixelY;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 3) { // within 3 tiles
          const pairKey = [idleAgents[i].agent.id, idleAgents[j].agent.id].sort().join(':');
          const lastWave = this.interactionCooldowns.get(pairKey) ?? 0;
          if (now - lastWave < 15000) continue; // 15s cooldown per pair
          this.interactionCooldowns.set(pairKey, now);

          // Draw wave emoji above both agents briefly
          // (This sets a transient visual; the next few frames will show it)
          if (!a.bubble) {
            a.bubble = '👋';
            a.bubbleTimer = 2000;
            a.bubbleSetAt = now;
          }
          if (!b.bubble) {
            b.bubble = '👋';
            b.bubbleTimer = 2000;
            b.bubbleSetAt = now;
          }
        }
      }
    }

    // Cleanup old cooldown entries
    if (this.interactionCooldowns.size > 100) {
      for (const [key, time] of this.interactionCooldowns) {
        if (now - time > 30000) this.interactionCooldowns.delete(key);
      }
    }
  }

  // ── Edit Mode Overlay ──────────────────────

  private drawEditOverlay(map: TileMapData) {
    const { ctx, camera } = this;
    const z = camera.zoom;

    // Grid overlay
    ctx.strokeStyle = 'rgba(255,200,50,0.12)';
    for (let ty = 0; ty < map.height; ty++) {
      for (let tx = 0; tx < map.width; tx++) {
        if (!map.walkable[ty][tx]) continue;
        const { sx, sy } = camera.worldToScreen(tx * TILE, ty * TILE);
        ctx.strokeRect(sx, sy, TILE * z, TILE * z);
      }
    }

    // Label
    ctx.fillStyle = 'rgba(255,200,50,0.9)';
    ctx.font = '12px monospace';
    ctx.fillText('編輯模式 — 右鍵:移動 | 左鍵:選取 | R:旋轉 | []:寬度 | {}:高度', 12, this.canvas.height - 12);
  }

  // ── Palette ────────────────────────────────

  private getPalette(cliType: string, agentId: string): ColorPalette {
    const base = CLI_PALETTES[cliType] ?? CLI_PALETTES.claude;
    const key = `${cliType}:${agentId}`;
    if (!this.cliSessionCounters.has(key)) {
      const count = [...this.cliSessionCounters.keys()]
        .filter(k => k.startsWith(`${cliType}:`)).length;
      this.cliSessionCounters.set(key, count);
    }
    return shiftPalette(base, this.cliSessionCounters.get(key)!);
  }
}

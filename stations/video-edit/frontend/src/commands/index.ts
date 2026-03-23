import { api } from "../api";
import { useProjectStore } from "../stores/projectStore";
import type { Command } from "../stores/historyStore";

function reload() {
  return useProjectStore.getState().reloadTimeline();
}

function getProjectId(): string {
  const pid = useProjectStore.getState().projectId;
  if (!pid) throw new Error("No project loaded");
  return pid;
}

export class TrimCommand implements Command {
  readonly type = "trim";
  readonly description: string;

  constructor(
    private clipId: string,
    private newIn: number | undefined,
    private newOut: number | undefined,
    private prevIn: number,
    private prevOut: number,
  ) {
    this.description = "Trim clip";
  }

  async execute() {
    const pid = getProjectId();
    await api.trimClip(pid, this.clipId, {
      in_point: this.newIn,
      out_point: this.newOut,
    });
    await reload();
  }

  async undo() {
    const pid = getProjectId();
    await api.trimClip(pid, this.clipId, {
      in_point: this.prevIn,
      out_point: this.prevOut,
    });
    await reload();
  }
}

export class RemoveCommand implements Command {
  readonly type = "remove";
  readonly description: string;
  private addBackData: {
    resource: string;
    track: number;
    inPoint: number;
    outPoint: number;
  } | null = null;

  constructor(
    private clipId: string,
    resource: string,
    track: number,
    inPoint: number,
    outPoint: number,
  ) {
    this.description = `Remove clip`;
    this.addBackData = { resource, track, inPoint, outPoint };
  }

  async execute() {
    const pid = getProjectId();
    await api.removeClip(pid, this.clipId);
    await reload();
  }

  async undo() {
    if (!this.addBackData) return;
    const pid = getProjectId();
    const result = await api.addClip(pid, {
      file_path: this.addBackData.resource,
      track: this.addBackData.track,
      in_point: this.addBackData.inPoint,
      out_point: this.addBackData.outPoint,
    });
    // Update clipId to the newly created one for future redo
    if (result && typeof result === "object" && "clip_id" in result) {
      this.clipId = (result as { clip_id: string }).clip_id;
    }
    await reload();
  }
}

export class CutCommand implements Command {
  readonly type = "cut";
  readonly description: string;

  constructor(
    private clipId: string,
    private atTime: number,
  ) {
    this.description = `Cut clip at ${atTime.toFixed(1)}s`;
  }

  async execute() {
    const pid = getProjectId();
    await api.cutClip(pid, this.clipId, this.atTime);
    await reload();
  }

  async undo() {
    // Cut is hard to undo perfectly — reload from saved state
    // For now, just reload (user can save before cutting)
    await reload();
  }
}

export class MoveToTimeCommand implements Command {
  readonly type = "move-to-time";
  readonly description = "Move clip";

  constructor(
    private clipId: string,
    private newTime: number,
    private newTrack: number | undefined,
    private prevTime: number,
    private prevTrack: number,
  ) {}

  async execute() {
    const pid = getProjectId();
    await api.moveClipToTime(pid, this.clipId, {
      target_time: this.newTime,
      target_track: this.newTrack,
    });
    await reload();
  }

  async undo() {
    const pid = getProjectId();
    await api.moveClipToTime(pid, this.clipId, {
      target_time: this.prevTime,
      target_track: this.prevTrack,
    });
    await reload();
  }
}

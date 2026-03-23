"""MLT XML engine — create, modify, and render MLT projects.

Manages .mlt XML project files that are compatible with both
the `melt` CLI and Kdenlive GUI.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from video_edit.config import settings


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClipInfo:
    id: str
    producer_id: str
    resource: str
    track: int
    in_point: str  # HH:MM:SS.mmm
    out_point: str  # HH:MM:SS.mmm
    position: int  # entry index in playlist


@dataclass
class ProjectInfo:
    id: str
    name: str
    path: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    tracks: int = 3
    clips: list[ClipInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _tc(seconds: float) -> str:
    """Convert seconds to MLT timecode HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _parse_tc(tc: str) -> float:
    """Parse HH:MM:SS.mmm or SS.mmm to seconds."""
    parts = tc.split(":")
    if len(parts) == 3:
        h, m, rest = parts
        s = float(rest)
        return int(h) * 3600 + int(m) * 60 + s
    elif len(parts) == 2:
        m, rest = parts
        s = float(rest)
        return int(m) * 60 + s
    else:
        return float(tc)


def _gen_id(prefix: str = "item") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# MLT Engine
# ---------------------------------------------------------------------------

class MLTEngine:
    """Create and manipulate MLT XML project files."""

    def __init__(self, projects_dir: str | None = None):
        self.projects_dir = Path(projects_dir or settings.PROJECTS_DIR)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, etree._Element] = {}

    # ======================== Project CRUD ========================

    def create_project(
        self,
        name: str,
        width: int | None = None,
        height: int | None = None,
        fps_num: int | None = None,
        fps_den: int | None = None,
        num_tracks: int = 3,
    ) -> ProjectInfo:
        """Create a new MLT XML project."""
        w = width or settings.DEFAULT_WIDTH
        h = height or settings.DEFAULT_HEIGHT
        fn = fps_num or settings.DEFAULT_FPS_NUM
        fd = fps_den or settings.DEFAULT_FPS_DEN

        project_id = _gen_id("proj")
        project_dir = self.projects_dir / name
        project_dir.mkdir(parents=True, exist_ok=True)

        root = etree.Element("mlt", LC_NUMERIC="C", version="7.28.0")

        # Profile
        etree.SubElement(
            root,
            "profile",
            description=f"{w}x{h} {fn}/{fd}fps",
            width=str(w),
            height=str(h),
            progressive="1",
            sample_aspect_num="1",
            sample_aspect_den="1",
            display_aspect_num=str(w // (w // 16 if w % 16 == 0 else 1)),
            display_aspect_den=str(h // (h // 9 if h % 9 == 0 else 1)),
            frame_rate_num=str(fn),
            frame_rate_den=str(fd),
            colorspace="709",
        )

        # Create track playlists
        for i in range(num_tracks):
            etree.SubElement(root, "playlist", id=f"track{i}")

        # Tractor (timeline)
        tractor = etree.SubElement(root, "tractor", id="timeline")
        multitrack = etree.SubElement(tractor, "multitrack")
        for i in range(num_tracks):
            etree.SubElement(multitrack, "track", producer=f"track{i}")

        # Save metadata as comment
        comment = etree.Comment(f" project_id={project_id} name={name} ")
        root.insert(0, comment)

        # Write to disk
        mlt_path = project_dir / f"{name}.mlt"
        tree = etree.ElementTree(root)
        tree.write(str(mlt_path), xml_declaration=True, encoding="utf-8", pretty_print=True)

        self._cache[project_id] = root

        return ProjectInfo(
            id=project_id,
            name=name,
            path=str(mlt_path),
            width=w,
            height=h,
            fps_num=fn,
            fps_den=fd,
            tracks=num_tracks,
        )

    def open_project(self, path: str) -> ProjectInfo:
        """Open an existing .mlt project file."""
        mlt_path = Path(path)
        if not mlt_path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")

        tree = etree.parse(str(mlt_path))
        root = tree.getroot()

        # Extract metadata
        profile = root.find("profile")
        width = int(profile.get("width", "1920"))
        height = int(profile.get("height", "1080"))
        fps_num = int(profile.get("frame_rate_num", "30"))
        fps_den = int(profile.get("frame_rate_den", "1"))

        # Extract project_id from comment
        project_id = _gen_id("proj")
        for item in root.iter():
            if isinstance(item, etree._Comment):
                text = item.text or ""
                if "project_id=" in text:
                    project_id = text.split("project_id=")[1].split()[0]
                    break

        name = mlt_path.stem
        num_tracks = len(root.findall("playlist"))

        self._cache[project_id] = root

        info = ProjectInfo(
            id=project_id,
            name=name,
            path=str(mlt_path),
            width=width,
            height=height,
            fps_num=fps_num,
            fps_den=fps_den,
            tracks=num_tracks,
        )
        info.clips = self._extract_clips(root)
        return info

    def save_project(self, project_id: str, path: str | None = None) -> str:
        """Save project to disk. Returns the file path."""
        root = self._get_root(project_id)

        if path is None:
            # Find existing path from comment
            for item in root.iter():
                if isinstance(item, etree._Comment):
                    text = item.text or ""
                    if "name=" in text:
                        name = text.split("name=")[1].strip()
                        path = str(self.projects_dir / name / f"{name}.mlt")
                        break
            if path is None:
                raise ValueError("No path specified and cannot determine from project metadata")

        mlt_path = Path(path)
        mlt_path.parent.mkdir(parents=True, exist_ok=True)
        tree = etree.ElementTree(root)
        tree.write(str(mlt_path), xml_declaration=True, encoding="utf-8", pretty_print=True)
        return str(mlt_path)

    def list_projects(self) -> list[dict]:
        """List all projects in the projects directory."""
        projects = []
        if not self.projects_dir.exists():
            return projects
        for d in sorted(self.projects_dir.iterdir()):
            if d.is_dir():
                mlt_files = list(d.glob("*.mlt"))
                if mlt_files:
                    projects.append({
                        "name": d.name,
                        "path": str(mlt_files[0]),
                        "modified": mlt_files[0].stat().st_mtime,
                    })
        return projects

    # ======================== Clip Operations ========================

    def add_clip(
        self,
        project_id: str,
        file_path: str,
        track: int = 0,
        in_point: float = 0,
        out_point: float | None = None,
    ) -> dict:
        """Add a media clip to the timeline."""
        root = self._get_root(project_id)
        resource = Path(file_path).resolve()
        if not resource.exists():
            raise FileNotFoundError(f"Media file not found: {file_path}")

        producer_id = _gen_id("prod")
        clip_id = _gen_id("clip")

        # Probe duration if out_point not specified
        if out_point is None:
            out_point = self._probe_duration(str(resource))

        # Create producer element (insert before playlists)
        producer = etree.Element("producer", id=producer_id)
        prop_res = etree.SubElement(producer, "property", name="resource")
        prop_res.text = str(resource)
        prop_svc = etree.SubElement(producer, "property", name="mlt_service")
        prop_svc.text = "avformat"
        prop_cid = etree.SubElement(producer, "property", name="clip_id")
        prop_cid.text = clip_id

        # Insert producer before first playlist
        first_playlist = root.find("playlist")
        if first_playlist is not None:
            root.insert(list(root).index(first_playlist), producer)
        else:
            root.append(producer)

        # Add entry to target track playlist
        playlist = root.find(f".//playlist[@id='track{track}']")
        if playlist is None:
            raise ValueError(f"Track {track} does not exist")

        entry = etree.SubElement(
            playlist,
            "entry",
            producer=producer_id,
        )
        entry.set("in", _tc(in_point))
        entry.set("out", _tc(out_point))

        return {
            "clip_id": clip_id,
            "producer_id": producer_id,
            "resource": str(resource),
            "track": track,
            "in": _tc(in_point),
            "out": _tc(out_point),
        }

    def cut_clip(self, project_id: str, clip_id: str, at_time: float) -> dict:
        """Cut a clip at the specified time, creating two segments."""
        root = self._get_root(project_id)
        producer, entry, playlist = self._find_clip(root, clip_id)

        in_tc = entry.get("in", "00:00:00.000")
        out_tc = entry.get("out", "00:00:00.000")
        in_sec = _parse_tc(in_tc)
        out_sec = _parse_tc(out_tc)

        if at_time <= in_sec or at_time >= out_sec:
            raise ValueError(f"Cut time {at_time}s is outside clip range [{in_sec}, {out_sec}]")

        # Modify original entry to end at cut point
        entry.set("out", _tc(at_time))

        # Create new entry for the second half
        new_clip_id = _gen_id("clip")
        new_producer_id = producer.get("id")

        new_entry = etree.Element("entry", producer=new_producer_id)
        new_entry.set("in", _tc(at_time))
        new_entry.set("out", out_tc)

        # Insert after original entry
        idx = list(playlist).index(entry)
        playlist.insert(idx + 1, new_entry)

        return {
            "original_clip_id": clip_id,
            "new_clip_id": new_clip_id,
            "cut_at": _tc(at_time),
            "part1": {"in": in_tc, "out": _tc(at_time)},
            "part2": {"in": _tc(at_time), "out": out_tc},
        }

    def trim_clip(
        self,
        project_id: str,
        clip_id: str,
        in_point: float | None = None,
        out_point: float | None = None,
    ) -> dict:
        """Adjust a clip's in/out points."""
        root = self._get_root(project_id)
        _, entry, _ = self._find_clip(root, clip_id)

        if in_point is not None:
            entry.set("in", _tc(in_point))
        if out_point is not None:
            entry.set("out", _tc(out_point))

        return {
            "clip_id": clip_id,
            "in": entry.get("in"),
            "out": entry.get("out"),
        }

    def remove_clip(self, project_id: str, clip_id: str) -> dict:
        """Remove a clip from the timeline."""
        root = self._get_root(project_id)
        producer, entry, playlist = self._find_clip(root, clip_id)

        playlist.remove(entry)
        # Also remove the producer if no other entries reference it
        producer_id = producer.get("id")
        still_used = any(
            e.get("producer") == producer_id
            for pl in root.findall(".//playlist")
            for e in pl.findall("entry")
        )
        if not still_used:
            root.remove(producer)

        return {"clip_id": clip_id, "removed": True}

    def move_clip(
        self,
        project_id: str,
        clip_id: str,
        new_track: int | None = None,
        new_position: int | None = None,
    ) -> dict:
        """Move a clip to a different track or position."""
        root = self._get_root(project_id)
        producer, entry, old_playlist = self._find_clip(root, clip_id)

        if new_track is not None:
            new_playlist = root.find(f".//playlist[@id='track{new_track}']")
            if new_playlist is None:
                raise ValueError(f"Track {new_track} does not exist")
            old_playlist.remove(entry)
            if new_position is not None and new_position < len(new_playlist):
                new_playlist.insert(new_position, entry)
            else:
                new_playlist.append(entry)
        elif new_position is not None:
            old_playlist.remove(entry)
            old_playlist.insert(min(new_position, len(old_playlist)), entry)

        return {"clip_id": clip_id, "track": new_track, "position": new_position}

    def move_clip_to_time(
        self,
        project_id: str,
        clip_id: str,
        target_time: float,
        target_track: int | None = None,
    ) -> dict:
        """Move a clip to a specific time position using blank elements."""
        root = self._get_root(project_id)
        producer, entry, old_playlist = self._find_clip(root, clip_id)

        in_tc = entry.get("in", "00:00:00.000")
        out_tc = entry.get("out", "00:00:00.000")
        clip_duration = _parse_tc(out_tc) - _parse_tc(in_tc)

        # Determine target playlist
        if target_track is not None:
            new_playlist = root.find(f".//playlist[@id='track{target_track}']")
            if new_playlist is None:
                raise ValueError(f"Track {target_track} does not exist")
        else:
            new_playlist = old_playlist
            # Find track index from playlist id
            target_track = int(old_playlist.get("id", "track0").replace("track", ""))

        # Remove from old playlist
        old_playlist.remove(entry)

        # Clear all blanks and entries from target playlist, collect entries
        existing_entries = []
        for child in list(new_playlist):
            if child.tag == "entry":
                # Calculate this entry's timeline position
                cursor = 0.0
                for prev in new_playlist:
                    if prev is child:
                        break
                    if prev.tag == "blank":
                        cursor += _parse_tc(prev.get("length", "00:00:00.000"))
                    elif prev.tag == "entry":
                        e_in = _parse_tc(prev.get("in", "00:00:00.000"))
                        e_out = _parse_tc(prev.get("out", "00:00:00.000"))
                        cursor += e_out - e_in
                existing_entries.append((cursor, child))
            new_playlist.remove(child)

        # Add our moved entry at the target time
        existing_entries.append((target_time, entry))
        # Sort by time
        existing_entries.sort(key=lambda x: x[0])

        # Rebuild playlist with proper blanks
        cursor = 0.0
        for t, e in existing_entries:
            gap = t - cursor
            if gap > 0.01:  # >10ms gap → insert blank
                blank = etree.SubElement(new_playlist, "blank")
                blank.set("length", _tc(gap))
                cursor += gap
            new_playlist.append(e)
            e_in = _parse_tc(e.get("in", "00:00:00.000"))
            e_out = _parse_tc(e.get("out", "00:00:00.000"))
            cursor += e_out - e_in

        return {
            "clip_id": clip_id,
            "track": target_track,
            "time": _tc(target_time),
        }

    # ======================== Effects ========================

    def add_transition(
        self,
        project_id: str,
        a_track: int,
        b_track: int,
        transition_type: str = "luma",
        in_time: float = 0,
        out_time: float = 2,
    ) -> dict:
        """Add a transition between two tracks."""
        root = self._get_root(project_id)
        tractor = root.find(".//tractor[@id='timeline']")
        if tractor is None:
            raise ValueError("No timeline tractor found")

        trans_id = _gen_id("trans")
        transition = etree.SubElement(tractor, "transition", id=trans_id)
        transition.set("in", _tc(in_time))
        transition.set("out", _tc(out_time))

        props = {
            "a_track": str(a_track),
            "b_track": str(b_track),
            "mlt_service": transition_type,
        }
        for k, v in props.items():
            prop = etree.SubElement(transition, "property", name=k)
            prop.text = v

        return {
            "transition_id": trans_id,
            "type": transition_type,
            "a_track": a_track,
            "b_track": b_track,
            "in": _tc(in_time),
            "out": _tc(out_time),
        }

    def add_subtitle(
        self,
        project_id: str,
        text: str,
        start: float,
        end: float,
        track: int | None = None,
        font_size: int = 48,
        color: str = "#ffffffff",
        bg_color: str = "#00000080",
        valign: str = "bottom",
    ) -> dict:
        """Add a text subtitle overlay."""
        root = self._get_root(project_id)

        # Use the highest track for subtitles, or specified track
        playlists = root.findall("playlist")
        if track is None:
            track = len(playlists) - 1

        sub_id = _gen_id("sub")
        producer_id = _gen_id("text")

        # Create pango text producer
        producer = etree.Element("producer", id=producer_id)
        props = {
            "mlt_service": "pango",
            "text": text,
            "fgcolour": color,
            "bgcolour": bg_color,
            "size": str(font_size),
            "valign": valign,
            "clip_id": sub_id,
        }
        for k, v in props.items():
            prop = etree.SubElement(producer, "property", name=k)
            prop.text = v

        # Insert before playlists
        first_playlist = root.find("playlist")
        root.insert(list(root).index(first_playlist), producer)

        # Add to track
        playlist = root.find(f".//playlist[@id='track{track}']")
        if playlist is None:
            raise ValueError(f"Track {track} does not exist")

        # Add blank to position the subtitle
        if start > 0:
            blank = etree.SubElement(playlist, "blank")
            blank.set("length", _tc(start))

        entry = etree.SubElement(playlist, "entry", producer=producer_id)
        entry.set("in", "00:00:00.000")
        entry.set("out", _tc(end - start))

        # Add composite transition so text overlays on video
        tractor = root.find(".//tractor[@id='timeline']")
        if tractor is not None:
            trans = etree.SubElement(tractor, "transition", id=_gen_id("comp"))
            trans.set("in", _tc(start))
            trans.set("out", _tc(end))
            for k, v in {
                "a_track": "0",
                "b_track": str(track),
                "mlt_service": "composite",
                "geometry": "0/75%:100%x25%",
                "halign": "centre",
                "valign": valign,
            }.items():
                prop = etree.SubElement(trans, "property", name=k)
                prop.text = v

        return {
            "subtitle_id": sub_id,
            "text": text,
            "start": _tc(start),
            "end": _tc(end),
            "track": track,
        }

    def add_filter(
        self,
        project_id: str,
        clip_id: str,
        filter_type: str,
        params: dict[str, str] | None = None,
    ) -> dict:
        """Add a filter/effect to a specific clip's producer."""
        root = self._get_root(project_id)
        producer, _, _ = self._find_clip(root, clip_id)

        filter_id = _gen_id("filt")
        filt = etree.SubElement(producer, "filter", id=filter_id)
        prop_svc = etree.SubElement(filt, "property", name="mlt_service")
        prop_svc.text = filter_type

        if params:
            for k, v in params.items():
                prop = etree.SubElement(filt, "property", name=k)
                prop.text = str(v)

        return {
            "filter_id": filter_id,
            "clip_id": clip_id,
            "type": filter_type,
            "params": params or {},
        }

    def adjust_audio(
        self,
        project_id: str,
        clip_id: str,
        volume: float | None = None,
        fade_in: float | None = None,
        fade_out: float | None = None,
    ) -> dict:
        """Adjust audio properties of a clip."""
        root = self._get_root(project_id)
        producer, entry, _ = self._find_clip(root, clip_id)

        results = {}

        if volume is not None:
            filt = etree.SubElement(producer, "filter", id=_gen_id("vol"))
            prop_svc = etree.SubElement(filt, "property", name="mlt_service")
            prop_svc.text = "volume"
            prop_lvl = etree.SubElement(filt, "property", name="level")
            prop_lvl.text = str(volume)
            results["volume"] = volume

        if fade_in is not None:
            filt = etree.SubElement(producer, "filter", id=_gen_id("fin"))
            prop_svc = etree.SubElement(filt, "property", name="mlt_service")
            prop_svc.text = "volume"
            prop_lvl = etree.SubElement(filt, "property", name="level")
            prop_lvl.text = f"0=0;{_tc(fade_in)}=1"
            results["fade_in"] = fade_in

        if fade_out is not None:
            out_tc = entry.get("out", "00:00:00.000")
            out_sec = _parse_tc(out_tc)
            filt = etree.SubElement(producer, "filter", id=_gen_id("fout"))
            prop_svc = etree.SubElement(filt, "property", name="mlt_service")
            prop_svc.text = "volume"
            prop_lvl = etree.SubElement(filt, "property", name="level")
            prop_lvl.text = f"{_tc(out_sec - fade_out)}=1;{out_tc}=0"
            results["fade_out"] = fade_out

        return {"clip_id": clip_id, **results}

    def list_filters(self, project_id: str, clip_id: str) -> list[dict]:
        """List all filters attached to a clip's producer."""
        root = self._get_root(project_id)
        producer, _, _ = self._find_clip(root, clip_id)

        filters = []
        for filt in producer.findall("filter"):
            filter_id = filt.get("id", "")
            service = ""
            params = {}
            for prop in filt.findall("property"):
                name = prop.get("name", "")
                value = prop.text or ""
                if name == "mlt_service":
                    service = value
                else:
                    params[name] = value
            filters.append({
                "filter_id": filter_id,
                "type": service,
                "params": params,
            })
        return filters

    def remove_filter(self, project_id: str, clip_id: str, filter_id: str) -> dict:
        """Remove a filter from a clip's producer."""
        root = self._get_root(project_id)
        producer, _, _ = self._find_clip(root, clip_id)

        for filt in producer.findall("filter"):
            if filt.get("id") == filter_id:
                producer.remove(filt)
                return {"filter_id": filter_id, "removed": True}
        raise KeyError(f"Filter {filter_id} not found on clip {clip_id}")

    # ======================== Info & Render ========================

    def timeline_info(self, project_id: str) -> dict:
        """Return a structured summary of the timeline for LLM consumption."""
        root = self._get_root(project_id)
        profile = root.find("profile")

        tracks = []
        for playlist in root.findall("playlist"):
            track_id = playlist.get("id", "")
            entries = []
            cursor = 0.0  # absolute timeline position in seconds
            for child in playlist:
                if child.tag == "blank":
                    length_tc = child.get("length", "00:00:00.000")
                    cursor += _parse_tc(length_tc)
                elif child.tag == "entry":
                    producer_id = child.get("producer", "")
                    producer = root.find(f".//producer[@id='{producer_id}']")
                    resource = ""
                    clip_id = ""
                    if producer is not None:
                        for prop in producer.findall("property"):
                            if prop.get("name") == "resource":
                                resource = prop.text or ""
                            if prop.get("name") == "clip_id":
                                clip_id = prop.text or ""
                    in_tc = child.get("in", "00:00:00.000")
                    out_tc = child.get("out", "00:00:00.000")
                    clip_dur = _parse_tc(out_tc) - _parse_tc(in_tc)
                    entries.append({
                        "clip_id": clip_id or producer_id,
                        "resource": Path(resource).name if resource else "",
                        "in": in_tc,
                        "out": out_tc,
                        "timeline_start": _tc(cursor),
                        "timeline_end": _tc(cursor + clip_dur),
                    })
                    cursor += clip_dur
            tracks.append({"track": track_id, "clips": entries})

        transitions = []
        tractor = root.find(".//tractor[@id='timeline']")
        if tractor is not None:
            for t in tractor.findall("transition"):
                svc = ""
                a_track = ""
                b_track = ""
                for prop in t.findall("property"):
                    name = prop.get("name", "")
                    if name == "mlt_service":
                        svc = prop.text or ""
                    elif name == "a_track":
                        a_track = prop.text or ""
                    elif name == "b_track":
                        b_track = prop.text or ""
                transitions.append({
                    "id": t.get("id", ""),
                    "type": svc,
                    "a_track": a_track,
                    "b_track": b_track,
                    "in": t.get("in", ""),
                    "out": t.get("out", ""),
                })

        return {
            "profile": {
                "width": profile.get("width") if profile is not None else None,
                "height": profile.get("height") if profile is not None else None,
                "fps": f"{profile.get('frame_rate_num')}/{profile.get('frame_rate_den')}"
                if profile is not None
                else None,
            },
            "tracks": tracks,
            "transitions": transitions,
        }

    def preview(
        self,
        project_id: str,
        start: float | None = None,
        end: float | None = None,
        output_path: str | None = None,
    ) -> str:
        """Render a preview segment using melt. Returns the output file path."""
        root = self._get_root(project_id)

        # Save to temp file for melt
        tmp_mlt = Path(settings.PREVIEW_DIR) / f"{project_id}_preview.mlt"
        tmp_mlt.parent.mkdir(parents=True, exist_ok=True)
        tree = etree.ElementTree(root)
        tree.write(str(tmp_mlt), xml_declaration=True, encoding="utf-8", pretty_print=True)

        if output_path is None:
            output_path = str(tmp_mlt.parent / f"{project_id}_preview.mp4")

        cmd = [settings.MELT_BIN, str(tmp_mlt)]
        if start is not None:
            cmd.extend(["-in", _tc(start)])
        if end is not None:
            cmd.extend(["-out", _tc(end)])
        cmd.extend([
            "-consumer", f"avformat:{output_path}",
            "vcodec=libx264", "acodec=aac",
            "preset=ultrafast", "crf=23",
        ])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"melt preview failed: {result.stderr[:500]}")

        return output_path

    def render(
        self,
        project_id: str,
        output_path: str,
        vcodec: str = "libx264",
        acodec: str = "aac",
        preset: str = "medium",
        crf: int = 18,
    ) -> str:
        """Final render using melt. Returns the output file path."""
        root = self._get_root(project_id)

        # Save current state to temp file
        tmp_mlt = Path(settings.PREVIEW_DIR) / f"{project_id}_render.mlt"
        tmp_mlt.parent.mkdir(parents=True, exist_ok=True)
        tree = etree.ElementTree(root)
        tree.write(str(tmp_mlt), xml_declaration=True, encoding="utf-8", pretty_print=True)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            settings.MELT_BIN, str(tmp_mlt),
            "-consumer", f"avformat:{output_path}",
            f"vcodec={vcodec}", f"acodec={acodec}",
            f"preset={preset}", f"crf={crf}",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"melt render failed: {result.stderr[:500]}")

        return output_path

    def render_frame(
        self,
        project_id: str,
        time: float,
        width: int = 960,
        height: int = 540,
    ) -> bytes:
        """Render a single frame at the given time as JPEG bytes."""
        root = self._get_root(project_id)
        project_dir = self.projects_dir / project_id
        tmp_mlt = project_dir / "project.mlt"
        tree = etree.ElementTree(root)
        tree.write(str(tmp_mlt), xml_declaration=True, encoding="UTF-8")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(tmp_mlt),
            "-ss", str(time),
            "-vframes", "1",
            "-s", f"{width}x{height}",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "3",
            "pipe:1",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode != 0:
            # Fallback: try melt for .mlt files
            cmd2 = [
                settings.MELT_BIN, str(tmp_mlt),
                "-in", str(int(time * 30)),
                "-out", str(int(time * 30)),
                "-consumer", f"avformat:/dev/stdout",
                "vcodec=mjpeg", "f=image2pipe",
            ]
            result = subprocess.run(cmd2, capture_output=True, timeout=15)
            if result.returncode != 0:
                raise RuntimeError(f"Frame render failed at t={time}")
        return result.stdout

    def get_waveform(
        self,
        project_id: str,
        clip_id: str,
        samples: int = 800,
    ) -> list[float]:
        """Extract audio waveform peaks for a clip."""
        root = self._get_root(project_id)
        producer, entry, _ = self._find_clip(root, clip_id)

        resource = ""
        for prop in producer.findall("property"):
            if prop.get("name") == "resource":
                resource = prop.text or ""
                break

        if not resource or not Path(resource).exists():
            return [0.0] * samples

        # Use ffmpeg to extract raw audio, compute peaks
        cmd = [
            "ffmpeg", "-i", resource,
            "-ac", "1",  # mono
            "-ar", "8000",  # low sample rate for speed
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "pipe:1",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0 or not result.stdout:
            return [0.0] * samples

        import struct
        raw = result.stdout
        total_floats = len(raw) // 4
        if total_floats == 0:
            return [0.0] * samples

        # Downsample to requested number of samples
        chunk_size = max(1, total_floats // samples)
        peaks = []
        for i in range(0, total_floats, chunk_size):
            end = min(i + chunk_size, total_floats)
            chunk_max = 0.0
            for j in range(i, end):
                val = abs(struct.unpack_from('<f', raw, j * 4)[0])
                if val > chunk_max:
                    chunk_max = val
            peaks.append(round(min(chunk_max, 1.0), 4))
            if len(peaks) >= samples:
                break

        return peaks

    def get_thumbnails(
        self,
        project_id: str,
        clip_id: str,
        interval: float = 2.0,
        thumb_width: int = 160,
        thumb_height: int = 90,
    ) -> str:
        """Generate thumbnail sprite sheet for a clip. Returns path to PNG."""
        root = self._get_root(project_id)
        producer, entry, _ = self._find_clip(root, clip_id)

        resource = ""
        for prop in producer.findall("property"):
            if prop.get("name") == "resource":
                resource = prop.text or ""
                break

        if not resource or not Path(resource).exists():
            raise FileNotFoundError(f"Resource not found for clip {clip_id}")

        in_sec = _parse_tc(entry.get("in", "00:00:00.000"))
        out_sec = _parse_tc(entry.get("out", "00:00:00.000"))
        duration = out_sec - in_sec

        # Output path
        thumb_dir = self.projects_dir / project_id / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(thumb_dir / f"{clip_id}_strip.png")

        num_frames = max(1, int(duration / interval))

        # Use ffmpeg to extract frames and tile them horizontally
        cmd = [
            "ffmpeg", "-y",
            "-i", resource,
            "-ss", str(in_sec),
            "-t", str(duration),
            "-vf", f"fps=1/{interval},scale={thumb_width}:{thumb_height},tile={num_frames}x1",
            "-frames:v", "1",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Thumbnail generation failed: {result.stderr[:200]}")

        return output_path

    # ======================== Internal helpers ========================

    def _get_root(self, project_id: str) -> etree._Element:
        if project_id not in self._cache:
            raise KeyError(f"Project {project_id} not loaded. Call open_project() first.")
        return self._cache[project_id]

    def _find_clip(
        self, root: etree._Element, clip_id: str
    ) -> tuple[etree._Element, etree._Element, etree._Element]:
        """Find a clip by clip_id. Returns (producer, entry, playlist)."""
        # Find producer by clip_id property
        for producer in root.findall("producer"):
            for prop in producer.findall("property"):
                if prop.get("name") == "clip_id" and prop.text == clip_id:
                    producer_id = producer.get("id")
                    # Find the entry referencing this producer
                    for playlist in root.findall("playlist"):
                        for entry in playlist.findall("entry"):
                            if entry.get("producer") == producer_id:
                                return producer, entry, playlist
        raise KeyError(f"Clip {clip_id} not found")

    def _extract_clips(self, root: etree._Element) -> list[ClipInfo]:
        """Extract all clips from the project."""
        clips = []
        for i, playlist in enumerate(root.findall("playlist")):
            for j, entry in enumerate(playlist.findall("entry")):
                producer_id = entry.get("producer", "")
                producer = root.find(f".//producer[@id='{producer_id}']")
                resource = ""
                clip_id = producer_id
                if producer is not None:
                    for prop in producer.findall("property"):
                        if prop.get("name") == "resource":
                            resource = prop.text or ""
                        if prop.get("name") == "clip_id":
                            clip_id = prop.text or ""
                clips.append(
                    ClipInfo(
                        id=clip_id,
                        producer_id=producer_id,
                        resource=resource,
                        track=i,
                        in_point=entry.get("in", "00:00:00.000"),
                        out_point=entry.get("out", "00:00:00.000"),
                        position=j,
                    )
                )
        return clips

    def _probe_duration(self, file_path: str) -> float:
        """Probe media file duration using ffprobe (more reliable than melt for duration)."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        # Fallback: try melt (returns frame count, convert via profile fps)
        try:
            cmd = [settings.MELT_BIN, file_path, "-consumer", "xml"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                xml_root = etree.fromstring(result.stdout.encode())
                length = None
                fps = 25.0  # melt default
                for prop in xml_root.findall(".//property"):
                    if prop.get("name") == "length":
                        length = int(prop.text or "0")
                profile = xml_root.find(".//profile")
                if profile is not None:
                    fn = float(profile.get("frame_rate_num", "25"))
                    fd = float(profile.get("frame_rate_den", "1"))
                    if fd > 0:
                        fps = fn / fd
                if length and fps > 0:
                    return length / fps
        except Exception:
            pass
        # Final fallback
        return 60.0

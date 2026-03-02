"""Docker / OrbStack collector — containers, images, volumes."""

from __future__ import annotations

import json
import shutil
import subprocess


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def collect() -> dict:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {"available": False}

    result: dict = {"available": True}

    # OrbStack detection
    orbstack_bin = shutil.which("orbctl")
    result["orbstack"] = orbstack_bin is not None

    # Running containers
    ps_out = _run([docker_bin, "ps", "--format", "{{json .}}"])
    containers = []
    for line in ps_out.splitlines():
        if not line.strip():
            continue
        try:
            c = json.loads(line)
            containers.append({
                "name": c.get("Names", ""),
                "image": c.get("Image", ""),
                "status": c.get("Status", ""),
                "ports": c.get("Ports", ""),
            })
        except json.JSONDecodeError:
            continue
    result["containers"] = containers
    result["container_count"] = len(containers)

    # Images
    img_out = _run([docker_bin, "images", "--format", "{{.Repository}}:{{.Tag}} {{.Size}}"])
    images = []
    for line in img_out.splitlines():
        parts = line.rsplit(" ", 1)
        if parts:
            images.append({
                "image": parts[0],
                "size": parts[1] if len(parts) > 1 else "",
            })
    result["images"] = images
    result["image_count"] = len(images)

    # Volumes
    vol_out = _run([docker_bin, "volume", "ls", "--format", "{{.Name}}"])
    result["volumes"] = vol_out.splitlines() if vol_out else []
    result["volume_count"] = len(result["volumes"])

    # Docker Compose projects
    compose_out = _run([docker_bin, "compose", "ls", "--format", "json"])
    if compose_out:
        try:
            projects = json.loads(compose_out)
            result["compose_projects"] = [
                {"name": p.get("Name", ""), "status": p.get("Status", "")}
                for p in projects
            ]
        except json.JSONDecodeError:
            result["compose_projects"] = []

    return result

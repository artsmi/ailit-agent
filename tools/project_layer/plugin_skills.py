"""Тексты skills из установленных плагинов проекта (M.1)."""

from __future__ import annotations

from pathlib import Path

import yaml

from project_layer.loader import LoadedProject
from project_layer.plugin_manifest import AilitPluginManifestLoader


def _read_text_limited(path: Path, max_bytes: int) -> str:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="replace")


def collect_plugin_skill_snippets(
    loaded: LoadedProject,
    *,
    max_total_chars: int = 12_000,
    max_per_file: int = 6_000,
) -> str | None:
    """Собрать фрагменты markdown из плагинов под ``.ailit/plugins/*/``."""
    plugins_root = (loaded.root / ".ailit" / "plugins").resolve()
    if not plugins_root.is_dir():
        return None
    parts: list[str] = []
    used = 0
    for sub in sorted(plugins_root.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        try:
            manifest = AilitPluginManifestLoader.load_from_dir(sub)
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
            continue
        for rel in manifest.skills_paths:
            target = (manifest.plugin_root / rel).resolve()
            try:
                target.relative_to(manifest.plugin_root)
            except ValueError:
                continue
            if target.is_file():
                files = [target]
            elif target.is_dir():
                files = sorted(target.rglob("*.md"))[:20]
            else:
                continue
            for f in files:
                if used >= max_total_chars:
                    break
                chunk = _read_text_limited(f, max_per_file)
                block = f"### plugin:{manifest.name} `{f.relative_to(manifest.plugin_root).as_posix()}`\n\n{chunk}\n"
                if used + len(block) > max_total_chars:
                    block = block[: max_total_chars - used]
                parts.append(block)
                used += len(block)
        if used >= max_total_chars:
            break
    if not parts:
        return None
    return "\n".join(parts).strip()

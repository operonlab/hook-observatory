"""One-way sync from Obsidian vaults to Workshop docvault.

Public API:
    walk_vault(vault_path) -> Iterator[Path]
    compute_hash(path) -> str
    parse_frontmatter(path) -> tuple[dict, str]
    State.load(path) / state.is_changed(rel, hash) / state.record(rel, hash, doc_id)
    DocvaultAdapter(space_id).upload_markdown(file_path, vault, rel_path, base_tags)
    cli.main() — entry point for `python -m obsidian_sync`
"""
from .frontmatter import parse_frontmatter
from .state import State
from .walker import compute_hash, walk_vault

__all__ = [
    "DocvaultAdapter",
    "State",
    "compute_hash",
    "parse_frontmatter",
    "walk_vault",
]


def __getattr__(name: str):
    if name == "DocvaultAdapter":
        from .docvault_adapter import DocvaultAdapter

        return DocvaultAdapter
    raise AttributeError(name)

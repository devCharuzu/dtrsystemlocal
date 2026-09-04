"""Safe naming helpers for locally persisted uploads."""
from pathlib import Path


def validate_upload_filename(filename: str | None, extension: str) -> str:
    """Return a plain filename or raise ValueError for paths and wrong types."""
    if not isinstance(filename, str):
        raise ValueError("A filename is required.")
    name = filename.strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or Path(name).name != name
    ):
        raise ValueError("The upload must use a plain filename without folders.")
    if not name.lower().endswith(extension.lower()):
        raise ValueError(f"Filename must end with {extension}")
    return name


def is_safe_stored_path(path: Path, store: Path) -> bool:
    """Stored upload files must be direct children of their configured store."""
    return path.resolve().parent == store.resolve()

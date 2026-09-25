"""Upload validation (SRS Step 4 / Step 10 / file-upload security): type by magic bytes AND
extension, size limits, empty files, executables, zip-bomb guard, safe filenames."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

from supportnova.core.errors import ValidationFailed

from .sanitization import safe_filename

DOCUMENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
}
ATTACHMENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "txt": "text/plain",
}
EXECUTABLE_EXTENSIONS = {"exe", "dll", "bat", "cmd", "com", "msi", "scr", "ps1", "vbs", "js", "jar", "sh", "bin",
                         "app", "apk", "cpl", "hta", "lnk", "reg", "wsf", "py", "php"}
_MAX_DOCX_UNCOMPRESSED = 120 * 1024 * 1024
_MAX_ZIP_ENTRIES = 2000


@dataclass(frozen=True)
class ValidatedFile:
    file_name: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _looks_executable(data: bytes) -> bool:
    return data.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"#!"))


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        try:
            data[:65536].decode("cp1252")
        except UnicodeDecodeError:
            return False
    return True


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise ValidationFailed("The DOCX archive contains too many entries.")
            if sum(i.file_size for i in infos) > _MAX_DOCX_UNCOMPRESSED:
                raise ValidationFailed("The DOCX file expands to an unsafe size.")
            names = {i.filename for i in infos}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ValidationFailed("The file is not a valid Word (DOCX) document.")
            if any(n.lower().endswith((".bin", ".exe", ".dll")) or "vbaproject" in n.lower() for n in names):
                raise ValidationFailed("Documents with macros or embedded executables are not accepted.")
    except zipfile.BadZipFile as exc:
        raise ValidationFailed("The DOCX file is corrupted or not a valid archive.") from exc


def validate_upload(file_name: str, data: bytes, *, allowed: dict[str, str], max_bytes: int) -> ValidatedFile:
    """Raise ValidationFailed with a user-friendly message for any unsafe or unsupported file."""
    name = safe_filename(file_name)
    ext = _extension(name)
    if not data:
        raise ValidationFailed("The uploaded file is empty.", details={"file": name})
    if len(data) > max_bytes:
        raise ValidationFailed(f"The file exceeds the {max_bytes // (1024 * 1024)} MB limit.", details={"file": name})
    if ext in EXECUTABLE_EXTENSIONS or _looks_executable(data):
        raise ValidationFailed("Executable files are not accepted.", details={"file": name})
    if ext not in allowed:
        raise ValidationFailed(f"Unsupported file type '.{ext or '?'}'. Allowed: {', '.join(sorted(allowed))}.",
                               details={"file": name})
    if ext == "pdf" and not data.startswith(b"%PDF-"):
        raise ValidationFailed("The file does not look like a valid PDF.", details={"file": name})
    if ext == "docx":
        _check_docx(data)
    if ext == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationFailed("The file does not look like a valid PNG image.", details={"file": name})
    if ext in ("jpg", "jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise ValidationFailed("The file does not look like a valid JPEG image.", details={"file": name})
    if ext in ("txt", "md", "csv") and not _is_text(data):
        raise ValidationFailed("The text file contains binary data.", details={"file": name})
    return ValidatedFile(name, ext, allowed[ext], len(data), hashlib.sha256(data).hexdigest())

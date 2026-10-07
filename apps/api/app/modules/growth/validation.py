from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from app.core.errors import AppError

ALLOWED_EXTENSIONS = {
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".pdf": "document",
    ".docx": "document",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "spreadsheet",
    ".txt": "text",
    ".md": "text",
}
ALLOWED_PURPOSES = frozenset({"conversation", "meeting", "reference"})
GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream"})
EXPECTED_MIME_TYPES = {
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".xls": {"application/vnd.ms-excel"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
}
MAX_ARCHIVE_MEMBERS = 2_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def validate_material_upload(
    filename: str, mime_type: str, content: bytes, purpose: str
) -> tuple[str, str]:
    safe_name = Path(filename).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise AppError("INVALID_FILENAME", "文件名无效", status_code=400)
    if purpose not in ALLOWED_PURPOSES:
        raise AppError("INVALID_MATERIAL_PURPOSE", "资料用途不合法", status_code=422)
    if not content:
        raise AppError("EMPTY_FILE", "不能上传空文件", status_code=422)

    extension = Path(safe_name).suffix.lower()
    material_type = ALLOWED_EXTENSIONS.get(extension)
    if material_type is None:
        raise AppError(
            "UNSUPPORTED_MATERIAL_TYPE",
            "仅支持音频、截图、PDF、DOCX、Excel、CSV、Markdown 和 TXT 材料",
            status_code=415,
        )

    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    expected_mimes = EXPECTED_MIME_TYPES[extension]
    if normalized_mime not in GENERIC_MIME_TYPES and normalized_mime not in expected_mimes:
        raise AppError(
            "MATERIAL_TYPE_MISMATCH",
            "文件扩展名与声明的内容类型不一致",
            status_code=415,
        )

    _validate_signature(extension, content)
    return extension, material_type


def _validate_signature(extension: str, content: bytes) -> None:
    valid = True
    if extension == ".png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension in {".jpg", ".jpeg"}:
        valid = content.startswith(b"\xff\xd8\xff")
    elif extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension == ".xls":
        valid = content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif extension == ".wav":
        valid = content.startswith(b"RIFF") and content[8:12] == b"WAVE"
    elif extension == ".m4a":
        valid = len(content) >= 12 and content[4:8] == b"ftyp"
    elif extension == ".mp3":
        valid = content.startswith(b"ID3") or (
            len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
        )
    elif extension in {".docx", ".xlsx"}:
        marker = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
        valid = _validate_office_archive(content, marker)
    elif extension in {".txt", ".md", ".csv"}:
        valid = b"\x00" not in content[:8192]

    if not valid:
        error_codes = {
            ".pdf": ("PDF_PARSE_FAILED", "PDF 文件无法读取或已损坏"),
            ".docx": ("DOCX_PARSE_FAILED", "Word 文件无法读取或已损坏"),
            ".xlsx": ("SPREADSHEET_PARSE_FAILED", "Excel 文件无法读取或已损坏"),
            ".xls": ("SPREADSHEET_PARSE_FAILED", "Excel 文件无法读取或已损坏"),
        }
        error_code, message = error_codes.get(
            extension,
            ("MATERIAL_CONTENT_MISMATCH", "文件内容与扩展名不一致或文件已损坏"),
        )
        raise AppError(
            error_code,
            message,
            status_code=422,
        )


def _validate_office_archive(content: bytes, marker: str) -> bool:
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                return False
            if sum(item.file_size for item in members) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                return False
            return marker in {item.filename for item in members}
    except (BadZipFile, OSError, ValueError):
        return False

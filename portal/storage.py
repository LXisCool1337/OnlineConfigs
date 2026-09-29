"""Library layout on disk, manifests and ZIP export.

library/
  companies/<country>/<name>_<LEI>/<fiscal year>/annual_report_2019_en.pdf
                                   manifest.json
  industries/nace-28/statistics|studies|associations|peers/<peer>|web/...
                     manifest.json
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
import zipfile
from pathlib import Path

from .db import now_iso

STORED_TYPES = {".pdf", ".zip", ".png", ".jpg", ".gz"}  # already compressed: store as-is in ZIP exports


def slugify(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:maxlen].rstrip("-") or "unbenannt"


class Library:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._reserve_lock = threading.Lock()
        self._reserved: set[Path] = set()

    def company_dir(self, company: dict) -> Path:
        """The company's folder. An existing folder for the LEI is reused, so a changed name or country
        (GLEIF rename, universe sync) does not split the documents over two folders."""
        lei = company["lei"]
        if re.fullmatch(r"[A-Z0-9]{20}", lei or ""):
            existing = sorted(p for p in (self.root / "companies").glob(f"*/*_{lei}") if p.is_dir())
            if existing:
                return existing[0]
        country = (company.get("country") or "XX").upper()
        return self.root / "companies" / country / f"{slugify(company.get('name') or '', 50)}_{lei}"

    def industry_dir(self, nace: str) -> Path:
        return self.root / "industries" / f"nace-{nace.replace('.', '')}"

    def exports_dir(self) -> Path:
        path = self.root / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reserve(self, path: Path) -> Path:
        """A free file name (``path``, else name_2, name_3, …), safe across download threads: a returned
        path is handed out only once until ``release``, so parallel downloads never share a (.part) file."""
        with self._reserve_lock:
            for n in range(1, 1000):
                candidate = path if n == 1 else path.with_name(f"{path.stem}_{n}{path.suffix}")
                if candidate not in self._reserved and not candidate.exists():
                    self._reserved.add(candidate)
                    return candidate
        raise FileExistsError(path)

    def release(self, path: Path) -> None:
        with self._reserve_lock:
            self._reserved.discard(path)

    def relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def absolute(self, relative: str) -> Path:
        """Resolve a stored relative path, refusing anything outside the library."""
        path = (self.root / relative).resolve()
        if self.root != path and self.root not in path.parents:
            raise PermissionError(relative)
        return path

    def write_manifest(self, directory: Path, header: dict, documents: list[dict]) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        entries = []
        for doc in documents:
            entries.append({
                "file": Path(os.path.relpath(self.absolute(doc["path"]), directory)).as_posix() if doc.get("path")
                else None,
                "category": doc.get("category"),
                "fiscal_year": doc.get("fiscal_year"),
                "fy_label": doc.get("fy_label"),
                "period_end": doc.get("period_end"),
                "language": doc.get("language"),
                "title": doc.get("title"),
                "source": doc.get("source"),
                "source_url": doc.get("source_url"),
                "sha256": doc.get("sha256"),
                "size": doc.get("size"),
                "retrieved_at": doc.get("created_at"),
                "lei": doc.get("lei"),
            })
        payload = {"generated_at": now_iso(), **header, "documents": entries}
        target = directory / "manifest.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return target

    def build_zip(self, directory: Path, name: str) -> Path:
        """Pack a company or industry folder into library/exports/<name>.zip."""
        target = self.exports_dir() / f"{slugify(name, 80)}.zip"
        # A temp file of its own per call: two simultaneous exports must not write into the same file.
        fd, tmp_name = tempfile.mkstemp(prefix=target.stem + ".", suffix=".zip.tmp", dir=target.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w") as zf:
                for path in sorted(directory.rglob("*")):
                    if not path.is_file() or path.name.endswith((".part", ".tmp")):
                        continue
                    method = zipfile.ZIP_STORED if path.suffix.lower() in STORED_TYPES else zipfile.ZIP_DEFLATED
                    zf.write(path, arcname=f"{directory.name}/{path.relative_to(directory).as_posix()}",
                             compress_type=method)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return target

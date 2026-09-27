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

    def company_dir(self, company: dict) -> Path:
        country = (company.get("country") or "XX").upper()
        return self.root / "companies" / country / f"{slugify(company.get('name') or '', 50)}_{company['lei']}"

    def industry_dir(self, nace: str) -> Path:
        return self.root / "industries" / f"nace-{nace.replace('.', '')}"

    def exports_dir(self) -> Path:
        path = self.root / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def unique(path: Path) -> Path:
        if not path.exists():
            return path
        for n in range(2, 1000):
            candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(path)

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
                "file": Path(self.absolute(doc["path"])).relative_to(directory).as_posix() if doc.get("path") else None,
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
        tmp = target.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w") as zf:
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or path.name.endswith((".part", ".tmp")):
                    continue
                method = zipfile.ZIP_STORED if path.suffix.lower() in STORED_TYPES else zipfile.ZIP_DEFLATED
                zf.write(path, arcname=f"{directory.name}/{path.relative_to(directory).as_posix()}",
                         compress_type=method)
        os.replace(tmp, target)
        return target

"""Load resume text from .pdf / .docx / .txt / .md files."""
import os
import subprocess


def load_resume_text(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Resume not found at {path}. Drop your resume there "
            "(pdf/docx/txt/md) or change resume_path in config.json."
        )
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == ".pdf":
        return _pdf_text(path)
    if ext in (".docx", ".doc", ".rtf"):
        return _textutil_text(path)
    raise ValueError(f"Unsupported resume format: {ext}")


def _pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError(
            "pypdf is not installed. Run: .venv/bin/pip install pypdf "
            "(or export your resume as .txt)."
        )
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _textutil_text(path: str) -> str:
    # macOS built-in converter for doc/docx/rtf
    out = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", path],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"textutil failed to read {path}: {out.stderr.strip()}")
    return out.stdout

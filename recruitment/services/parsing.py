import contextlib
from pathlib import Path
from html import unescape
from html.parser import HTMLParser
import shutil
import subprocess
import tempfile

import fitz
import pytesseract
from django.conf import settings
from docx import Document
from PIL import Image

from recruitment.models import ResumeVersion


class ResumeParseError(RuntimeError):
    pass


@contextlib.contextmanager
def local_file_from_field(field_file, suffix=""):
    """
    Yields a local filesystem path for a Django FieldFile.
    Works seamlessly with both local FileSystemStorage and remote storages (S3/MinIO).
    """
    try:
        yield field_file.path
    except (NotImplementedError, AttributeError):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            field_file.open("rb")
            try:
                for chunk in field_file.chunks():
                    tmp.write(chunk)
                tmp.flush()
                tmp_path = tmp.name
            finally:
                field_file.close()
        try:
            yield tmp_path
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


class ResumeHTMLTextParser(HTMLParser):
    block_tags = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }
    ignored_tags = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored_tags:
            self.ignored_depth += 1
        elif tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ignored_tags and self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth and data.strip():
            self.parts.append(data)

    def text(self):
        lines = []
        for line in unescape("".join(self.parts)).splitlines():
            normalized = " ".join(line.split())
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)


def parse_pdf(path):
    document = fitz.open(path)
    text = "\n".join(page.get_text("text") for page in document)
    if text.strip():
        return text
    tesseract_available = bool(
        getattr(settings, "TESSERACT_CMD", "") or shutil.which("tesseract")
    )
    if tesseract_available:
        if getattr(settings, "TESSERACT_CMD", ""):
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
        parts = []
        for page in document:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            parts.append(pytesseract.image_to_string(image, lang="chi_sim+eng"))
        return "\n".join(parts)
    return ""


def parse_docx(path):
    document = Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def parse_doc(path):
    result = subprocess.run(
        ["antiword", path],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return result.stdout.decode("utf-8", errors="ignore")


def parse_html(path):
    raw = Path(path).read_bytes()
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("utf-8", errors="ignore")
    parser = ResumeHTMLTextParser()
    parser.feed(text)
    return parser.text()


def parse_path(path, suffix):
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".doc":
        return parse_doc(path)
    if suffix in {".html", ".htm"}:
        return parse_html(path)
    return None


def parse_resume(resume):
    if not resume.source_file:
        raise ResumeParseError("简历源文件不存在。")
    suffix = Path(
        resume.original_filename or getattr(resume.source_file, "name", "")
    ).suffix.lower()
    resume.parse_status = ResumeVersion.ParseStatus.PARSING
    resume.save(update_fields=["parse_status"])
    try:
        with local_file_from_field(resume.source_file, suffix=suffix) as path:
            text = parse_path(path, suffix)
        used_standard_pdf = False
        if (text is None or len(text.strip()) < 200) and resume.standard_pdf:
            with local_file_from_field(resume.standard_pdf, suffix=".pdf") as std_path:
                standard_text = parse_pdf(std_path)
            if len(standard_text.strip()) > len((text or "").strip()):
                text = standard_text
                used_standard_pdf = True
        if text is None:
            resume.parse_status = ResumeVersion.ParseStatus.UNSUPPORTED
            resume.parse_error = f"暂不支持 {suffix or '未知'} 格式。"
            resume.save(update_fields=["parse_status", "parse_error"])
            return resume
        quality = min(100, round(len(text.strip()) / 20, 2))
        resume.extracted_text = text
        resume.parse_quality = quality
        if len(text.strip()) < 200:
            resume.parse_status = ResumeVersion.ParseStatus.LOW_QUALITY
            resume.parse_error = "提取文本过短，无法生成正式评分。"
        else:
            resume.parse_status = ResumeVersion.ParseStatus.SUCCESS
            resume.parse_error = (
                "源文件无法提取足够文本，已使用北森标准 PDF 解析。"
                if used_standard_pdf
                else ""
            )
    except Exception as exc:
        resume.parse_status = ResumeVersion.ParseStatus.FAILED
        resume.parse_error = str(exc)
    resume.save(
        update_fields=["extracted_text", "parse_quality", "parse_status", "parse_error"]
    )
    return resume

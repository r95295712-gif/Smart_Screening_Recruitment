import hashlib
from pathlib import Path

from django.core.files.base import ContentFile

from recruitment.models import ResumeVersion


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def save_resume_bytes(candidate, content, filename, mime_type="", source_type=None):
    content_hash = sha256_bytes(content)
    existing = ResumeVersion.objects.filter(
        candidate=candidate, content_hash=content_hash
    ).first()
    if existing:
        return existing, False
    resume = ResumeVersion(
        candidate=candidate,
        source_type=source_type or ResumeVersion.SourceType.ORIGIN,
        original_filename=Path(filename).name,
        mime_type=mime_type,
        content_hash=content_hash,
    )
    resume.source_file.save(Path(filename).name, ContentFile(content), save=False)
    resume.save()
    return resume, True


def attach_standard_pdf(resume, content, filename="standard-resume.pdf"):
    if content:
        resume.standard_pdf.save(Path(filename).name, ContentFile(content), save=False)
        resume.save(update_fields=["standard_pdf"])
    return resume

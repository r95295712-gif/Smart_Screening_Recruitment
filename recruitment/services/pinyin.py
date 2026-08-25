import re
import unicodedata
from django.conf import settings

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:
    lazy_pinyin = None


def name_to_pinyin(name: str) -> str:
    """
    Convert a person's name (Chinese characters or Latin letters) to clean lowercase pinyin without spaces/tones.
    e.g. "张三" -> "zhangsan", "张玉凡" -> "zhangyufan", "John Doe" -> "johndoe"
    """
    raw = str(name or "").strip()
    if not raw:
        return ""

    if lazy_pinyin is not None:
        try:
            parts = lazy_pinyin(raw, style=Style.NORMAL, errors="ignore")
            result = "".join(parts).lower()
            clean = re.sub(r"[^a-z0-9]", "", result)
            if clean:
                return clean
        except Exception:
            pass

    # Fallback for ascii/latin names
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_bytes = normalized.encode("ascii", "ignore")
    clean = re.sub(r"[^a-z0-9]", "", ascii_bytes.decode("ascii").lower())
    return clean


def name_to_reviewer_email(name: str, domain: str = "") -> str:
    """
    Generate email address for a reviewer based on pinyin.
    e.g. "张三" -> "zhangsan@nuptio.net"
    """
    target_domain = (domain or getattr(settings, "DEFAULT_REVIEWER_EMAIL_DOMAIN", "nuptio.net")).lstrip("@").strip()
    if not target_domain:
        target_domain = "nuptio.net"
    pinyin = name_to_pinyin(name)
    if not pinyin:
        return ""
    return f"{pinyin}@{target_domain}"

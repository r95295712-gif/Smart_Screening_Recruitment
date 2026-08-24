from email.utils import parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

from .services import token_for_batch


def public_review_url(batch):
    return (
        f"{settings.PUBLIC_REVIEW_BASE_URL.rstrip('/')}"
        f"/reviews/public/{batch.public_id}/{token_for_batch(batch)}/"
    )


def send_review_email(batch):
    review_url = public_review_url(batch)
    subject = f"【智筛招聘】{batch.position} 待审核简历"
    body = "\n".join(
        [
            f"{batch.reviewer.name}，您好：",
            f"岗位：{batch.position}",
            f"待审核数量：{batch.items.exclude(decision='withdrawn').count()}",
            f"截止时间：{batch.expires_at:%Y-%m-%d %H:%M}",
            f"审核链接：{review_url}",
            "",
            "邮件不附加简历或报告文件，请通过审核链接在线查看简历和 AI 分析报告。",
        ]
    )
    html_body = f"""
    <!doctype html>
    <html lang="zh-CN">
      <body style="margin:0;background:#f4f6fb;font-family:Arial,'Microsoft YaHei',sans-serif;color:#172033;">
        <div style="max-width:620px;margin:0 auto;padding:32px 16px;">
          <div style="background:#ffffff;border-radius:14px;padding:28px;box-shadow:0 6px 24px rgba(31,45,76,.08);">
            <h1 style="margin:0 0 20px;font-size:22px;">待审核简历</h1>
            <p>{escape(batch.reviewer.name)}，您好：</p>
            <p><strong>岗位：</strong>{escape(str(batch.position))}</p>
            <p><strong>待审核数量：</strong>{batch.items.exclude(decision='withdrawn').count()}</p>
            <p><strong>截止时间：</strong>{batch.expires_at:%Y-%m-%d %H:%M}</p>
            <p style="margin:28px 0;">
              <a href="{escape(review_url)}" style="display:inline-block;padding:12px 22px;border-radius:8px;background:#3157d5;color:#ffffff;text-decoration:none;font-weight:700;">打开审核页面</a>
            </p>
            <p style="font-size:13px;color:#667085;">如果按钮无法打开，请复制以下地址到浏览器：</p>
            <p style="font-size:13px;word-break:break-all;"><a href="{escape(review_url)}">{escape(review_url)}</a></p>
            <p style="font-size:13px;color:#667085;">邮件不附加简历或报告文件，请通过审核页面在线查看简历和 AI 分析报告。</p>
          </div>
        </div>
      </body>
    </html>
    """
    configured_from = settings.DEFAULT_FROM_EMAIL.strip()
    display_name, address = parseaddr(configured_from)
    from_email = (
        configured_from
        if display_name
        else f"智筛招聘 <{address or configured_from}>"
    )
    message = EmailMultiAlternatives(
        subject,
        body,
        from_email,
        [batch.reviewer.email],
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=False)

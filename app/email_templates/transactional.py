from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from app.schemas.email_template import EmailTemplateContent, EmailTemplatesContent


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


DEFAULT_EMAIL_TEMPLATES = EmailTemplatesContent.model_validate({
    "email_verification": {
        "subject": "Verify your email to finish setting up Tatparya",
        "preheader": "Confirm your email address to activate your Tatparya account.",
        "title": "Verify your email address",
        "body": "Hi {{user_name}},\n\nWelcome to Tatparya.\n\nConfirm your email to finish setting up your account and start turning business data into clear findings, visuals, and recommendations.",
        "action_label": "Verify email address",
        "notice": "This link expires in 24 hours. If you did not create a Tatparya account, you can safely ignore this email.",
    },
    "password_reset": {
        "subject": "Reset your Tatparya password",
        "preheader": "Use this secure link to create a new password.",
        "title": "Reset your password",
        "body": "Hi {{user_name}},\n\nWe received a request to reset the password for your Tatparya account.",
        "action_label": "Reset password",
        "notice": "This link expires in one hour and can only be used once. If you did not request a password reset, no action is required. Never share this link with anyone.",
    },
    "password_changed": {
        "subject": "Your Tatparya password was changed",
        "preheader": "Your password has been updated and existing sessions were signed out.",
        "title": "Your password was changed",
        "body": "Hi {{user_name}},\n\nThe password for your Tatparya account was successfully changed on {{changed_at}}.\n\nFor your protection, your other active sessions have been signed out. If you made this change, no further action is required.",
        "action_label": "Secure my account",
        "notice": "If you did not make this change, reset your password immediately and contact Tatparya support.",
    },
    "payment_confirmation": {
        "subject": "Your Tatparya credits are ready",
        "preheader": "Payment confirmed—{{credits_added}} credits have been added to your account.",
        "title": "Your credits are ready",
        "body": "Hi {{user_name}},\n\nYour payment was successful, and the purchased credits are now available in your Tatparya workspace.",
        "action_label": "Open Tatparya workspace",
        "notice": "Keep this email for your records. If the credits do not appear, contact support and include the payment ID above.",
        "details": [
            {"label": "Plan", "value": "{{plan_name}}"},
            {"label": "Credits added", "value": "{{credits_added}}"},
            {"label": "Current balance", "value": "{{credit_balance}}"},
            {"label": "Amount paid", "value": "{{formatted_amount}}"},
            {"label": "Payment ID", "value": "{{payment_id}}"},
            {"label": "Date", "value": "{{payment_date}}"},
        ],
    },
    "credit_adjusted": {
        "subject": "Your Tatparya credit balance was updated",
        "preheader": "An administrator has updated the credits in your account.",
        "title": "Your credit balance was updated",
        "body": "Hi {{user_name}},\n\nAn administrator updated the credit balance associated with your Tatparya account.",
        "action_label": "View your workspace",
        "notice": "If you were not expecting this change, contact Tatparya support.",
        "details": [
            {"label": "Previous balance", "value": "{{previous_balance}}"},
            {"label": "Adjustment", "value": "{{signed_adjustment}}"},
            {"label": "New balance", "value": "{{new_balance}}"},
            {"label": "Reason", "value": "{{adjustment_reason}}"},
        ],
    },
    "account_deleted": {
        "subject": "Your Tatparya account has been deleted",
        "preheader": "Your account deletion request has been completed.",
        "title": "Your account has been deleted",
        "body": "Hi {{user_name}},\n\nYour Tatparya account was permanently deleted on {{deleted_at}}.\n\nYour account access has been removed, and your stored datasets are no longer available through Tatparya.",
        "notice": "If you did not request this deletion, contact Tatparya support immediately at {{support_email}}.",
    },
    "contact_reply": {
        "subject": "Re: {{original_subject}}",
        "preheader": "The Tatparya team has replied to your message.",
        "title": "A reply from Tatparya",
        "body": "Hi {{contact_name}},\n\nThank you for contacting Tatparya about “{{original_subject}}”.\n\n{{reply_message}}",
        "notice": "This reply relates to the message you submitted through the Tatparya website.",
    },
})


def _absolute_url(frontend_url: str, path: str) -> str:
    return urljoin(f"{frontend_url.rstrip('/')}/", path.lstrip("/"))


def _format_datetime(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%d %b %Y at %H:%M UTC")


def _format_amount(amount_minor: int, currency: str) -> str:
    amount = amount_minor / 100
    return f"₹{amount:,.2f}" if currency.upper() == "INR" else f"{currency.upper()} {amount:,.2f}"


def _fill(value: str | None, variables: dict[str, str]) -> str | None:
    if value is None:
        return None
    rendered = value
    for name, replacement in variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", replacement)
    return rendered


def _render(
    *,
    template: EmailTemplateContent,
    variables: dict[str, str],
    frontend_url: str,
    support_email: str,
    action_url: str | None = None,
) -> RenderedEmail:
    subject = _fill(template.subject, variables) or template.subject
    preheader = _fill(template.preheader, variables) or template.preheader
    title = _fill(template.title, variables) or template.title
    paragraphs = [part.strip() for part in (_fill(template.body, variables) or "").split("\n\n") if part.strip()]
    action_label = _fill(template.action_label, variables)
    notice = _fill(template.notice, variables)
    details = [
        (_fill(item.label, variables) or item.label, _fill(item.value, variables) or item.value)
        for item in template.details
    ]

    text_lines: list[str] = []
    for paragraph in paragraphs:
        text_lines.extend([paragraph, ""])
    if details:
        text_lines.extend([f"{label}: {value}" for label, value in details])
    if action_label and action_url:
        text_lines.extend(["", action_label, action_url])
    if notice:
        text_lines.extend(["", notice])
    text_lines.extend(["", "— The Tatparya team", "", f"Support: {support_email}"])

    paragraph_html = "".join(
        f'<p style="margin:0 0 16px;color:#475569;font-size:16px;line-height:1.65;">{escape(value)}</p>'
        for value in paragraphs
    )
    details_html = ""
    if details:
        rows = "".join(
            '<tr>'
            f'<td style="padding:10px 12px;color:#64748b;font-size:14px;border-bottom:1px solid #e2e8f0;">{escape(label)}</td>'
            f'<td style="padding:10px 12px;color:#0f172a;font-size:14px;font-weight:600;text-align:right;border-bottom:1px solid #e2e8f0;">{escape(value)}</td>'
            '</tr>'
            for label, value in details
        )
        details_html = f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:8px 0 24px;border:1px solid #e2e8f0;border-radius:12px;border-collapse:separate;overflow:hidden;">{rows}</table>'
    action_html = ""
    fallback_html = ""
    if action_label and action_url:
        safe_url = escape(action_url, quote=True)
        action_html = (
            '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:8px 0 24px;"><tr><td>'
            f'<a href="{safe_url}" style="display:inline-block;padding:13px 22px;border-radius:10px;background:#315cf4;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;">{escape(action_label)}</a>'
            '</td></tr></table>'
        )
        fallback_html = (
            '<p style="margin:0 0 20px;color:#64748b;font-size:12px;line-height:1.6;">If the button does not work, copy and paste this address into your browser:<br>'
            f'<a href="{safe_url}" style="color:#315cf4;word-break:break-all;">{safe_url}</a></p>'
        )
    notice_html = (
        f'<div style="margin-top:20px;padding:14px 16px;border-radius:10px;background:#f1f5f9;color:#475569;font-size:13px;line-height:1.6;">{escape(notice)}</div>'
        if notice
        else ""
    )
    root = frontend_url.rstrip("/")
    logo_url = escape(f"{root}/brand/logo2.png", quote=True)
    privacy_url = escape(_absolute_url(root, "/privacy"), quote=True)
    terms_url = escape(_absolute_url(root, "/terms"), quote=True)
    support_href = escape(f"mailto:{support_email}", quote=True)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#eef4ff;font-family:Arial,Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef4ff;"><tr><td align="center" style="padding:32px 14px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;">
    <tr><td style="padding:0 4px 20px;"><a href="{escape(root, quote=True)}" style="text-decoration:none;"><img src="{logo_url}" width="150" alt="Tatparya" style="display:block;width:150px;max-width:100%;height:auto;border:0;"></a></td></tr>
    <tr><td style="padding:34px 30px;background:#ffffff;border:1px solid #dbe5f5;border-radius:18px;box-shadow:0 10px 30px rgba(15,38,87,.08);">
      <h1 style="margin:0 0 20px;color:#102044;font-size:28px;line-height:1.2;letter-spacing:-.5px;">{escape(title)}</h1>
      {paragraph_html}{details_html}{action_html}{fallback_html}{notice_html}
      <p style="margin:24px 0 0;color:#475569;font-size:14px;line-height:1.6;">— The Tatparya team</p>
    </td></tr>
    <tr><td align="center" style="padding:22px 12px;color:#64748b;font-size:12px;line-height:1.7;">
      This is a service email from Tatparya.<br>
      <a href="{privacy_url}" style="color:#315cf4;text-decoration:none;">Privacy Policy</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="{terms_url}" style="color:#315cf4;text-decoration:none;">Terms</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="{support_href}" style="color:#315cf4;text-decoration:none;">Support</a>
    </td></tr>
  </table>
</td></tr></table></body></html>"""
    return RenderedEmail(subject=subject, text="\n".join(text_lines).strip(), html=html)


def email_verification_email(*, user_name: str, verification_url: str, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.email_verification, variables={"user_name": user_name.strip() or "there"}, action_url=verification_url, frontend_url=frontend_url, support_email=support_email)


def password_reset_email(*, user_name: str, reset_url: str, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.password_reset, variables={"user_name": user_name.strip() or "there"}, action_url=reset_url, frontend_url=frontend_url, support_email=support_email)


def password_changed_email(*, user_name: str, changed_at: datetime, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.password_changed, variables={"user_name": user_name.strip() or "there", "changed_at": _format_datetime(changed_at)}, action_url=_absolute_url(frontend_url, "/forgot-password"), frontend_url=frontend_url, support_email=support_email)


def payment_confirmation_email(*, user_name: str, plan_name: str, credits_added: int, credit_balance: int, amount_minor: int, currency: str, payment_id: str, paid_at: datetime, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    variables = {"user_name": user_name.strip() or "there", "plan_name": plan_name, "credits_added": str(credits_added), "credit_balance": str(credit_balance), "formatted_amount": _format_amount(amount_minor, currency), "payment_id": payment_id, "payment_date": _format_datetime(paid_at)}
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.payment_confirmation, variables=variables, action_url=_absolute_url(frontend_url, "/dashboard"), frontend_url=frontend_url, support_email=support_email)


def credit_adjusted_email(*, user_name: str, previous_balance: int, adjustment: int, new_balance: int, reason: str, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    sign = "+" if adjustment > 0 else ""
    variables = {"user_name": user_name.strip() or "there", "previous_balance": str(previous_balance), "signed_adjustment": f"{sign}{adjustment} credits", "new_balance": str(new_balance), "adjustment_reason": reason}
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.credit_adjusted, variables=variables, action_url=_absolute_url(frontend_url, "/dashboard"), frontend_url=frontend_url, support_email=support_email)


def account_deleted_email(*, user_name: str, deleted_at: datetime, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    variables = {"user_name": user_name.strip() or "there", "deleted_at": _format_datetime(deleted_at), "support_email": support_email}
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.account_deleted, variables=variables, frontend_url=frontend_url, support_email=support_email)


def contact_reply_email(*, contact_name: str, original_subject: str, reply_message: str, frontend_url: str, support_email: str, template: EmailTemplateContent | None = None) -> RenderedEmail:
    variables = {
        "contact_name": contact_name.strip() or "there",
        "original_subject": original_subject.strip() or "Your Tatparya enquiry",
        "reply_message": reply_message.strip(),
    }
    return _render(template=template or DEFAULT_EMAIL_TEMPLATES.contact_reply, variables=variables, frontend_url=frontend_url, support_email=support_email)

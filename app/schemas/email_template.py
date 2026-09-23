import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


VARIABLE_PATTERN = re.compile(r"{{[^{}]+}}")

TEMPLATE_VARIABLES: dict[str, tuple[str, ...]] = {
    "email_verification": ("{{user_name}}",),
    "password_reset": ("{{user_name}}",),
    "password_changed": ("{{user_name}}", "{{changed_at}}"),
    "payment_confirmation": (
        "{{user_name}}", "{{plan_name}}", "{{credits_added}}", "{{credit_balance}}",
        "{{formatted_amount}}", "{{payment_id}}", "{{payment_date}}",
    ),
    "credit_adjusted": (
        "{{user_name}}", "{{previous_balance}}", "{{signed_adjustment}}",
        "{{new_balance}}", "{{adjustment_reason}}",
    ),
    "account_deleted": ("{{user_name}}", "{{deleted_at}}", "{{support_email}}"),
}


class EmailDetailTemplate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=300)


class EmailTemplateContent(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    preheader: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    action_label: str | None = Field(default=None, max_length=100)
    notice: str | None = Field(default=None, max_length=2000)
    details: list[EmailDetailTemplate] = Field(default_factory=list, max_length=12)

    @field_validator("subject", "preheader", "title")
    @classmethod
    def normalize_single_line_text(cls, value: str) -> str:
        normalized = value.strip()
        if "\n" in normalized or "\r" in normalized:
            raise ValueError("Email subject, preview text, and heading must stay on one line.")
        return normalized


class EmailTemplatesContent(BaseModel):
    email_verification: EmailTemplateContent
    password_reset: EmailTemplateContent
    password_changed: EmailTemplateContent
    payment_confirmation: EmailTemplateContent
    credit_adjusted: EmailTemplateContent
    account_deleted: EmailTemplateContent

    @model_validator(mode="after")
    def preserve_template_variables(self):
        for template_name, required in TEMPLATE_VARIABLES.items():
            template = getattr(self, template_name)
            if template_name != "account_deleted" and not (template.action_label or "").strip():
                raise ValueError(f"{template_name} must keep a button label")
            editable_text = "\n".join(
                [
                    template.subject,
                    template.preheader,
                    template.title,
                    template.body,
                    template.action_label or "",
                    template.notice or "",
                    *[item.label for item in template.details],
                    *[item.value for item in template.details],
                ]
            )
            found = set(VARIABLE_PATTERN.findall(editable_text))
            allowed = set(required)
            missing = sorted(allowed - found)
            unknown = sorted(found - allowed)
            if missing:
                raise ValueError(f"{template_name} must keep these variables: {', '.join(missing)}")
            if unknown:
                raise ValueError(f"{template_name} contains unsupported variables: {', '.join(unknown)}")
        return self


class EmailTemplatesUpdate(BaseModel):
    content: EmailTemplatesContent


class EmailTemplatesResponse(BaseModel):
    content: EmailTemplatesContent
    variables: dict[str, list[str]]
    version: int = 0
    updated_at: datetime | None = None

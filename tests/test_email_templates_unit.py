from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.email_templates import (
    DEFAULT_EMAIL_TEMPLATES,
    account_deleted_email,
    credit_adjusted_email,
    contact_reply_email,
    email_verification_email,
    password_changed_email,
    password_reset_email,
    payment_confirmation_email,
)
from app.schemas.admin_user import CreditAdjustment
from app.schemas.email_template import EmailTemplatesContent


COMMON = {
    "frontend_url": "https://tatparya.example",
    "support_email": "support@tatparya.example",
}


def test_verification_template_has_html_text_and_escaped_user_content():
    email = email_verification_email(
        user_name='<script>alert("x")</script>',
        verification_url="https://tatparya.example/verify-email?token=secret",
        **COMMON,
    )

    assert email.subject == "Verify your email to finish setting up Tatparya"
    assert "https://tatparya.example/verify-email?token=secret" in email.text
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
    assert "/privacy" in email.html
    assert "/terms" in email.html


def test_all_transactional_templates_render_both_mime_bodies():
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    emails = [
        password_reset_email(user_name="Dhruv", reset_url="https://tatparya.example/reset-password?token=secret", **COMMON),
        password_changed_email(user_name="Dhruv", changed_at=now, **COMMON),
        payment_confirmation_email(user_name="Dhruv", plan_name="Growth", credits_added=25, credit_balance=30, amount_minor=49900, currency="INR", payment_id="pay_test123", paid_at=now, **COMMON),
        credit_adjusted_email(user_name="Dhruv", previous_balance=5, adjustment=10, new_balance=15, reason="Customer support correction", **COMMON),
        account_deleted_email(user_name="Dhruv", deleted_at=now, **COMMON),
        contact_reply_email(contact_name="Dhruv", original_subject="Product demo", reply_message="We would be happy to help.", **COMMON),
    ]

    for email in emails:
        assert email.subject
        assert "Hi Dhruv" in email.text
        assert "<!doctype html>" in email.html
        assert "Tatparya" in email.html
        assert "support@tatparya.example" in email.text

    payment = emails[2]
    assert "₹499.00" in payment.text
    assert "25" in payment.text
    assert "pay_test123" in payment.text

    contact_reply = emails[-1]
    assert contact_reply.subject == "Re: Product demo"
    assert "We would be happy to help." in contact_reply.text


def test_credit_adjustment_requires_a_meaningful_reason():
    with pytest.raises(ValidationError):
        CreditAdjustment(delta=1, reason="   ")

    adjustment = CreditAdjustment(delta=1, reason="  Customer support correction  ")
    assert adjustment.reason == "Customer support correction"


def test_admin_template_copy_is_used_and_required_variables_are_protected():
    content = DEFAULT_EMAIL_TEMPLATES.model_dump(mode="python")
    content["email_verification"]["subject"] = "Complete your Tatparya setup"
    configured = EmailTemplatesContent.model_validate(content)
    email = email_verification_email(
        user_name="Dhruv",
        verification_url="https://tatparya.example/verify-email?token=secret",
        template=configured.email_verification,
        **COMMON,
    )
    assert email.subject == "Complete your Tatparya setup"

    content["email_verification"]["body"] = "Welcome without a protected name."
    with pytest.raises(ValidationError, match="must keep these variables"):
        EmailTemplatesContent.model_validate(content)

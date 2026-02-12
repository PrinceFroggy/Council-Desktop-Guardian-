"""Stripe webhook handler (optional).

Skeleton that:
- verifies webhook signature (if STRIPE_WEBHOOK_SECRET set)
- updates a local user plan in SQLite

Webhook endpoint:
  POST /saas/stripe/webhook
"""

from __future__ import annotations

import json
from typing import Dict, Any

from ..config import settings
from .db import update_user_plan


def handle_stripe_webhook(raw_body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    try:
        import stripe  # type: ignore
    except Exception as e:
        return {"ok": False, "error": "stripe not installed"}

    if not settings.STRIPE_SECRET_KEY:
        return {"ok": False, "error": "STRIPE_SECRET_KEY not set"}
    stripe.api_key = settings.STRIPE_SECRET_KEY

    event = None
    if settings.STRIPE_WEBHOOK_SECRET:
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not sig:
            return {"ok": False, "error": "missing stripe-signature header"}
        try:
            event = stripe.Webhook.construct_event(
                payload=raw_body,
                sig_header=sig,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except Exception as e:
            return {"ok": False, "error": f"bad signature: {str(e)[:120]}"}
    else:
        # No signature verification (dev only)
        try:
            event = json.loads(raw_body.decode("utf-8", errors="ignore"))
        except Exception:
            return {"ok": False, "error": "invalid json"}

    etype = event.get("type") if isinstance(event, dict) else None

    # Extremely minimal: look for customer email in customer object (best-effort)
    try:
        obj = (event.get("data") or {}).get("object") or {}
        email = obj.get("customer_email") or obj.get("email")
        customer = obj.get("customer") or obj.get("id")
    except Exception:
        email = None
        customer = None

    if etype in {"checkout.session.completed", "invoice.paid", "customer.subscription.created", "customer.subscription.updated"}:
        if email:
            update_user_plan(email=email, plan="pro", stripe_customer_id=str(customer) if customer else None)
        return {"ok": True, "event": etype, "email": email}

    if etype in {"customer.subscription.deleted", "invoice.payment_failed"}:
        if email:
            update_user_plan(email=email, plan="free", stripe_customer_id=str(customer) if customer else None)
        return {"ok": True, "event": etype, "email": email}

    return {"ok": True, "event": etype, "ignored": True}

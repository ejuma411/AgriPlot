import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from .bank_transfer_providers import BankTransferProviderError, get_bank_transfer_provider
from .models import BankBeneficiary, BankTransferRequest, PaymentDisbursement, PaymentRequest

logger = logging.getLogger(__name__)


class BankTransferService:
    @staticmethod
    def choose_rail(amount):
        provider = get_bank_transfer_provider()
        return provider.choose_rail(Decimal(str(amount)))

    @staticmethod
    def _beneficiary_from_details(details, user=None):
        if not details:
            raise ValidationError("Bank beneficiary details are required for bank transfer payouts.")

        bank_name = (details.get("bank_name") or "").strip()
        account_name = (details.get("bank_account_name") or details.get("account_name") or "").strip()
        account_number = (details.get("bank_account_number") or details.get("account_number") or "").strip()
        if not (bank_name and account_name and account_number):
            raise ValidationError("Bank name, account name, and account number are required.")

        beneficiary, _ = BankBeneficiary.objects.get_or_create(
            user=user,
            bank_name=bank_name,
            bank_code=(details.get("bank_code") or "").strip(),
            account_name=account_name,
            account_number=account_number,
            defaults={
                "legal_name": (details.get("legal_name") or account_name).strip(),
                "branch_name": (details.get("bank_branch") or details.get("branch_name") or "").strip(),
                "currency": (details.get("currency") or "KES").strip() or "KES",
                "metadata": {
                    "source": "payment_metadata",
                },
            },
        )

        updated_fields = []
        legal_name = (details.get("legal_name") or account_name).strip()
        if beneficiary.legal_name != legal_name:
            beneficiary.legal_name = legal_name
            updated_fields.append("legal_name")
        branch_name = (details.get("bank_branch") or details.get("branch_name") or "").strip()
        if beneficiary.branch_name != branch_name:
            beneficiary.branch_name = branch_name
            updated_fields.append("branch_name")
        currency = (details.get("currency") or "KES").strip() or "KES"
        if beneficiary.currency != currency:
            beneficiary.currency = currency
            updated_fields.append("currency")
        if details.get("bank_code", "").strip() and beneficiary.bank_code != details.get("bank_code").strip():
            beneficiary.bank_code = details.get("bank_code").strip()
            updated_fields.append("bank_code")
        if updated_fields:
            updated_fields.append("updated_at")
            beneficiary.save(update_fields=updated_fields)

        return beneficiary

    @staticmethod
    def beneficiary_for_payment(payment, user=None, details=None):
        metadata = dict(payment.metadata or {})
        merged_details = dict(metadata)
        if details:
            merged_details.update(details)

        if not any(
            merged_details.get(key)
            for key in ("bank_name", "bank_account_name", "bank_account_number", "account_name", "account_number")
        ):
            seller = payment.seller or user
            if seller:
                profile_name = seller.get_full_name() or seller.username
                merged_details.setdefault("legal_name", profile_name)
        return BankTransferService._beneficiary_from_details(merged_details, user=user or payment.seller)

    @staticmethod
    def create_transfer(
        payment,
        disbursement=None,
        beneficiary=None,
        details=None,
        rail=None,
        created_by=None,
        idempotency_key=None,
    ):
        if not isinstance(payment, PaymentRequest):
            raise ValidationError("A payment request is required.")
        if disbursement is not None and not isinstance(disbursement, PaymentDisbursement):
            raise ValidationError("Invalid disbursement record.")
        if disbursement is not None:
            existing_transfer = getattr(disbursement, "bank_transfer_request", None)
            if existing_transfer:
                return existing_transfer

        beneficiary = beneficiary or BankTransferService.beneficiary_for_payment(
            payment,
            user=disbursement.recipient_user if disbursement else payment.seller,
            details=details,
        )
        if not beneficiary:
            raise ValidationError("Bank beneficiary details are required.")

        payout_amount = disbursement.amount if disbursement else payment.seller_total_payout_amount
        payout_amount = Decimal(str(payout_amount)).quantize(Decimal("0.01"))
        provider = get_bank_transfer_provider(transfer=None)
        resolved_rail = rail or provider.choose_rail(payout_amount)

        transfer = BankTransferRequest.objects.create(
            payment=payment,
            disbursement=disbursement,
            beneficiary=beneficiary,
            beneficiary_name=beneficiary.legal_name or beneficiary.account_name,
            bank_name=beneficiary.bank_name,
            bank_code=beneficiary.bank_code,
            account_name=beneficiary.account_name,
            account_number=beneficiary.account_number,
            amount=payout_amount,
            currency=beneficiary.currency or "KES",
            rail=resolved_rail,
            provider=getattr(provider, "provider_name", "jenga"),
            status=BankTransferRequest.Status.QUEUED,
            idempotency_key=idempotency_key,
        )
        provider = get_bank_transfer_provider(transfer.provider, transfer=transfer)
        payload = provider.build_payload()
        transfer.request_payload = payload
        transfer.save(update_fields=["request_payload", "updated_at"])
        if created_by:
            payment.add_event(
                "bank_transfer_queued",
                f"Bank payout queued for {transfer.beneficiary_name} via {transfer.get_rail_display()}.",
                actor=created_by,
            )
        return transfer

    @staticmethod
    def submit_transfer(transfer_id, submitted_by=None):
        transfer = (
            BankTransferRequest.objects.select_related("payment", "disbursement", "beneficiary")
            .filter(Q(pk=transfer_id) | Q(reference=transfer_id))
            .first()
        )
        if not transfer:
            raise ValidationError("Bank transfer request not found.")
        if transfer.status in {BankTransferRequest.Status.SUBMITTED, BankTransferRequest.Status.PROCESSING, BankTransferRequest.Status.SETTLED}:
            return transfer

        provider = get_bank_transfer_provider(transfer.provider, transfer=transfer)
        with transaction.atomic():
            locked_transfer = BankTransferRequest.objects.select_for_update().get(pk=transfer.pk)
            if locked_transfer.status in {
                BankTransferRequest.Status.SUBMITTED,
                BankTransferRequest.Status.PROCESSING,
                BankTransferRequest.Status.SETTLED,
            }:
                return locked_transfer

            response = provider.submit()
            provider_reference = (
                response.get("providerReference")
                or response.get("transactionId")
                or response.get("conversationId")
                or response.get("ConversationID")
                or response.get("reference")
                or locked_transfer.reference
            )
            locked_transfer.provider_reference = provider_reference
            locked_transfer.provider_response = response
            locked_transfer.status = BankTransferRequest.Status.SUBMITTED
            locked_transfer.submitted_at = timezone.now()
            locked_transfer.save(
                update_fields=[
                    "provider_reference",
                    "provider_response",
                    "status",
                    "submitted_at",
                    "updated_at",
                ]
            )
            if submitted_by:
                locked_transfer.payment.add_event(
                    "bank_transfer_submitted",
                    f"Bank transfer submitted for {locked_transfer.beneficiary_name} via {locked_transfer.get_rail_display()}.",
                    actor=submitted_by,
                )
            return locked_transfer

    @staticmethod
    def handle_callback(payload, headers=None):
        headers = headers or {}
        provider_name = getattr(headers, "provider", None)
        provider = get_bank_transfer_provider(provider_name)
        if not provider.verify_callback(payload, headers):
            raise ValidationError("Bank transfer callback signature could not be verified.")

        reference = provider.extract_reference(payload)
        if not reference:
            raise ValidationError("Bank transfer callback is missing a transfer reference.")

        transfer = (
            BankTransferRequest.objects.select_related("payment", "disbursement", "beneficiary")
            .filter(Q(reference=reference) | Q(provider_reference=reference))
            .first()
        )
        if not transfer:
            logger.warning("Bank transfer callback could not be matched to a transfer: %s", reference)
            return None

        success_flag = payload.get("status") or payload.get("Status") or payload.get("resultCode") or payload.get("ResultCode")
        success = str(success_flag).lower() in {"0", "success", "successful", "settled", "completed", "true"}
        with transaction.atomic():
            locked_transfer = BankTransferRequest.objects.select_for_update().get(pk=transfer.pk)
            if locked_transfer.status in {BankTransferRequest.Status.SETTLED, BankTransferRequest.Status.RECONCILED}:
                return locked_transfer

            locked_transfer.callback_payload = payload
            if success:
                locked_transfer.status = BankTransferRequest.Status.SETTLED
                locked_transfer.completed_at = timezone.now()
                locked_transfer.provider_response = payload
                locked_transfer.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "callback_payload",
                        "provider_response",
                        "updated_at",
                    ]
                )
            else:
                reason = (
                    payload.get("message")
                    or payload.get("Message")
                    or payload.get("resultDesc")
                    or payload.get("ResultDesc")
                    or "Bank transfer failed."
                )
                locked_transfer.status = BankTransferRequest.Status.FAILED
                locked_transfer.failure_reason = reason
                locked_transfer.provider_response = payload
                locked_transfer.save(
                    update_fields=[
                        "status",
                        "failure_reason",
                        "callback_payload",
                        "provider_response",
                        "updated_at",
                    ]
                )

            if locked_transfer.disbursement_id:
                disbursement = locked_transfer.disbursement
                if success:
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        "bank_transfer_reference": locked_transfer.reference,
                        "provider_reference": locked_transfer.provider_reference,
                    }
                    disbursement.save(update_fields=["metadata", "updated_at"])
                else:
                    disbursement.metadata = {
                        **(disbursement.metadata or {}),
                        "bank_transfer_reference": locked_transfer.reference,
                        "bank_transfer_failure": locked_transfer.failure_reason,
                    }
                    disbursement.save(update_fields=["metadata", "updated_at"])

            return locked_transfer

    @staticmethod
    def queue_disbursement(disbursement, beneficiary=None, details=None, rail=None, created_by=None, idempotency_key=None):
        if not isinstance(disbursement, PaymentDisbursement):
            raise ValidationError("A payment disbursement is required.")
        if disbursement.payment.status not in {
            PaymentRequest.Status.IN_ESCROW,
            PaymentRequest.Status.PARTIALLY_RELEASED,
            PaymentRequest.Status.RELEASED,
        }:
            raise ValidationError("The payment must be ready for payout before queuing a bank transfer.")
        transfer = BankTransferService.create_transfer(
            payment=disbursement.payment,
            disbursement=disbursement,
            beneficiary=beneficiary,
            details=details,
            rail=rail,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        return transfer

    @staticmethod
    def reconcile_transfer(reference, payload=None):
        transfer = (
            BankTransferRequest.objects.select_related("payment", "disbursement", "beneficiary")
            .filter(Q(reference=reference) | Q(provider_reference=reference))
            .first()
        )
        if not transfer:
            raise ValidationError("Bank transfer request not found.")
        transfer.status = BankTransferRequest.Status.RECONCILED
        if payload is not None:
            transfer.callback_payload = payload
        transfer.reconciled_at = timezone.now()
        transfer.save(update_fields=["status", "callback_payload", "reconciled_at", "updated_at"])
        return transfer


def queue_bank_payout(disbursement, **kwargs):
    return BankTransferService.queue_disbursement(disbursement, **kwargs)

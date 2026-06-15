from types import SimpleNamespace

from django.test import SimpleTestCase

from .forms import TransactionDocumentForm
from .models import TransactionDocument


class TransactionDocumentFormTests(SimpleTestCase):
    def test_document_type_is_limited_to_current_stage_docs(self):
        transaction = SimpleNamespace(
            get_required_documents_for_stage=lambda: [
                TransactionDocument.DocType.OFFICIAL_SEARCH,
                TransactionDocument.DocType.SURVEY_MAP,
            ],
            get_stage_display=lambda: "Due Diligence",
        )

        form = TransactionDocumentForm(transaction=transaction)

        allowed = [choice[0] for choice in form.fields["document_type"].choices]
        self.assertEqual(
            allowed,
            [
                TransactionDocument.DocType.OFFICIAL_SEARCH,
                TransactionDocument.DocType.SURVEY_MAP,
            ],
        )

    def test_single_required_document_is_hidden_and_prefilled(self):
        transaction = SimpleNamespace(
            get_required_documents_for_stage=lambda: [TransactionDocument.DocType.NEW_TITLE_DEED],
            get_stage_display=lambda: "Registration",
        )

        form = TransactionDocumentForm(transaction=transaction)

        self.assertTrue(form.fields["document_type"].widget.is_hidden)
        self.assertEqual(
            form.fields["document_type"].initial,
            TransactionDocument.DocType.NEW_TITLE_DEED,
        )

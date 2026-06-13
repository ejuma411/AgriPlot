from django import forms
from django.core.exceptions import ValidationError
from .models import Transaction, TransactionDocument
from django.utils import timezone


class TransactionDocumentForm(forms.ModelForm):
    """Form for uploading legal documents with Kenyan law validation"""
    
    document_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Date on the document (e.g., LCB meeting date, search certificate date)"
    )
    reference_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="Reference number (LCB consent ref, Stamp Duty receipt ref, etc.)"
    )
    
    class Meta:
        model = TransactionDocument
        fields = ['document_type', 'file', 'reference_number', 'document_date']
    
    def __init__(self, *args, **kwargs):
        self.transaction = kwargs.pop('transaction', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter document type choices based on current stage
        if self.transaction:
            allowed_docs = self.transaction.get_required_documents_for_stage()
            self.fields['document_type'].choices = [
                (choice[0], choice[1]) for choice in self.fields['document_type'].choices 
                if choice[0] in allowed_docs
            ]
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.transaction = self.transaction
        instance.uploaded_by = self.user
        instance.status = 'pending'  # Default status
        if commit:
            instance.save()
        return instance

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if file.size > 20 * 1024 * 1024:
                raise ValidationError("File size must be less than 20MB")
            
            ext = file.name.split('.')[-1].lower()
            if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
                raise ValidationError("Only PDF, JPG, JPEG, and PNG files are allowed")
        return file
    
    def clean_document_date(self):
        """Validate document date is not in future"""
        doc_date = self.cleaned_data.get('document_date')
        if doc_date and doc_date > timezone.now().date():
            raise ValidationError("Document date cannot be in the future")
        return doc_date
    
    def clean(self):
        cleaned_data = super().clean()
        doc_type = cleaned_data.get('document_type')
        
        # LCB Consent requires meeting date and reference
        if doc_type == TransactionDocument.DocType.LCB_CONSENT:
            if not cleaned_data.get('document_date'):
                self.add_error('document_date', 'LCB meeting date is required for agricultural land transfers')
            if not cleaned_data.get('reference_number'):
                self.add_error('reference_number', 'LCB consent reference number is required')
        
        # Official search requires search date (valid for 30 days)
        if doc_type == TransactionDocument.DocType.OFFICIAL_SEARCH:
            if not cleaned_data.get('document_date'):
                self.add_error('document_date', 'Official search certificate date is required')
        
        # Stamp duty receipt requires receipt number
        if doc_type == TransactionDocument.DocType.STAMP_DUTY_RECEIPT:
            if not cleaned_data.get('reference_number'):
                self.add_error('reference_number', 'Stamp duty receipt number is required')
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.transaction = self.transaction
        instance.uploaded_by = self.user
        instance.filename = self.cleaned_data['file'].name
        instance.file_size = self.cleaned_data['file'].size
        instance.mime_type = self.cleaned_data['file'].content_type or 'application/octet-stream'
        instance.document_date = self.cleaned_data.get('document_date')
        instance.reference_number = self.cleaned_data.get('reference_number', '')
        
        if commit:
            instance.save()
        return instance


class TransactionAdvanceForm(forms.Form):
    """Form for advancing transaction stage with legal confirmation"""
    confirm_legal_requirements = forms.BooleanField(
        required=True,
        label="I confirm that all legal requirements for this stage have been met under the Land Act 2012",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional notes about this legal milestone...'}),
        help_text="Add any relevant notes about this stage (e.g., LCB meeting outcome)"
    )
    
    def clean_confirm_legal_requirements(self):
        confirmed = self.cleaned_data.get('confirm_legal_requirements')
        if not confirmed:
            raise ValidationError("You must confirm that all legal requirements are met before advancing")
        return confirmed
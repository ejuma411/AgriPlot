from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from .models import Transaction, TransactionDocument


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
        
        if self.transaction:
            # Get documents required for current stage
            allowed_docs = self.transaction.get_required_documents_for_stage()
            
            # Also allow documents from all stages for retrospective upload
            all_stage_docs = [
                TransactionDocument.DocType.OFFICIAL_SEARCH,
                TransactionDocument.DocType.SURVEY_MAP,
                TransactionDocument.DocType.LETTER_OF_OFFER,
                TransactionDocument.DocType.SALE_AGREEMENT,
                TransactionDocument.DocType.LCB_CONSENT,
                TransactionDocument.DocType.SPOUSAL_CONSENT,
                TransactionDocument.DocType.STAMP_DUTY_RECEIPT,
                TransactionDocument.DocType.VALUATION_REPORT,
                TransactionDocument.DocType.TRANSFER_FORM,
                TransactionDocument.DocType.ORIGINAL_TITLE_DEED,
                TransactionDocument.DocType.NEW_TITLE_DEED,
                TransactionDocument.DocType.ID_DOCUMENT,
                TransactionDocument.DocType.KRA_PIN,
                TransactionDocument.DocType.RATES_CLEARANCE,
                TransactionDocument.DocType.RENT_CLEARANCE,
                TransactionDocument.DocType.PASSPORT_PHOTO,
            ]
            
            # Combine current stage required docs with all docs for retrospective upload
            allowed_docs = list(set(allowed_docs + all_stage_docs))
            
            self.fields['document_type'].choices = [
                (choice[0], choice[1]) for choice in self.fields['document_type'].choices 
                if choice[0] in allowed_docs
            ]
    
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
            else:
                search_date = cleaned_data.get('document_date')
                if (timezone.now().date() - search_date).days > 30:
                    self.add_error('document_date', 'Official search certificate is older than 30 days. A fresh search is required.')
        
        # Stamp duty receipt (paid to KRA) requires receipt number
        if doc_type == TransactionDocument.DocType.STAMP_DUTY_RECEIPT:
            if not cleaned_data.get('reference_number'):
                self.add_error('reference_number', 'Stamp duty receipt number from KRA iTax is required')
            
            # Validate receipt format (KRA-YYYYMMDD-XXXXXX)
            receipt_number = cleaned_data.get('reference_number', '')
            if receipt_number:
                import re
                pattern = r'^KRA-\d{8}-\d{6}$'
                if not re.match(pattern, receipt_number):
                    self.add_error('reference_number', 'Invalid KRA receipt number format. Expected: KRA-YYYYMMDD-XXXXXX')
        
        # New Title Deed requires verification (must be after registration)
        if doc_type == TransactionDocument.DocType.NEW_TITLE_DEED:
            if not cleaned_data.get('document_date'):
                self.add_error('document_date', 'Title deed issue date is required')
            else:
                issue_date = cleaned_data.get('document_date')
                if issue_date and issue_date > timezone.now().date():
                    self.add_error('document_date', 'Title deed issue date cannot be in the future')
        
        # Sale Agreement requires advocates to be assigned
        if doc_type == TransactionDocument.DocType.SALE_AGREEMENT:
            if not self.transaction:
                self.add_error(None, 'Transaction must be specified before uploading sale agreement')
            elif not self.transaction.buyer_advocate:
                self.add_error(None, 'Buyer advocate must be assigned before uploading sale agreement')
            elif not self.transaction.seller_advocate:
                self.add_error(None, 'Seller advocate must be assigned before uploading sale agreement')
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.transaction:
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
    
    # Stage-specific fields
    lcb_meeting_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Date of Land Control Board meeting"
    )
    lcb_consent_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text="LCB consent reference number"
    )
    stamp_duty_rate = forms.ChoiceField(
        required=False,
        choices=[('2.00', '2% (Rural)'), ('4.00', '4% (Urban)')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Stamp duty rate based on property location"
    )
    stamp_duty_receipt_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'KRA-YYYYMMDD-XXXXXX'}),
        help_text="KRA iTax stamp duty receipt number (paid directly to KRA)"
    )
    confirm_disbursement = forms.BooleanField(
        required=False,
        label="I confirm that funds are ready for disbursement to seller (platform fee will be deducted)",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def __init__(self, *args, **kwargs):
        self.transaction = kwargs.pop('transaction', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Add stage-specific fields dynamically
        if self.transaction:
            self._add_stage_specific_fields()
    
    def _add_stage_specific_fields(self):
        """Add fields based on current stage"""
        if self.transaction.stage == Transaction.Stage.STATUTORY_CONSENTS:
            self.fields['lcb_meeting_date'].required = True
            self.fields['lcb_consent_reference'].required = True
            self.fields['confirm_legal_requirements'].label = (
                "I confirm that Land Control Board consent and spousal consent (if applicable) "
                "have been obtained under Cap 302 and LRA 2012"
            )
        
        elif self.transaction.stage == Transaction.Stage.TAXATION:
            self.fields['stamp_duty_rate'].required = True
            self.fields['stamp_duty_receipt_number'].required = True
            self.fields['confirm_legal_requirements'].label = (
                "I confirm that stamp duty has been paid directly to KRA via iTax and the receipt "
                "has been uploaded for verification"
            )
            
            # Set initial stamp duty rate based on plot zone
            if self.transaction.plot:
                default_rate = '2.00' if self.transaction.plot.market_zone == 'rural' else '4.00'
                self.fields['stamp_duty_rate'].initial = default_rate
        
        elif self.transaction.stage == Transaction.Stage.DISBURSEMENT:
            self.fields['confirm_disbursement'].required = True
            self.fields['confirm_legal_requirements'].label = (
                "I confirm that the new title deed has been issued in the buyer's name under "
                "Section 58-65 of the Land Registration Act 2012"
            )
    
    def clean_stamp_duty_receipt_number(self):
        """Validate stamp duty receipt number format (KRA receipt)"""
        receipt = self.cleaned_data.get('stamp_duty_receipt_number', '')
        if receipt:
            import re
            pattern = r'^KRA-\d{8}-\d{6}$'
            if not re.match(pattern, receipt):
                raise ValidationError(
                    "Invalid KRA receipt number format. Expected: KRA-YYYYMMDD-XXXXXX"
                )
        return receipt
    
    def clean(self):
        cleaned_data = super().clean()
        
        if not self.transaction:
            return cleaned_data
        
        # Stage-specific validations
        if self.transaction.stage == Transaction.Stage.STATUTORY_CONSENTS:
            lcb_date = cleaned_data.get('lcb_meeting_date')
            if lcb_date and lcb_date > timezone.now().date():
                self.add_error('lcb_meeting_date', 'LCB meeting date cannot be in the future')
        
        elif self.transaction.stage == Transaction.Stage.TAXATION:
            # Verify stamp duty rate matches property zone
            stamp_duty_rate = Decimal(cleaned_data.get('stamp_duty_rate', '0'))
            expected_rate = Decimal('2.00') if self.transaction.plot.market_zone == 'rural' else Decimal('4.00')
            
            if stamp_duty_rate != expected_rate:
                self.add_error(
                    'stamp_duty_rate',
                    f"Stamp duty rate should be {expected_rate}% for {self.transaction.plot.market_zone} land. "
                    f"Please adjust or confirm with the government valuation."
                )
        
        elif self.transaction.stage == Transaction.Stage.DISBURSEMENT:
            from .models import TransactionDocument
            
            # Verify new title deed is uploaded and verified
            new_title_verified = TransactionDocument.objects.filter(
                transaction=self.transaction,
                document_type=TransactionDocument.DocType.NEW_TITLE_DEED,
                status='verified'
            ).exists()
            
            if not new_title_verified and cleaned_data.get('confirm_disbursement'):
                self.add_error(
                    'confirm_disbursement',
                    "Cannot disburse funds. New title deed must be uploaded and verified first."
                )
            
            # Verify stamp duty is verified (paid to KRA)
            if not self.transaction.stamp_duty_receipt_verified_at:
                self.add_error(
                    'confirm_disbursement',
                    "Cannot disburse funds. Stamp duty payment to KRA must be verified first."
                )
            
            # Verify both deposit and balance are in escrow
            if self.transaction.deposit_paid < self.transaction.ten_percent_deposit:
                self.add_error(
                    'confirm_disbursement',
                    f"Cannot disburse funds. Deposit of {self.transaction.ten_percent_deposit:,.2f} not fully paid. "
                    f"Current deposit: {self.transaction.deposit_paid:,.2f}"
                )
            
            if self.transaction.balance_paid < self.transaction.ninety_percent_balance:
                self.add_error(
                    'confirm_disbursement',
                    f"Cannot disburse funds. Balance of {self.transaction.ninety_percent_balance:,.2f} not fully paid. "
                    f"Current balance: {self.transaction.balance_paid:,.2f}"
                )
        
        return cleaned_data


class TransactionCreateForm(forms.ModelForm):
    """Form for creating a new legal transaction"""
    
    confirm_terms = forms.BooleanField(
        required=True,
        label="I confirm that I have read and agree to the AgriPlot Terms of Service and Legal Framework",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = Transaction
        fields = ['agreed_price', 'notes']
        widgets = {
            'agreed_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Enter agreed sale price in KES'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Any special conditions or notes about this transaction...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.plot = kwargs.pop('plot', None)
        self.buyer = kwargs.pop('buyer', None)
        self.seller = kwargs.pop('seller', None)
        self.payment_request = kwargs.pop('payment_request', None)
        super().__init__(*args, **kwargs)
        
        if self.plot:
            self.fields['agreed_price'].initial = self.plot.sale_price or self.plot.price
            self.fields['agreed_price'].help_text = f"Based on plot listing price: KES {self.plot.sale_price or self.plot.price:,.2f}"
    
    def clean_agreed_price(self):
        price = self.cleaned_data.get('agreed_price')
        if price and price <= 0:
            raise ValidationError("Agreed price must be greater than zero")
        return price
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.plot = self.plot
        instance.buyer = self.buyer
        instance.seller = self.seller
        instance.payment_request = self.payment_request
        instance.transaction_type = Transaction.TransactionType.PURCHASE
        instance.stage = Transaction.Stage.DUE_DILIGENCE
        
        if commit:
            instance.save()
        return instance


class TransactionDocumentVerifyForm(forms.Form):
    """Form for admin verification of legal documents"""
    
    status = forms.ChoiceField(
        choices=[('verified', 'Verify Document'), ('rejected', 'Reject Document')],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'})
    )
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Reason for rejection...'}),
        help_text="Required if rejecting the document"
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Internal verification notes...'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        rejection_reason = cleaned_data.get('rejection_reason')
        
        if status == 'rejected' and not rejection_reason:
            self.add_error('rejection_reason', 'Please provide a reason for rejecting this document')
        
        return cleaned_data


class StampDutyVerificationForm(forms.Form):
    """Form for verifying stamp duty payment to KRA (Finance Admin only)"""
    
    receipt_number = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'KRA-YYYYMMDD-XXXXXX'}),
        help_text="Stamp duty receipt number from KRA iTax"
    )
    stamp_duty_amount = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text="Amount paid to KRA (should match assessment)"
    )
    confirm_kra_payment = forms.BooleanField(
        required=True,
        label="I confirm that stamp duty has been paid directly to KRA via iTax",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def clean_receipt_number(self):
        receipt = self.cleaned_data.get('receipt_number', '')
        import re
        pattern = r'^KRA-\d{8}-\d{6}$'
        if not re.match(pattern, receipt):
            raise ValidationError(
                "Invalid KRA receipt number format. Expected: KRA-YYYYMMDD-XXXXXX"
            )
        return receipt
    
    def clean_stamp_duty_amount(self):
        amount = self.cleaned_data.get('stamp_duty_amount')
        if amount and amount <= 0:
            raise ValidationError("Stamp duty amount must be greater than zero")
        return amount


class DisbursementAuthorizationForm(forms.Form):
    """Form for escrow admin to authorize fund disbursement to seller"""
    
    confirm_registration_complete = forms.BooleanField(
        required=True,
        label="I confirm that the new title deed has been issued in the buyer's name",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    confirm_stamp_duty_paid = forms.BooleanField(
        required=True,
        label="I confirm that stamp duty has been verified (paid directly to KRA)",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    platform_fee_percentage = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '1', 'max': '3'}),
        help_text="Platform fee percentage (1-3%) - will be deducted from seller proceeds"
    )
    authorize_disbursement = forms.BooleanField(
        required=True,
        label="I authorize the disbursement of funds to the seller after platform fee deduction",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Disbursement notes...'})
    )
    
    def __init__(self, *args, **kwargs):
        self.transaction = kwargs.pop('transaction', None)
        super().__init__(*args, **kwargs)
        
        if self.transaction:
            # Set initial platform fee percentage based on property value
            value = self.transaction.agreed_price
            if value < 1000000:
                initial_percentage = 3.0
            elif value < 5000000:
                initial_percentage = 2.5
            elif value < 10000000:
                initial_percentage = 2.0
            else:
                initial_percentage = 1.5
            self.fields['platform_fee_percentage'].initial = initial_percentage
    
    def clean_platform_fee_percentage(self):
        percentage = self.cleaned_data.get('platform_fee_percentage')
        if percentage and (percentage < 1 or percentage > 3):
            raise ValidationError("Platform fee must be between 1% and 3%")
        return percentage


class AdvocateAssignmentForm(forms.Form):
    """Form for assigning advocates to a transaction (required by Kenyan law)"""
    
    buyer_advocate_id = forms.IntegerField(
        widget=forms.HiddenInput(),
        required=False
    )
    seller_advocate_id = forms.IntegerField(
        widget=forms.HiddenInput(),
        required=False
    )
    confirm_advocate_engagement = forms.BooleanField(
        required=True,
        label="I confirm that licensed advocates have been engaged as required by the Advocates Act Cap 16",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def __init__(self, *args, **kwargs):
        self.transaction = kwargs.pop('transaction', None)
        super().__init__(*args, **kwargs)
        
        if self.transaction:
            self.fields['buyer_advocate_id'].initial = self.transaction.buyer_advocate_id
            self.fields['seller_advocate_id'].initial = self.transaction.seller_advocate_id
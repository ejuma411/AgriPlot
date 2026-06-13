from django.contrib import admin
from .models import Transaction, TransactionMilestone, TransactionDocument

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "plot", "buyer", "seller", "stage", "created_at")
    list_filter = ("stage",)
    search_fields = ("plot__title", "buyer__username", "seller__username")
    readonly_fields = ("created_at", "updated_at")

@admin.register(TransactionMilestone)
class TransactionMilestoneAdmin(admin.ModelAdmin):
    list_display = ("transaction", "milestone_type", "achieved_by", "achieved_at")
    list_filter = ("milestone_type",)

@admin.register(TransactionDocument)
class TransactionDocumentAdmin(admin.ModelAdmin):
    list_display = ("transaction", "document_type", "status", "uploaded_at")
    list_filter = ("document_type", "status")

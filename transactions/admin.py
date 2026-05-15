from django.contrib import admin
from .models import Transaction, TransactionMilestone, TransactionDocument

class TransactionMilestoneInline(admin.TabularInline):
    model = TransactionMilestone
    extra = 1

class TransactionDocumentInline(admin.TabularInline):
    model = TransactionDocument
    extra = 1

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "plot", "buyer", "seller", "stage", "is_completed", "created_at")
    list_filter = ("stage", "is_completed", "buyer_type")
    search_fields = ("plot__title", "buyer__username", "seller__username", "buyer_id_number")
    inlines = [TransactionMilestoneInline, TransactionDocumentInline]
    fieldsets = (
        ("Parties", {
            "fields": (("seller", "buyer"), ("buyer_type", "buyer_id_number", "buyer_kra_pin"), "buyer_address")
        }),
        ("Transaction Details", {
            "fields": (("plot", "stage"), ("agreed_price", "deposit_paid", "balance_due"), "is_completed")
        }),
        ("Legal Representatives", {
            "fields": (("seller_advocate", "buyer_advocate"),)
        }),
    )

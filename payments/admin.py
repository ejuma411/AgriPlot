from django.contrib import admin
from .models import (
    Wallet,
    WalletTransaction,
    WalletDepositRequest,
    WalletWithdrawalRequest,
    PaymentRequest,
)

@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ("internal_reference", "amount", "status", "created_at")
    list_filter = ("status", "method", "category")
    search_fields = ("internal_reference", "title")
    raw_id_fields = ("buyer", "seller", "plot")



@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("account_number", "balance", "is_active", "created_at")
    search_fields = ("account_number", "user__username")
    raw_id_fields = ("user",)

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount", "type", "status", "created_at")
    list_filter = ("type", "status", "channel")
    search_fields = ("reference", "wallet__account_number")

@admin.register(WalletDepositRequest)
class WalletDepositRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "user__username")

@admin.register(WalletWithdrawalRequest)
class WalletWithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "user__username")










from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from .models import Transaction

class TransactionDashboardView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = "transactions/dashboard.html"
    context_object_name = "transactions"

    def get_queryset(self):
        # Users see transactions where they are either buyer or seller
        return Transaction.objects.filter(
            Q(buyer=self.request.user) | Q(seller=self.request.user)
        ).select_related("plot", "buyer", "seller")

class TransactionDetailView(LoginRequiredMixin, DetailView):
    model = Transaction
    template_name = "transactions/detail.html"
    context_object_name = "transaction"

    def get_queryset(self):
        return Transaction.objects.filter(
            Q(buyer=self.request.user) | Q(seller=self.request.user)
        ).select_related("plot", "buyer", "seller").prefetch_related("milestones", "documents")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add stage progress percentage for the UI
        stages = list(Transaction.Stage)
        current_index = 0
        for i, stage in enumerate(stages):
            if stage[0] == self.object.stage:
                current_index = i
                break
        context["progress_percentage"] = int(((current_index + 1) / len(stages)) * 100)
        return context

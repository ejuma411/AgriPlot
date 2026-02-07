from formtools.wizard.views import SessionWizardView
from django.shortcuts import redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from listings.models import Plot, PlotImage, Broker
from listings.forms.plot_wizard_forms import (
    PlotStep1Form,
    PlotStep2Form,
    PlotStep3Form,
    PlotStep4Form
)


class PlotCreateWizard(LoginRequiredMixin, SessionWizardView):

    form_list = [
        ("basic", PlotStep1Form),
        ("soil", PlotStep2Form),
        ("documents", PlotStep3Form),
        ("images", PlotStep4Form),
    ]

    template_name = "listings/plot_wizard.html"

    # ✅ Ensure only Brokers can create plots
    def dispatch(self, request, *args, **kwargs):
        if not hasattr(request.user, "broker"):
            return redirect("upgrade_to_broker")
        return super().dispatch(request, *args, **kwargs)

    # ✅ Final save logic
    def done(self, form_list, **kwargs):

        broker = self.request.user.broker

        plot = Plot(broker=broker)

        # Merge cleaned data from all steps
        for form in form_list:
            for field, value in form.cleaned_data.items():
                if hasattr(plot, field):
                    setattr(plot, field, value)

        plot.save()

        # Handle images step
        images_data = self.get_cleaned_data_for_step("images_list")

        if images_data:
            images = images_data.get("images_list", [])
            for img in images:
                PlotImage.objects.create(plot=plot, image=img)

        return redirect("dashboard")

# listings/views_test.py

from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from .models import Plot
from .services.ardhisasa_integration import ArdhisasaService

@staff_member_required
def test_ardhisasa(request, plot_id):
    """Test endpoint for Ardhisasa API"""
    plot = get_object_or_404(Plot, id=plot_id)
    
    service = ArdhisasaService(use_mock=True)
    result = service.verify_plot_title(plot)
    
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse(result)
    
    return render(request, 'test/ardhisasa_result.html', {
        'plot': plot,
        'result': result
    })

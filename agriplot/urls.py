"""
URL configuration for agriplot project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from authentication import views_auth
from listings.sitemaps import PlotSitemap, StaticViewSitemap


sitemaps = {
    "plots": PlotSitemap,
    "static": StaticViewSitemap,
}


urlpatterns = [
    path("admin/", admin.site.urls),
    path("payments/", include("payments.urls")),
    path("transactions/", include("transactions.urls")),
    path('', include('listings.urls')),
    path("", include("verification.urls")),
    path('reports/', include('reports.urls')),
    path('login/', views_auth.TwoFactorLoginView.as_view(), name='login'),
    path('', include('authentication.urls')),
    path('security/', include('security.urls')),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

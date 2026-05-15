from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Plot


class PlotSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Plot.objects.filter(is_hidden=False).exclude(market_status="sold")

    def lastmod(self, obj):
        return obj.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return [
            "listings:home",
            "listings:about_us",
            "listings:how_it_works",
            "listings:browse_plots",
            "listings:contact_us",
            "listings:faq",
            "listings:terms",
            "listings:privacy",
        ]

    def location(self, item):
        return reverse(item)

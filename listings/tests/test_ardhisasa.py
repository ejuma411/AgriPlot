# listings/management/commands/test_ardhisasa.py

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from listings.models import Plot
from listings.services.ardhisasa_integration import ArdhisasaService
from listings.services.mock_ardhisasa import TEST_TITLES
from unittest.mock import Mock, MagicMock

class Command(BaseCommand):
    help = 'Test Ardhisasa API integration with mock data'
    
    def add_arguments(self, parser):
        parser.add_argument('--plot-id', type=int, help='Test specific plot')
        parser.add_argument('--scenario', type=str, choices=['valid', 'invalid', 'encumbrance', 'mismatch'],
                          default='valid', help='Test scenario')
    
    def handle(self, *args, **options):
        self.stdout.write("🧪 Testing Ardhisasa API Integration")
        self.stdout.write("=" * 50)
        
        service = ArdhisasaService(use_mock=True)
        
        if options['plot_id']:
            # Test specific plot
            try:
                plot = Plot.objects.get(id=options['plot_id'])
                self.test_plot(service, plot)
            except Plot.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Plot with ID {options['plot_id']} not found"))
                self.stdout.write("\nAvailable plots:")
                for plot in Plot.objects.all()[:5]:
                    self.stdout.write(f"  - ID {plot.id}: {plot.title}")
        else:
            # Test with sample data
            self.test_scenarios(service, options['scenario'])
    
    def test_plot(self, service, plot):
        self.stdout.write(f"\n📋 Testing Plot: {plot.title} (ID: {plot.id})")
        result = service.verify_plot_title(plot)
        
        if result['success']:
            verification_data = result.get('verification_data', {})
            search_data = verification_data.get('search_result', {})
            self.stdout.write(self.style.SUCCESS("✅ Verification successful!"))
            self.stdout.write(f"   Title: {verification_data.get('title_number') or search_data.get('title_number')}")
            self.stdout.write(f"   Owner: {search_data.get('owner_name')}")
            self.stdout.write(f"   Reference: {search_data.get('search_reference')}")
        else:
            self.stdout.write(self.style.ERROR(f"❌ Verification failed: {result['error']}"))
    
    def test_scenarios(self, service, scenario):
        test_data = TEST_TITLES.get(scenario.upper(), TEST_TITLES['VALID'])
        
        self.stdout.write(f"\n📋 Testing Scenario: {scenario}")
        self.stdout.write(f"   {test_data['description']}")
        self.stdout.write(f"   Title: {test_data['title_number']}")
        
        # Create a proper mock plot that behaves like a Django model
        plot = self.create_mock_plot(test_data)
        
        # Override the title number extraction
        service._extract_title_number = lambda p: test_data['title_number']
        
        result = service.verify_plot_title(plot)
        
        if result['success']:
            verification_data = result.get('verification_data', {})
            search_data = verification_data.get('search_result', {})
            self.stdout.write(self.style.SUCCESS("✅ Verification successful!"))
            self.stdout.write(f"   Search ref: {search_data.get('search_reference')}")
            self.stdout.write(f"   Owner: {search_data.get('owner_name')}")
        else:
            self.stdout.write(self.style.WARNING(f"⚠️ Verification failed: {result['error']}"))
            self.stdout.write(f"   Expected: {test_data['expected']}")
    
    def create_mock_plot(self, test_data):
        """Create a mock plot that has the required Django model attributes"""
        
        # Create a mock class that looks like a Django model
        class MockPlot:
            class Meta:
                app_label = 'listings'
                model_name = 'plot'
            
            class _meta:
                app_label = 'listings'
                model_name = 'plot'
                concrete_model = None
                
            def __init__(self):
                self.id = 9999
                self.title = f"Test Plot - {test_data.get('scenario', 'test')}"
                self.county = "Nairobi"
                self.subcounty = "Westlands"
                self.area = 5.0
                self.agent = self.create_mock_agent()
                self.landowner = None
                self._state = MagicMock()
                self._state.adding = False
                
            def create_mock_agent(self):
                agent = MagicMock()
                agent.id_number = "12345678"
                agent.user = MagicMock()
                agent.user.get_full_name.return_value = "John Mwangi"
                agent.user.username = "john_mwangi"
                return agent
        
        return MockPlot()

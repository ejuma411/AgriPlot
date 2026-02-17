# listings/management/commands/create_test_plots.py
import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from listings.models import Plot, Agent, VerificationStatus
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

class Command(BaseCommand):
    help = 'Create test plots for development with proper validation'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=5, help='Number of test plots to create')
        parser.add_argument('--agent', type=str, default='juma', help='Username of the agent')

    def handle(self, *args, **options):
        count = options['count']
        agent_username = options['agent']
        
        # Get agent
        try:
            user = User.objects.get(username=agent_username)
            agent = Agent.objects.get(user=user)
            self.stdout.write(self.style.SUCCESS(f"✅ Found agent: {agent_username}"))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ User '{agent_username}' does not exist."))
            self.stdout.write(self.style.WARNING("Create a user with: python manage.py createsuperuser"))
            return
        except Agent.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Agent profile for '{agent_username}' does not exist."))
            return

        # Test data
        titles = [
            "5-Acre Fertile Farm in Kitale",
            "3-Acre Organic Land in Eldoret",
            "2-Acre Hillside Plot in Nakuru",
            "4-Acre Irrigated Farm in Narok",
            "6-Acre Mixed-Crop Land in Thika",
            "8-Area Coffee Plantation in Kiambu",
            "1.5-Acre Vegetable Farm in Machakos",
            "10-Acre Wheat Farm in Uasin Gishu"
        ]
        
        locations = [
            "Kitale, Trans-Nzoia County",
            "Eldoret, Uasin Gishu County",
            "Nakuru, Nakuru County",
            "Narok, Narok County",
            "Thika, Kiambu County",
            "Kiambu, Kiambu County",
            "Machakos, Machakos County",
            "Eldoret, Uasin Gishu County"
        ]
        
        soil_types = ['Loam', 'Clay', 'Sandy', 'Silty', 'Peaty', 'Sandy Loam', 'Clay Loam']
        crops = [
            'Maize, Beans, Vegetables',
            'Wheat, Barley, Oats',
            'Tomatoes, Onions, Cabbage',
            'Sugarcane, Maize',
            'Coffee, Tea, Bananas',
            'Dairy Farming, Fodder',
            'Mixed Farming',
            'Wheat, Sunflower'
        ]
        
        land_types = ['agricultural', 'mixed_use', 'commercial']
        water_sources = ['borehole', 'river', 'rain', 'irrigation', None]

        created_count = 0
        for i in range(min(count, len(titles))):
            try:
                # Generate base price
                base_price = random.randint(2_000_000, 15_000_000)
                area = round(random.uniform(2.0, 10.0), 1)
                
                # Randomly select listing type
                listing_type = random.choice(['sale', 'lease', 'both'])
                
                # Prepare plot data
                plot_data = {
                    'title': titles[i % len(titles)],
                    'location': locations[i % len(locations)],
                    'area': area,
                    'soil_type': random.choice(soil_types),
                    'ph_level': round(random.uniform(5.0, 7.5), 1),
                    'crop_suitability': crops[i % len(crops)],
                    'agent': agent,
                    'listing_type': listing_type,
                    'land_type': random.choice(land_types),
                    'land_use_description': f"Currently used for {random.choice(['farming', 'grazing', 'mixed use'])}",
                    
                    # Infrastructure
                    'has_water': random.choice([True, False]),
                    'water_source': random.choice(water_sources) if random.choice([True, False]) else None,
                    'has_electricity': random.choice([True, False]),
                    'electricity_meter': random.choice([True, False]),
                    'has_road_access': True,
                    'road_type': random.choice(['tarmac', 'murram', 'earth']),
                    'road_distance_km': round(random.uniform(0.1, 5.0), 1),
                    'has_buildings': random.choice([True, False]),
                    'fencing': random.choice(['full', 'partial', 'none', 'live']),
                }
                
                # Add pricing based on listing type
                if listing_type in ['sale', 'both']:
                    plot_data['sale_price'] = base_price
                    plot_data['price'] = base_price
                    plot_data['price_per_acre'] = base_price / area
                
                if listing_type in ['lease', 'both']:
                    # For lease, add lease prices
                    monthly = base_price // 100  # Approximate monthly rate
                    plot_data['lease_price_monthly'] = monthly
                    plot_data['lease_price_yearly'] = monthly * 10  # 10 months rate
                    plot_data['lease_duration'] = random.choice(['monthly', '1year', '3years', '5years'])
                    plot_data['lease_terms'] = f"Lease terms: {random.choice(['Flexible', 'Strict', 'Negotiable'])}"
                    
                    # For sale+lease, also need sale price
                    if listing_type == 'both':
                        plot_data['sale_price'] = base_price
                        plot_data['price'] = base_price
                
                # Create plot
                plot = Plot(**plot_data)
                plot.save()  # This will trigger validation
                
                # Create verification status
                content_type = ContentType.objects.get_for_model(Plot)
                VerificationStatus.objects.get_or_create(
                    content_type=content_type,
                    object_id=plot.id,
                    defaults={
                        'current_stage': random.choice(['pending', 'admin_review', 'approved']),
                        'document_uploaded_at': timezone.now()
                    }
                )
                
                created_count += 1
                self.stdout.write(f"  ✅ Created plot {i+1}: {plot.title[:30]}... ({plot.get_listing_type_display()})")
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ❌ Error creating plot {i+1}: {str(e)}"))
                continue

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Successfully created {created_count} test plots!"))
# listings/tests/conftest.py
import pytest
from django.contrib.auth.models import User
from listings.models import Agent, Plot, LandownerProfile

@pytest.fixture
def test_user(db):
    """Create a test user"""
    return User.objects.create_user(
        username='testuser',
        password='testpass123',
        email='test@example.com'
    )

@pytest.fixture
def test_agent(db, test_user):
    """Create a test agent"""
    return Agent.objects.create(
        user=test_user,
        phone='+254700000000',
        id_number='12345678',
        license_number='LIC123'
    )

@pytest.fixture
def test_landowner(db, test_user):
    """Create a test landowner"""
    return LandownerProfile.objects.create(
        user=test_user,
        national_id='national_id.pdf',
        kra_pin='kra_pin.pdf',
        verified=False
    )

@pytest.fixture
def test_plot(db, test_agent):
    """Create a test plot"""
    return Plot.objects.create(
        title='Test Plot',
        location='Nairobi',
        county='Nairobi',
        subcounty='Westlands',
        area=5.0,
        listing_type='sale',
        land_type='agricultural',
        soil_type='Loam',
        crop_suitability='Maize',
        price=5000000,
        agent=test_agent
    )
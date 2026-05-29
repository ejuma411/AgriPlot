"""
Security Middleware for AgriPlot
Handles 2FA enforcement, audit logging, and security headers
"""

from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
import re
import logging

logger = logging.getLogger(__name__)


class AuditLogMiddleware(MiddlewareMixin):
    """
    Automatically log all significant requests for non-repudiation.
    This middleware captures every request and creates an audit log entry.
    """
    
    # Skip logging for these path patterns
    SKIP_PATHS = [
        r'^/static/',
        r'^/media/',
        r'^/admin/jsi18n/',
        r'^/health/',
        r'^/favicon\.ico$',
        r'^/robots\.txt$',
    ]
    
    # Skip for these HTTP methods
    SKIP_METHODS = ['OPTIONS', 'HEAD']

    def process_request(self, request):
        """Store request data for later logging"""
        request._audit_start_time = timezone.now()
        request._audit_body = None
        
        # Capture request body for POST/PUT/PATCH requests
        if request.method in ['POST', 'PUT', 'PATCH'] and request.body:
            # Limit body size to 10KB to avoid memory issues
            if len(request.body) < 10240:
                try:
                    request._audit_body = request.body
                except Exception as e:
                    logger.error(f"Failed to capture request body: {e}")
        
        return None

    def process_response(self, request, response):
        """Log the request after response is generated"""
        
        # Skip logging for certain paths
        current_path = request.path_info
        for skip_path in self.SKIP_PATHS:
            if re.match(skip_path, current_path):
                return response
        
        # Skip for certain methods
        if request.method in self.SKIP_METHODS:
            return response
        
        # Log all authenticated requests and important unauthenticated ones
        is_important_path = any(p in current_path for p in ['login', 'register', 'password', 'payment', 'plot', 'contract'])
        
        if not request.user.is_authenticated and not is_important_path:
            return response
        
        # Determine action
        action = self._determine_action(request, response)
        if not action:
            # Default action based on method
            if request.method == 'GET':
                action = 'view'
            elif request.method == 'POST':
                action = 'create'
            elif request.method in ['PUT', 'PATCH']:
                action = 'update'
            elif request.method == 'DELETE':
                action = 'delete'
            else:
                action = 'access'
        
        # Extract object information from URL
        object_type, object_id = self._extract_object_info(request)
        
        # Create audit log
        try:
            from .models import AuditLog
            
            # Get client IP
            ip_address = self._get_client_ip(request)
            
            # Determine severity
            if response.status_code >= 500:
                severity = 'critical'
            elif response.status_code >= 400:
                severity = 'warning'
            else:
                severity = 'info'
            
            # Create log entry
            log = AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action=action,
                severity=severity,
                object_type=object_type,
                object_id=object_id,
                ip_address=ip_address,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                request_path=request.path[:500],
                request_method=request.method,
                extra={
                    'status_code': response.status_code,
                    'method': request.method,
                    'response_size': len(response.content) if hasattr(response, 'content') else 0,
                }
            )
            
            logger.info(f"Audit log created: {action} by {request.user} at {log.created_at}")
            
        except Exception as e:
            # Don't let logging errors break the application
            logger.error(f"Audit log error: {e}")
        
        return response
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def _determine_action(self, request, response):
        """Determine the audit action based on request and response"""
        path = request.path_info
        method = request.method
        
        # Authentication actions
        if path == '/login/' and response.status_code == 302:
            return 'login'
        elif path == '/logout/':
            return 'logout'
        elif 'login' in path and response.status_code == 401:
            return 'failed_login'
        
        # Plot-related actions
        if '/plot/' in path or '/plots/' in path:
            if method == 'POST':
                return 'create_plot'
            elif method in ['PUT', 'PATCH']:
                return 'edit_plot'
            elif method == 'DELETE':
                return 'delete_plot'
        
        # Payment-related actions
        if '/payment/' in path or '/payments/' in path:
            if method == 'POST' and response.status_code in [200, 201, 302]:
                return 'payment_initiated'
            elif method in ['PUT', 'PATCH'] and response.status_code == 200:
                return 'payment_completed'
        
        # Document actions
        if '/document/' in path or '/upload/' in path:
            if method == 'POST':
                return 'document_upload'
            elif method == 'GET':
                return 'document_view'
        
        # Export actions
        if 'export' in path or 'download' in path:
            return 'export_data'
        
        # Settings changes
        if '/settings/' in path or '/profile/' in path:
            if method in ['POST', 'PUT', 'PATCH']:
                return 'settings_change'
        
        # Admin actions
        if '/admin/' in path:
            return 'admin_action'
        
        # Verification actions
        if '/verify/' in path:
            if 'approve' in path:
                return 'verification_approved'
            elif 'reject' in path:
                return 'verification_rejected'
            return 'verification_request'
        
        # Registration
        if '/register/' in path and method == 'POST':
            return 'user_registration'
        
        return None
    
    def _extract_object_info(self, request):
        """Extract object type and ID from URL"""
        path = request.path_info
        object_type = None
        object_id = None
        
        # Extract plot ID
        plot_match = re.search(r'/plots?/(\d+)', path)
        if plot_match:
            object_type = 'Plot'
            object_id = int(plot_match.group(1))
            return object_type, object_id
        
        # Extract payment ID
        payment_match = re.search(r'/payments?/(\d+)', path)
        if payment_match:
            object_type = 'Payment'
            object_id = int(payment_match.group(1))
            return object_type, object_id
        
        # Extract user ID
        user_match = re.search(r'/users?/(\d+)', path)
        if user_match:
            object_type = 'User'
            object_id = int(user_match.group(1))
            return object_type, object_id
        
        # Extract contract ID
        contract_match = re.search(r'/contracts?/(\d+)', path)
        if contract_match:
            object_type = 'Contract'
            object_id = int(contract_match.group(1))
            return object_type, object_id
        
        return object_type, object_id


class EnforceTwoFactorEnrollmentMiddleware(MiddlewareMixin):
    """Redirect authenticated users to 2FA setup if required but not enabled."""
    
    ALLOWED_PATHS = [
        '/logout/',
        '/static/',
        '/media/',
        '/admin/',
        '/two-factor/setup/',
        '/two-factor/verify/',
    ]
    
    ALLOWED_URL_NAMES = [
        'two_factor_setup',
        'two_factor_verify',
        'logout',
        'home',
    ]

    def process_request(self, request):
        user = request.user
        
        require_2fa = getattr(settings, "REQUIRE_2FA", True)
        require_enrollment = getattr(settings, "REQUIRE_2FA_ENROLLMENT", True)
        
        if user.is_authenticated and require_2fa and require_enrollment:
            current_path = request.path_info
            
            for allowed_path in self.ALLOWED_PATHS:
                if current_path.startswith(allowed_path):
                    return None
            
            if hasattr(request, 'resolver_match') and request.resolver_match:
                url_name = request.resolver_match.url_name
                if url_name in self.ALLOWED_URL_NAMES:
                    return None
            
            try:
                from accounts.models import Profile
                profile = getattr(user, 'profile', None)
                if profile is None:
                    profile, created = Profile.objects.get_or_create(user=user)
                
                if profile and not profile.has_2fa_enabled:
                    return redirect(reverse('authentication:two_factor_setup'))
            except Exception as e:
                logger.error(f"2FA enrollment error: {e}")
        
        return None


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add security headers to all responses"""
    
    def process_response(self, request, response):
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

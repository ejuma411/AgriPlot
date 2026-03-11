from datetime import timedelta
import json
import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from listings.models import Plot
from verification.models import (
    ExtensionOfficer,
    ExtensionReport,
    VerificationLog,
    VerificationStatus,
    VerificationTask,
)

logger = logging.getLogger(__name__)

class AnalyticsService:
    """Service for generating reports and analytics"""
    
    @staticmethod
    def get_verification_overview(days=30):
        """Get overview of verification activity"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get content type for Plot
        plot_content_type = ContentType.objects.get_for_model(Plot)
        
        # Plots submitted
        plots_submitted = Plot.objects.filter(
            created_at__range=[start_date, end_date]
        ).count()
        
        # Plots verified - query VerificationStatus directly
        plots_verified = VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='approved',
            approved_at__range=[start_date, end_date]
        ).count()
        
        # Average verification time
        verified_statuses = VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='approved',
            approved_at__range=[start_date, end_date]
        ).select_related('content_type')
        
        total_time = timedelta()
        count = 0
        for status in verified_statuses:
            try:
                plot = status.content_object
                if plot and status.approved_at:
                    time_taken = status.approved_at - plot.created_at
                    total_time += time_taken
                    count += 1
            except:
                continue
        
        avg_time = total_time / count if count > 0 else timedelta()
        
        return {
            'plots_submitted': plots_submitted,
            'plots_verified': plots_verified,
            'verification_rate': round((plots_verified / plots_submitted * 100), 2) if plots_submitted > 0 else 0,
            'avg_verification_days': round(avg_time.total_seconds() / 86400, 1) if count > 0 else 0,
            'period_days': days
        }
    
    @staticmethod
    def get_officer_performance(days=30):
        """Get performance metrics for extension officers"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        officers = ExtensionOfficer.objects.filter(is_active=True)
        performance_data = []
        
        for officer in officers:
            # Tasks completed in period
            tasks_completed = VerificationTask.objects.filter(
                assigned_to=officer.user,
                status='completed',
                completed_at__range=[start_date, end_date],
                verification_type='extension_review'
            ).count()
            
            # Get reports submitted
            reports = ExtensionReport.objects.filter(
                officer=officer,
                submitted_at__range=[start_date, end_date]
            )
            
            # Calculate average rating based on overall_suitability
            rating_map = {
                'highly_suitable': 5,
                'moderately_suitable': 4,
                'marginally_suitable': 3,
                'not_suitable': 1
            }
            
            total_rating = 0
            rating_count = 0
            for report in reports:
                if report.overall_suitability in rating_map:
                    total_rating += rating_map[report.overall_suitability]
                    rating_count += 1
            
            avg_rating = round(total_rating / rating_count, 2) if rating_count > 0 else 0
            
            # Response time
            tasks = VerificationTask.objects.filter(
                assigned_to=officer.user,
                status='completed',
                completed_at__range=[start_date, end_date]
            )
            
            total_response = timedelta()
            response_count = 0
            for task in tasks:
                if task.assigned_at and task.completed_at:
                    response_time = task.completed_at - task.assigned_at
                    total_response += response_time
                    response_count += 1
            
            avg_response = total_response / response_count if response_count > 0 else timedelta()
            
            performance_data.append({
                'officer': officer,
                'tasks_completed': tasks_completed,
                'avg_rating': avg_rating,
                'avg_response_hours': round(avg_response.total_seconds() / 3600, 1) if response_count > 0 else 0,
                'utilization': round((tasks_completed / (officer.max_daily_tasks * days)) * 100, 1) if days > 0 and officer.max_daily_tasks > 0 else 0
            })
        
        return sorted(performance_data, key=lambda x: x['tasks_completed'], reverse=True)
    
    @staticmethod
    def get_verification_timeline(days=30):
        """Get daily verification counts for timeline chart"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        plot_content_type = ContentType.objects.get_for_model(Plot)
        
        timeline = []
        current_date = start_date
        
        while current_date <= end_date:
            next_date = current_date + timedelta(days=1)
            
            submitted = Plot.objects.filter(
                created_at__range=[current_date, next_date]
            ).count()
            
            verified = VerificationStatus.objects.filter(
                content_type=plot_content_type,
                current_stage='approved',
                approved_at__range=[current_date, next_date]
            ).count()
            
            timeline.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'submitted': submitted,
                'verified': verified
            })
            
            current_date = next_date
        
        return timeline
    
    @staticmethod
    def get_task_breakdown():
        """Get breakdown of tasks by type and status"""
        task_types = ['document_review', 'extension_review', 'surveyor_inspection']
        breakdown = {}
        
        for task_type in task_types:
            breakdown[task_type] = {
                'pending': VerificationTask.objects.filter(
                    verification_type=task_type,
                    status='pending'
                ).count(),
                'in_progress': VerificationTask.objects.filter(
                    verification_type=task_type,
                    status='in_progress'
                ).count(),
                'completed': VerificationTask.objects.filter(
                    verification_type=task_type,
                    status='completed'
                ).count(),
            }
        
        return breakdown
    
    @staticmethod
    def get_county_statistics():
        """Get verification statistics by county - SQLite compatible version"""
        # Get all counties that have plots
        counties = Plot.objects.exclude(county__isnull=True).exclude(county='').values_list('county', flat=True).distinct()
        plot_content_type = ContentType.objects.get_for_model(Plot)
        stats = []
        
        for county_name in counties:
            plots = Plot.objects.filter(county=county_name)
            total = plots.count()
            
            if total == 0:
                continue
                
            # Get plot IDs for this county
            plot_ids = plots.values_list('id', flat=True)
            
            verified = VerificationStatus.objects.filter(
                content_type=plot_content_type,
                object_id__in=plot_ids,
                current_stage='approved'
            ).count()
            
            # SQLite-compatible way to check county assignment
            # We need to do this in Python since SQLite doesn't support JSON contains
            officers = []
            all_officers = ExtensionOfficer.objects.filter(is_active=True)
            for officer in all_officers:
                if county_name in officer.assigned_counties:
                    officers.append(officer)
            
            stats.append({
                'county': county_name,
                'total_plots': total,
                'verified_plots': verified,
                'verification_rate': round((verified / total * 100), 2) if total > 0 else 0,
                'assigned_officers': len(officers)
            })
        
        return sorted(stats, key=lambda x: x['total_plots'], reverse=True)
    
    @staticmethod
    def get_system_health():
        """Get system health metrics"""
        now = timezone.now()
        plot_content_type = ContentType.objects.get_for_model(Plot)
        
        # Overdue tasks (> 3 days)
        overdue_tasks = VerificationTask.objects.filter(
            status='in_progress',
            assigned_at__lt=now - timedelta(days=3)
        ).count()
        
        # Unassigned tasks
        unassigned_tasks = VerificationTask.objects.filter(
            status='pending'
        ).count()
        
        # Plots waiting > 5 days
        stalled_plots = VerificationStatus.objects.filter(
            content_type=plot_content_type,
            current_stage='document_uploaded',
            created_at__lt=now - timedelta(days=5)
        ).count()
        
        # Calculate health score (0-100)
        health_score = 100
        health_score -= min(overdue_tasks * 5, 30)  # Max 30 points deduction
        health_score -= min(unassigned_tasks * 2, 20)  # Max 20 points deduction
        health_score -= min(stalled_plots * 3, 25)  # Max 25 points deduction
        health_score = max(0, health_score)  # Ensure not negative
        
        return {
            'overdue_tasks': overdue_tasks,
            'unassigned_tasks': unassigned_tasks,
            'stalled_plots': stalled_plots,
            'health_score': health_score
        }

    @staticmethod
    def get_sla_metrics():
        """Get SLA metrics for confirmation and submission deadlines."""
        now = timezone.now()

        confirm_overdue_qs = VerificationTask.objects.filter(
            confirmation_status='pending',
            confirm_by__lt=now,
            assigned_to__isnull=False,
            status='in_progress'
        ).select_related('plot', 'assigned_to')

        deadline_overdue_qs = VerificationTask.objects.filter(
            status='in_progress',
            deadline_at__lt=now
        ).select_related('plot', 'assigned_to')

        due_soon_qs = VerificationTask.objects.filter(
            status='in_progress',
            deadline_at__gte=now,
            deadline_at__lte=now + timedelta(hours=24)
        ).select_related('plot', 'assigned_to')

        return {
            'confirm_overdue_count': confirm_overdue_qs.count(),
            'deadline_overdue_count': deadline_overdue_qs.count(),
            'due_soon_count': due_soon_qs.count(),
            'confirm_overdue_tasks': confirm_overdue_qs.order_by('confirm_by')[:10],
            'deadline_overdue_tasks': deadline_overdue_qs.order_by('deadline_at')[:10],
            'due_soon_tasks': due_soon_qs.order_by('deadline_at')[:10],
        }

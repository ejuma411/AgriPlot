import os
from django.conf import settings
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.utils import timezone
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
from io import BytesIO
import tempfile

class WeasyPDFGenerator:
    """PDF generator using WeasyPrint with full CSS support"""
    
    def __init__(self, template_name, context=None, filename=None):
        self.template_name = template_name
        self.context = context or {}
        self.filename = filename or f"report_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        self.font_config = FontConfiguration()
        
    def generate_pdf(self):
        """Generate PDF from HTML template"""
        # Render HTML template
        html_string = render_to_string(self.template_name, self.context)
        
        # Create PDF
        pdf_file = BytesIO()
        
        # Custom CSS for reports
        css_string = """
        @page {
            size: A4;
            margin: 2cm;
            @top-center {
                content: element(header);
            }
            @bottom-center {
                content: element(footer);
            }
        }
        
        .report-header {
            position: running(header);
            margin-bottom: 20px;
        }
        
        .report-footer {
            position: running(footer);
            font-size: 9pt;
            text-align: center;
            color: #666;
            margin-top: 20px;
        }
        
        body {
            font-family: 'Helvetica', 'Arial', sans-serif;
            font-size: 10pt;
            line-height: 1.4;
            color: #333;
        }
        
        h1 {
            color: #2E7D32;
            font-size: 24pt;
            margin-bottom: 20px;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        
        h2 {
            color: #4CAF50;
            font-size: 16pt;
            margin-top: 20px;
            margin-bottom: 10px;
        }
        
        h3 {
            color: #666;
            font-size: 14pt;
            margin-top: 15px;
            margin-bottom: 8px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }
        
        th {
            background-color: #2E7D32;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: bold;
        }
        
        td {
            border: 1px solid #ddd;
            padding: 8px;
            vertical-align: top;
        }
        
        tr:nth-child(even) {
            background-color: #f5f5f5;
        }
        
        .status-completed {
            color: #4CAF50;
            font-weight: bold;
        }
        
        .status-pending {
            color: #FF9800;
            font-weight: bold;
        }
        
        .status-failed {
            color: #f44336;
            font-weight: bold;
        }
        
        .progress-bar {
            background-color: #e0e0e0;
            border-radius: 5px;
            overflow: hidden;
            margin: 10px 0;
        }
        
        .progress-fill {
            background-color: #4CAF50;
            height: 20px;
            text-align: center;
            color: white;
            line-height: 20px;
        }
        
        .signature-line {
            margin-top: 50px;
            border-top: 1px solid #333;
            width: 300px;
            padding-top: 10px;
        }
        
        .watermark {
            position: fixed;
            opacity: 0.1;
            font-size: 60pt;
            transform: rotate(-45deg);
            z-index: -1;
        }
        """
        
        HTML(string=html_string).write_pdf(
            pdf_file,
            stylesheets=[CSS(string=css_string)],
            font_config=self.font_config,
            presentational_hints=True
        )
        
        pdf_file.seek(0)
        
        # Create response
        response = HttpResponse(pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{self.filename}.pdf"'
        response['Content-Length'] = pdf_file.tell()
        
        return response
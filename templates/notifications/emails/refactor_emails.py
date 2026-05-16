import os
import re

email_dir = "/home/createch/Documents/PROJECT/agriplot/templates/notifications/emails/"

for filename in os.listdir(email_dir):
    if not filename.endswith('.html') or filename == 'base_email.html':
        continue
        
    filepath = os.path.join(email_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
        
    # Check if already refactored
    if "{% extends" in content:
        continue
        
    # Find loads like {% load humanize %}
    loads = "\n".join(re.findall(r'{%\s*load.*?%}', content))
    
    # Try to extract the content inside <div class="content"> ... </div>
    # Using regex to find the content
    match = re.search(r'<div class="content">(.*?)</div>\s*<div class="footer">', content, re.DOTALL)
    
    if match:
        inner_content = match.group(1).strip()
        
        # Build the new file content
        new_content = ""
        if loads:
            new_content += loads + "\n"
        new_content += "{% extends 'notifications/emails/base_email.html' %}\n\n{% block content %}\n"
        new_content += inner_content + "\n"
        new_content += "{% endblock %}\n"
        
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Refactored: {filename}")
    else:
        print(f"Skipped (no match): {filename}")


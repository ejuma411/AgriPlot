import os
import re

email_dir = "/home/createch/Documents/PROJECT/agriplot/templates/notifications/emails/"

for filename in ['support_ticket_admin.html', 'support_ticket_received.html', 'account_verified.html', 'role_approved.html', 'registration_received.html']:
    filepath = os.path.join(email_dir, filename)
    with open(filepath, 'r') as f:
        content = f.read()
        
    loads = "\n".join(re.findall(r'{%\s*load.*?%}', content))
    
    # Try to extract the content inside <div class="content"> ... </div>
    match = re.search(r'<div class="content">(.*?)</div>\s*</body>', content, re.DOTALL)
    if not match:
        # Fallback just in case
        match = re.search(r'<div class="content">(.*?)</div>', content, re.DOTALL)
        
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


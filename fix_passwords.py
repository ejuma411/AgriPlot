import os
import re

tpl_dir = "/home/createch/Documents/PROJECT/agriplot/templates/accounts/"

replacement = """            {% if 'password' in field.name|lower %}
            <div class="password-wrap">
                {{ field }}
                <button type="button" class="password-toggle" onclick="togglePassword('{{ field.auto_id }}', this)">Show</button>
            </div>
            {% else %}
                {{ field }}
            {% endif %}"""

for filename in os.listdir(tpl_dir):
    if filename.startswith('register_') and filename.endswith('.html'):
        filepath = os.path.join(tpl_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
        
        # We only replace the standalone {{ field }} that is just before <small class="text-error">{{ field.errors }}</small>
        # Let's use regex
        new_content = re.sub(r'(\s*)\{\{\s*field\s*\}\}(\s*<small class="text-error">\{\{ field\.errors \}\}</small>)', r'\1' + replacement.lstrip() + r'\2', content)
        
        if content != new_content:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"Updated {filename}")
        else:
            print(f"Skipped {filename} (no match or already updated)")

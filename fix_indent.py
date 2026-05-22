import re

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(1, len(lines)):
    if 'log_action(' in lines[i] and 'def log_action' not in lines[i]:
        # get indent of previous line
        prev_line = lines[i-1]
        indent = len(prev_line) - len(prev_line.lstrip())
        current_indent = len(lines[i]) - len(lines[i].lstrip())
        if indent != current_indent and 'db.session.commit()' in prev_line:
            lines[i] = (' ' * indent) + lines[i].lstrip()

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

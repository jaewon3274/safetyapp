import os

file_path = 'templates/index.html'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_str = "(data.employees || []).filter(e => e.status !== 'deleted').forEach(e => {"
new_str = "(data.employees || []).filter(e => e.status === 'active').forEach(e => {"

if old_str in content:
    content = content.replace(old_str, new_str)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Success")
else:
    print("String not found")

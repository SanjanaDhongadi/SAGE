import base64, os, sys

SAGE = '/home/SLA_Project/sage'

files = {}

# We'll populate this from stdin
import json
data = json.load(sys.stdin)
for path, content in data.items():
    full = os.path.join(SAGE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(base64.b64decode(content).decode())
    print(f'wrote {path}')
print('All files deployed.')
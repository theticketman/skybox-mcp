import json

path = r'C:\Users\rafae\.claude.json'
with open(path, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Use full explicit Python path so Claude Code can't pick the wrong one
config['projects']['C:/Users/rafae']['mcpServers']['skybox']['command'] = r'C:\Python314\python.exe'

with open(path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print('Updated to use C:\\Python314\\python.exe')
print(json.dumps(config['projects']['C:/Users/rafae']['mcpServers']['skybox'], indent=2))

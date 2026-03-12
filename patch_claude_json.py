import json
import os
from dotenv import load_dotenv

# Load tokens from .env
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app_token = os.environ['SKYBOX_APPLICATION_TOKEN']
api_token = os.environ['SKYBOX_API_TOKEN']
account_id = os.environ['SKYBOX_ACCOUNT_ID']

path = r'C:\Users\rafae\.claude.json'
with open(path, 'r', encoding='utf-8') as f:
    config = json.load(f)

project_key = 'C:/Users/rafae'
config['projects'][project_key]['mcpServers']['skybox'] = {
    'type': 'stdio',
    'command': r'C:\Python314\python.exe',
    'args': ['-m', 'skybox_mcp.server', 'stdio'],
    'cwd': r'C:\Users\rafae\OneDrive\Claude\skybox-mcp',
    'env': {
        'SKYBOX_APPLICATION_TOKEN': app_token,
        'SKYBOX_API_TOKEN': api_token,
        'SKYBOX_ACCOUNT_ID': account_id
    }
}

with open(path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print('Done - skybox MCP added to .claude.json (tokens loaded from .env)')

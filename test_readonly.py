import asyncio, os, sys
sys.path.insert(0, r'C:\Users\rafae\OneDrive\Claude\skybox-mcp')

# Test 1: read-only mode should block writes
os.environ['SKYBOX_READ_ONLY'] = 'true'
from skybox_mcp.server import _check_read_only

print('--- Test 1: READ-ONLY=true ---')
try:
    _check_read_only('PUT')
    print('FAIL - should have raised PermissionError')
except PermissionError as e:
    print(f'PASS - blocked with: {e}')

# Test 2: read-only=false should allow writes
os.environ['SKYBOX_READ_ONLY'] = 'false'
print()
print('--- Test 2: READ-ONLY=false ---')
try:
    _check_read_only('PUT')
    print('PASS - write allowed')
except PermissionError as e:
    print(f'FAIL - should not have blocked: {e}')

# Test 3: env var absent should allow writes
del os.environ['SKYBOX_READ_ONLY']
print()
print('--- Test 3: READ-ONLY not set ---')
try:
    _check_read_only('DELETE')
    print('PASS - write allowed')
except PermissionError as e:
    print(f'FAIL - should not have blocked: {e}')

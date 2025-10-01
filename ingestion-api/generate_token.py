import sys
sys.path.insert(0, 'src')

from auth import create_access_token
import os

# Use the same secret that's in Secret Manager
token = create_access_token('test-user@example.com', expires_delta=3600)
print(token)

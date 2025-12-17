# GitHub App Authentication Module

This module provides reusable GitHub App authentication functionality for all scripts in the GHAS Inventory project.

## Features

- **JWT Token Generation**: Automatic generation of JWT tokens for GitHub App authentication
- **Installation Management**: Handles GitHub App installation IDs for organizations
- **Token Lifecycle**: Automatic access token generation, refresh, and expiry handling
- **Session Management**: Pre-configured requests sessions with proper authentication headers
- **Error Handling**: Comprehensive error handling for authentication failures
- **SSL Flexibility**: Support for corporate environments with SSL certificate issues

## Installation

```bash
cd scripts/github_auth
pip install -r requirements.txt
```

## Environment Variables

Set these environment variables in your `.env` file or system environment:

```bash
# Required
GH_APP_ID=your_GH_APP_ID
GH_PRIVATE_KEY_PATH=path/to/your/private/key.pem

# Optional
VERIFY_SSL=true  # Set to false for corporate environments with SSL issues
```

## Usage

### Basic Usage

```python
from github_auth import GitHubAppAuth

# Initialize the auth handler
auth = GitHubAppAuth()

# Authenticate for an organization
if auth.authenticate_for_organization("your-org-name"):
    # Get authenticated session
    session = auth.get_authenticated_session()
    
    # Use session for API calls
    response = session.get("https://api.github.com/user")
    print(response.json())
else:
    print("Authentication failed")
```

### Advanced Usage

```python
from github_auth import GitHubAppAuth

# Initialize with custom parameters
auth = GitHubAppAuth(
    app_id="123456",
    private_key_path="/path/to/key.pem",
    verify_ssl=False  # For corporate environments
)

# Check authentication status
if auth.is_authenticated():
    print("Already authenticated")
else:
    auth.authenticate_for_organization("my-org")

# Get token information
token_info = auth.get_token_info()
print(f"Token expires at: {token_info['expires_at']}")
print(f"Time remaining: {token_info['remaining_seconds']} seconds")

# The session automatically handles token refresh
session = auth.get_authenticated_session()
```

### Using with GraphQL

```python
from github_auth import GitHubAppAuth

auth = GitHubAppAuth()
auth.authenticate_for_organization("my-org")
session = auth.get_authenticated_session()

# GraphQL query
query = """
{
  viewer {
    login
    name
  }
}
"""

response = session.post(
    "https://api.github.com/graphql",
    json={"query": query}
)
print(response.json())
```

## Integration with Existing Scripts

To use this authentication module in your existing scripts:

1. **Import the module**:
   ```python
   from github_auth import GitHubAppAuth
   ```

2. **Replace PAT authentication**:
   ```python
   # Old PAT method
   headers = {"Authorization": f"token {pat_token}"}
   
   # New GitHub App method
   auth = GitHubAppAuth()
   auth.authenticate_for_organization("org-name")
   session = auth.get_authenticated_session()
   ```

3. **Use the session for requests**:
   ```python
   # Instead of requests.get with headers
   response = session.get("https://api.github.com/repos/owner/repo")
   ```

## Error Handling

The module provides comprehensive error handling:

```python
try:
    auth = GitHubAppAuth()
    if auth.authenticate_for_organization("my-org"):
        session = auth.get_authenticated_session()
        # Your API calls here
    else:
        print("Failed to authenticate")
except ValueError as e:
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## File Structure

```
github_auth/
├── __init__.py              # Module initialization
├── github_app_auth.py       # Main authentication class
├── requirements.txt         # Dependencies
├── README.md               # This documentation
└── example_usage.py        # Usage examples
```

## Benefits over PAT

- **Enhanced Security**: GitHub Apps have more granular permissions
- **Organization-wide**: Works across all repositories in an organization
- **No Personal Dependency**: Not tied to individual user accounts
- **Automatic Token Management**: Handles token refresh automatically
- **Audit Trail**: Better tracking of API usage

## Troubleshooting

### SSL Certificate Issues
If you encounter SSL certificate errors in corporate environments:

```python
auth = GitHubAppAuth(verify_ssl=False)
```

Or set environment variable:
```bash
VERIFY_SSL=false
```

### Authentication Failures
- Verify your GitHub App ID and private key path
- Ensure the GitHub App is installed in the target organization
- Check that the private key file is readable
- Verify the organization name is correct

### Token Expiry
The module automatically handles token refresh, but if you encounter token-related errors:

```python
# Check token status
if not auth.is_authenticated():
    auth.authenticate_for_organization("org-name")
```

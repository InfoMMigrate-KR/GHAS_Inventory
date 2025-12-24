# Set Organization Owner Script

This script sets member users as owners (admin) of GitHub organizations using either the GitHub REST API or GraphQL API for better performance with bulk operations.

## Features

- **Single User Assignment**: Promote individual users to organization owners
- **Bulk CSV Processing**: Process multiple users from a CSV file
- **GraphQL Support**: Use GraphQL API for better performance with bulk operations
- **Environment Configuration**: Secure .env file configuration management
- **Concurrent Processing**: Parallel execution for faster bulk operations
- **Detailed Reporting**: Comprehensive success/failure reporting with JSON output
- **SSL Configuration**: Support for corporate environments
- **Interactive Mode**: Prompts for input when arguments are not provided
- **Membership Status Check**: Verifies current status before making changes

## Prerequisites

- GitHub App installed on the target organization(s)
- GitHub App must have the following permissions:
  - **Organization permissions**: Administration (read & write)
- Environment configuration via .env file:
  - `GH_APP_ID`: Your GitHub App ID
  - `GH_PRIVATE_KEY`: Path to your GitHub App's private key file

## Installation

```bash
cd scripts/set_org_owner
pip install -r requirements.txt

# Create .env file from example
cp .env.example .env
# Edit .env file with your GitHub App credentials
nano .env
```

## Environment Configuration

Create a `.env` file in the `scripts/set_org_owner` directory with your GitHub App credentials:

```bash
# Required
GH_APP_ID=123456
GH_PRIVATE_KEY=./github-app-private-key.pem

# Optional (with defaults)
VERIFY_SSL=true
MAX_WORKERS=5
DEFAULT_CSV_PATH=users.csv
```

**Security Note**: Never commit your `.env` file to version control. It contains sensitive credentials.

## CSV File Format

For bulk operations, create a CSV file with the following format:

```csv
username,organization,role,email
john_doe,example-org-1,admin,john.doe@example.com
jane_smith,example-org-1,admin,jane.smith@example.com
admin_user,example-org-2,admin,admin@example.com
```

**Required columns:**
- `username`: GitHub username
- `organization`: Organization name

**Optional columns:**
- `role`: User role (defaults to "admin")
- `email`: User email (for documentation purposes)

## Usage

### Quick Start

```bash
# Setup (one-time)
cp .env.example .env
# Edit .env with your GitHub App credentials

# Single user assignment
python set_org_owner.py --org my-org --username johndoe

# Bulk assignment with GraphQL (recommended)
python set_org_owner.py --csv --use-graphql
```

### Single User Assignment

**Interactive mode:**
```bash
python set_org_owner.py
```

**Command line:**
```bash
python set_org_owner.py --org my-organization --username johndoe
```

### Bulk Assignment from CSV

```bash
# Use default CSV path from .env file
python set_org_owner.py --csv

# Specify custom CSV path
python set_org_owner.py --csv custom_users.csv

# With GraphQL for better performance
python set_org_owner.py --csv --use-graphql
```

### Advanced Configuration

```bash
# Custom concurrent workers (override .env setting)
python set_org_owner.py --csv --max-workers 10

# Disable SSL verification (corporate environments)
python set_org_owner.py --csv --no-verify-ssl

# Combine options
python set_org_owner.py --csv users.csv --use-graphql --max-workers 3
```

## Performance Notes

**GraphQL vs REST API:**
- **GraphQL**: Recommended for bulk operations, better error handling, reduced API overhead
- **REST API**: Simple for single operations, good for basic use cases

**Concurrency:**
- Default: 5 concurrent workers (configurable in .env: `MAX_WORKERS=5`)
- Each organization processes separately to minimize authentication overhead
- Users within same organization process sequentially to avoid rate limits

## Output and Error Handling

### Console Output
- Real-time progress indicators for each user assignment
- Success/failure status with detailed error messages
- Summary report with counts and lists of results

### JSON Results File
For bulk operations: `org_owner_results_YYYYMMDD_HHMMSS.json`
```json
[
  {
    "username": "john_doe",
    "organization": "example-org",
    "success": true,
    "error": null
  }
]
```

### Common Errors

| Error | Solution |
|-------|----------|
| Missing environment variables | Ensure `.env` file exists with `GH_APP_ID` and `GH_PRIVATE_KEY` |
| Authentication failed | Verify GitHub App installation and permissions |
| User not found | Check username spelling |
| Forbidden (403) | Ensure GitHub App has Organization Administration permissions |
| Rate limit exceeded | Reduce `MAX_WORKERS` in `.env` file |

### Example Output
```
2025-12-24 10:00:00 - INFO - Setting john_doe as owner of my-org using GraphQL...
2025-12-24 10:00:01 - INFO - ✓ Successfully set john_doe as owner of my-org via GraphQL
2025-12-24 10:00:01 - INFO -   State: active
2025-12-24 10:00:01 - INFO -   Role: ADMIN
```

## GitHub App Setup

1. **Create/Configure GitHub App:**
   - Go to Organization Settings → Developer settings → GitHub Apps
   - Set **Organization permissions: Administration** to **Read & write**
   - Install the app on target organizations

2. **Get Credentials:**
   - Note your App ID
   - Generate and download private key (.pem file)
   - Add these to your `.env` file

## Security Best Practices

- ✅ Store credentials in `.env` file (never commit to version control)
- ✅ Use minimum required GitHub App permissions
- ✅ Validate CSV files before bulk operations
- ✅ Monitor GitHub audit logs for organization changes
- ✅ Use SSL verification except in trusted corporate environments

## API References

- [GitHub REST API - Organization Membership](https://docs.github.com/en/rest/orgs/members)
- [GitHub GraphQL API](https://docs.github.com/en/graphql/reference/mutations)
- [GitHub App Authentication](https://docs.github.com/en/developers/apps/building-github-apps/authenticating-with-github-apps)

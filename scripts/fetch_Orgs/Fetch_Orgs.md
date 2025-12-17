# GitHub Enterprise Organization Fetcher

## Overview

The `fetch_orgs.py` script is a Python tool designed to fetch and export all organizations within a GitHub Enterprise using the GitHub GraphQL API. It uses GitHub App authentication for enhanced security and provides comprehensive error handling with performance monitoring. The script is ideal for enterprise administrators who need a complete list of organizations under their enterprise account.

## Features

- **GraphQL API Integration**: Uses GitHub's GraphQL API for efficient data retrieval
- **GitHub App Authentication**: Secure authentication using GitHub Apps instead of Personal Access Tokens
- **Automatic Organization Discovery**: Automatically finds and uses available GitHub App installations for authentication
- **Comprehensive Logging**: Structured logging with timestamps and severity levels to both console and log files
- **Performance Monitoring**: Tracks request times, success rates, and provides detailed statistics
- **Enhanced Error Handling**: Categorized error handling for different types of failures (auth, rate limits, network)
- **Pagination Handling**: Automatically handles pagination to fetch all organizations regardless of count
- **Retry Logic**: Intelligent retry mechanism with exponential backoff for transient failures
- **CSV Export**: Exports organization data to CSV format with timestamps
- **Progress Tracking**: Real-time feedback on fetching progress with detailed timing information

## Architecture

### Core Class: `EnterpriseFetcher`

The main class that handles all organization fetching operations:

```python
class EnterpriseFetcher:
    def __init__(self)
    def _ensure_authentication(self, org_login=None)
    def _get_headers(self)
    def run_query(self, query, variables)
    def fetch_all_organizations(self)
    def save_to_csv(self, org_list, output_dir)
    def print_performance_stats(self)
```

### Key Components

1. **Initialization (`__init__`)**:
   - Loads environment variables for enterprise slug and GitHub App credentials
   - Sets up GitHub App authentication with predefined known organizations
   - Initializes performance tracking statistics
   - Configures structured logging

2. **Authentication Management**:
   - `_ensure_authentication()`: Manages GitHub App authentication with fallback organizations
   - `_get_headers()`: Generates HTTP headers for GraphQL requests
   - Automatic discovery and authentication with available GitHub App installations

3. **Query Execution (`run_query`)**:
   - Executes GraphQL queries with comprehensive error categorization
   - Handles HTTP errors (401, 403, 429, 5xx) with specific retry strategies
   - Implements intelligent rate limit handling with proper wait times
   - Tracks request statistics and performance metrics

4. **Data Fetching (`fetch_all_organizations`)**:
   - Implements pagination logic with progress tracking
   - Fetches all organizations from the enterprise with timing information
   - Provides detailed logging of each page fetch
   - Handles partial results gracefully in case of errors

5. **Data Export (`save_to_csv`)**:
   - Exports organization data to CSV format
   - Creates timestamped output files
   - Handles data validation and error cases

6. **Performance Monitoring (`print_performance_stats`)**:
   - Displays comprehensive execution statistics
   - Shows success rates, timing information, and retry counts
   - Helps with troubleshooting and optimization

## GraphQL Query

The script uses the following GraphQL query to fetch organization data:

```graphql
query($slug: String!, $cursor: String) {
  enterprise(slug: $slug) {
    name
    organizations(first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        login       
      }
    }
  }
}
```

### Query Parameters:
- `$slug`: The enterprise slug identifier
- `$cursor`: Pagination cursor for fetching subsequent pages

### Returned Data:
- `enterprise.name`: Name of the enterprise
- `organizations.nodes.login`: Login names of organizations
- `pageInfo`: Pagination information for handling large result sets

## Environment Variables

The script requires the following environment variables in a `.env` file:

```bash
# Required: GitHub Enterprise slug
GH_ENTERPRISE_SLUG=your-enterprise-slug

# Required: GitHub App credentials
GH_APP_ID=123456
GH_PRIVATE_KEY=path/to/your/private-key.pem

# Optional: SSL verification (default: true)
VERIFY_SSL=true
```

### GitHub App Requirements:
The GitHub App must have the following permissions:
- `read:org` - Read organization data
- `read:enterprise` - Read enterprise data
- `repo` - Read repository data (for comprehensive access)
- App must be installed on at least one organization within the enterprise

### Authentication Flow:
1. Script automatically discovers available GitHub App installations
2. Uses the first available organization for authentication
3. Generates installation-specific access tokens automatically
4. Handles token refresh and expiration automatically

## Usage

### Basic Execution:
```bash
python scripts/fetch_Orgs/fetch_orgs.py
```

### Expected Output:
```
2025-12-16 21:43:11,042 - INFO - Initialized GitHub App authentication for Enterprise: your-enterprise
2025-12-16 21:43:11,042 - INFO - Starting organization fetch...
2025-12-16 21:43:11,042 - INFO - Attempting authentication with organization: im-naga-ghas
Authenticating for organization: im-naga-ghas
Found installation ID: 99862049
Authentication successful!
2025-12-16 21:43:12,250 - INFO - Successfully authenticated with: im-naga-ghas
2025-12-16 21:43:14,527 - INFO - Page 1: Fetched 100 organizations (Total: 100, Time: 3.49s)
2025-12-16 21:43:16,250 - INFO - Page 2: Fetched 88 organizations (Total: 188, Time: 1.61s)
2025-12-16 21:43:16,353 - INFO - Completed fetching 188 organizations in 2 pages (Total time: 5.31s, Avg per page: 2.66s)

========================================
Total Organizations Found: 188
========================================
- automated-test-org-1
- byron-github-school
- cigbe-training-demo
- copilot-training-naga
- CSB-Demo
... and 183 more.
[*] Organizations saved to: scripts/output/organizations.csv
[✓] CSV report generated successfully!

==================================================
PERFORMANCE STATISTICS
==================================================
Total execution time: 5.31 seconds
Total API requests: 2
Failed requests: 0
Retry attempts: 0
Success rate: 100.0%
Average request time: 2.66s
==================================================
```

## Output Format

### CSV File Structure:
- **Filename**: `organizations.csv`
- **Location**: `scripts/output/`
- **Headers**: `login`
- **Encoding**: UTF-8

### Log File Structure:
- **Filename**: `fetch_orgs_YYYYMMDD_HHMMSS.log`
- **Location**: Same directory as script
- **Format**: Timestamped structured logs
- **Content**: Authentication details, API calls, errors, and performance metrics

### Sample CSV Content:
```csv
login
automated-test-org-1
byron-github-school
cigbe-training-demo
copilot-training-naga
CSB-Demo
```

## Error Handling

### Authentication Error Management:
1. **GitHub App Authentication**: Automatically tries multiple known organizations
2. **Token Expiration**: Automatic token refresh and regeneration
3. **Permission Issues**: Clear error messages with suggested fixes
4. **Installation Missing**: Helpful guidance on GitHub App installation

### Rate Limit Management:
1. **HTTP Rate Limits (429)**: Respects X-RateLimit-Reset headers with intelligent waiting
2. **GraphQL Rate Limits**: Implements 60-second cool-off periods
3. **Secondary Rate Limits**: Exponential backoff strategy

### Network Error Handling:
- **Connection Timeouts**: 60-second timeout with retry logic
- **Network Failures**: Automatic retry with exponential backoff
- **Server Errors (5xx)**: Intelligent retry with increasing delays
- **JSON Parse Errors**: Safe JSON parsing with error recovery

### Error Categories and Responses:

1. **Authentication Errors (401)**:
   - Automatic token refresh
   - Clear authentication cache
   - Retry with exponential backoff

2. **Permission Errors (403)**:
   - Detailed error logging
   - Permission guidance
   - Graceful failure with partial results

3. **Rate Limit Errors (429)**:
   - Respect rate limit reset times
   - Automatic waiting and retry
   - Performance impact tracking

4. **Server Errors (5xx)**:
   - Automatic retry with backoff
   - Detailed error logging
   - Graceful degradation

### Common Error Scenarios:

1. **Missing Environment Variables**:
   ```
   [X] Missing required environment variables: GH_APP_ID, GH_PRIVATE_KEY
   Please set the following in your .env file:
   - GH_ENTERPRISE_SLUG: Your GitHub enterprise slug
   - GH_APP_ID: Your GitHub App ID
   - GH_PRIVATE_KEY: Path to your GitHub App private key file
   ```

2. **GitHub App Not Installed**:
   ```
   ValueError: Could not authenticate with any known organization: ['org1', 'org2']. 
   Please ensure the GitHub App is installed on at least one of these organizations.
   ```

3. **Enterprise Not Found**:
   ```
   [X] Enterprise 'invalid-slug' not found or authentication lacks permission.
   ```

4. **Private Key File Missing**:
   ```
   FileNotFoundError: Private key file not found: path/to/private-key.pem
   ```

5. **Permission Denied**:
   ```
   2025-12-16 21:43:14,527 - WARNING - Access forbidden to some resources: 
   [{'type': 'FORBIDDEN', 'message': 'Although you appear to have the correct authorization credentials, the organization has an IP allow list enabled...'}]
   ```

## Performance Characteristics

### Efficiency Features:
- **Batch Fetching**: Fetches 100 organizations per GraphQL request
- **Token Rotation**: Maximizes rate limit utilization
- **Pagination**: Handles enterprises with thousands of organizations
- **Memory Efficient**: Processes data incrementally

### Typical Performance:
- **Small Enterprise** (< 100 orgs): 1-2 seconds
- **Medium Enterprise** (100-500 orgs): 5-15 seconds  
- **Large Enterprise** (500+ orgs): 30-60 seconds

## Dependencies

```python
import os
import sys
import time
import logging
import requests
import csv
from datetime import datetime
from typing import List, Dict, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from github_auth.github_app_auth import GitHubAppAuth
```

### Required Packages:
- `requests>=2.31.0` - HTTP library for API calls
- `python-dotenv>=1.0.0` - Environment variable management
- `PyJWT>=2.8.0` - JWT token generation for GitHub Apps
- `urllib3>=1.26.0` - HTTP client with connection pooling

### Internal Dependencies:
- `github_auth.github_app_auth.GitHubAppAuth` - GitHub App authentication module

## Integration Points

### Input Dependencies:
- `.env` file with required environment variables
- Valid GitHub Enterprise account with appropriate permissions
- Personal Access Tokens with correct scope permissions

### Output Dependencies:
- Write permissions to `scripts/fetch_languages/output/` directory
- Used by subsequent scripts that require organization lists

## Limitations

1. **GitHub App Installation**: Requires GitHub App to be installed on at least one organization within the enterprise
2. **Output Directory**: Configurable output directory (defaults to `scripts/output/`)
3. **Data Scope**: Only fetches organization login names, not detailed metadata
4. **Enterprise Scope**: Limited to single enterprise per execution
5. **Known Organizations**: Uses predefined list of known organizations for authentication fallback

## Security Considerations

1. **Token Management**: Store PATs securely in `.env` file
2. **Token Rotation**: Use multiple tokens to distribute API usage
3. **Logging**: Avoid logging sensitive token information
4. **File Permissions**: Ensure output files have appropriate permissions

## Troubleshooting

### Common Issues:

1. **Authentication Failures**:
   - Verify GitHub App is installed on organizations
   - Check GitHub App permissions (read:org, read:enterprise)
   - Ensure private key file path is correct and accessible
   - Verify enterprise slug spelling

2. **Rate Limit Issues**:
   - Monitor performance statistics for retry counts
   - Check GitHub App rate limits in organization settings
   - Ensure proper wait times between requests

3. **Empty Results**:
   - Verify enterprise slug spelling
   - Check GitHub App permissions
   - Confirm enterprise has organizations
   - Review log file for detailed error information

4. **Permission Errors**:
   - Check IP allow lists on organizations
   - Verify GitHub App installation scope
   - Review organization-level security settings

### Debug Steps:
1. Check log file (`fetch_orgs_YYYYMMDD_HHMMSS.log`) for detailed error information
2. Verify `.env` file configuration
3. Test GitHub App installation and permissions
4. Check enterprise settings and organization access
5. Review performance statistics for bottlenecks

### Log Analysis:
- **INFO level**: Normal operation and progress
- **WARNING level**: Non-critical issues (IP restrictions, etc.)
- **ERROR level**: Critical failures requiring attention
- Performance statistics show request success rates and timing

## Future Enhancements

Potential improvements for the script:
1. **Dynamic Organization Discovery**: Automatically discover all GitHub App installations instead of using predefined list
2. **Enhanced Metadata Collection**: Fetch additional organization details (member counts, repository counts, etc.)
3. **Configuration File**: Support external YAML/JSON configuration files
4. **Parallel Processing**: Implement concurrent requests for better performance with multiple organizations
5. **Database Export**: Support direct database exports (PostgreSQL, MySQL, etc.)
6. **Output Formats**: Support JSON, XML, and other export formats
7. **Incremental Updates**: Support for incremental organization discovery and updates
8. **Dashboard Integration**: Web dashboard for monitoring and visualization
9. **Notification System**: Email/Slack notifications for completion or errors
10. **Advanced Filtering**: Filter organizations by criteria (size, activity, etc.)

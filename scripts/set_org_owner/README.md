# Set Organization Owner Script

This script sets a member user as owner (admin) of a GitHub organization using the GitHub REST API.

## Overview

The script uses the GitHub App authentication to promote a user to organization owner by setting their role to "admin" using the [Set organization membership for a user](https://docs.github.com/en/enterprise-cloud@latest/rest/orgs/members?apiVersion=2022-11-28#set-organization-membership-for-a-user) API endpoint.

## Prerequisites

- GitHub App installed on the target organization
- GitHub App must have the following permissions:
  - **Organization permissions**: Administration (read & write)
- Environment variables configured:
  - `GH_APP_ID`: Your GitHub App ID
  - `GH_PRIVATE_KEY`: Path to your GitHub App's private key file

## Installation

```bash
cd scripts/set_org_owner
pip install -r requirements.txt
```

## Usage

### Interactive Mode

Run the script without arguments to be prompted for input:

```bash
python set_org_owner.py
```

### Command Line Arguments

Provide organization and username as arguments:

```bash
python set_org_owner.py --org my-organization --username johndoe
```

### With SSL Verification Disabled

For corporate environments with SSL certificate issues:

```bash
python set_org_owner.py --org my-organization --username johndoe --no-verify-ssl
```

## Features

- ✓ Checks current membership status before making changes
- ✓ Provides detailed feedback on operation success/failure
- ✓ Handles various error scenarios (user not found, insufficient permissions, etc.)
- ✓ Interactive prompts if arguments are not provided
- ✓ Warns if user is already an owner
- ✓ Supports SSL verification toggle for corporate environments

## API Behavior

When you set a user as organization owner using this script:

- **If the user is already a member**: Their role will be upgraded to "admin" (owner)
- **If the user is not a member**: An invitation will be sent with the "admin" role
- **State values**:
  - `active`: User is already a member and role was updated
  - `pending`: Invitation was sent to the user

## Example Output

```
2025-12-23 10:00:00 - INFO - Initializing GitHub App authentication...
2025-12-23 10:00:01 - INFO - Successfully authenticated as GitHub App
2025-12-23 10:00:01 - INFO - Checking current membership status for johndoe...
2025-12-23 10:00:02 - INFO - Current status - Role: member, State: active
2025-12-23 10:00:02 - INFO - Setting johndoe as owner of my-organization...
2025-12-23 10:00:03 - INFO - ✓ Successfully set johndoe as owner of my-organization
2025-12-23 10:00:03 - INFO -   State: active
2025-12-23 10:00:03 - INFO -   Role: admin
2025-12-23 10:00:03 - INFO - ✓ Operation completed successfully
```

## Error Handling

The script handles various error scenarios:

- **404**: Organization or user not found
- **403**: Insufficient permissions (check GitHub App permissions)
- **422**: Validation failed (user might not exist or have pending invitation)
- **Network errors**: Connection issues or timeouts

## GitHub App Permissions

Ensure your GitHub App has the following permissions:

1. Go to your GitHub App settings
2. Under "Permissions & events"
3. Set "Administration" to "Read & write" under "Organization permissions"
4. Install/update the app on your organization

## Security Notes

- This script requires admin-level permissions
- Use with caution as it grants full organization access
- Always verify the username before executing
- Consider implementing approval workflows for production use

## Related Scripts

- [`fetch_orgs.py`](../fetch_Orgs/fetch_orgs.py) - Fetch organization information
- [`add_enterprise_team_to_all_organizations.py`](../add_enterprise_team_to_all_organizations.py) - Manage enterprise teams

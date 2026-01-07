# GitHub Actions Workflow for GitHub App Installation

This workflow automates the installation of GitHub Apps across all organizations in a GitHub Enterprise using the `install_github_all.py` script.

## Prerequisites

### GitHub Repository Variables (Non-sensitive Configuration)

Set these in your repository settings under **Settings > Secrets and variables > Actions > Variables**:

- `GH_ENTERPRISE_SLUG`: Your GitHub Enterprise slug (e.g., `my-enterprise`)
- `INSTALLER_APP_ID`: The App ID of your installer app (e.g., `12345`)
- `INSTALLER_INSTALL_ID`: The Installation ID of the installer app on your enterprise (e.g., `67890`)
- `AUTOMATION_APP_CLIENT_IDS`: Comma-separated Client IDs of automation apps (e.g., `Iv1.abc123,Iv1.def456`)

### GitHub Repository Secrets (Sensitive Data)

Set these in your repository settings under **Settings > Secrets and variables > Actions > Secrets**:

- `INSTALLER_PRIVATE_KEY`: The complete PEM file content of your installer app's private key (including `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----`)
- `AUTOMATION_APPS_CONFIG`: JSON configuration for uninstall operations (only required if using uninstall mode)

#### Example `AUTOMATION_APPS_CONFIG` format:
```json
{
  "Iv1.abc123": {
    "app_id": "54321", 
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n-----END PRIVATE KEY-----"
  },
  "Iv1.def456": {
    "app_id": "54322",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n-----END PRIVATE KEY-----"
  }
}
```

## Workflow Usage

### Manual Trigger

1. Go to your repository's **Actions** tab
2. Select the **Install GitHub Apps Across Enterprise** workflow
3. Click **Run workflow**
4. Optionally customize parameters:
   - **Repository selection**: Choose `all` or `selected` repositories
   - **Enable parallel processing**: For faster execution
   - **Dry run**: Preview changes without applying them
   - **Uninstall mode**: Remove apps instead of installing

### Workflow Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `repository_selection` | ❌ | `all` | Repository selection: `all` or `selected` |
| `parallel` | ❌ | `false` | Enable parallel processing |
| `workers` | ❌ | `5` | Number of parallel workers |
| `dry_run` | ❌ | `false` | Preview changes without making them |
| `uninstall` | ❌ | `false` | Uninstall apps instead of installing |

## Setup Instructions

### 1. Create Repository Variables

```bash
# Navigate to: Settings > Secrets and variables > Actions > Variables
# Create these variables:
GH_ENTERPRISE_SLUG=my-enterprise
INSTALLER_APP_ID=12345
INSTALLER_INSTALL_ID=67890
AUTOMATION_APP_CLIENT_IDS=Iv1.abc123,Iv1.def456
```

### 2. Create Repository Secrets

```bash
# Navigate to: Settings > Secrets and variables > Actions > Secrets
# Create these secrets:

# INSTALLER_PRIVATE_KEY (paste the complete PEM content)
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...
[... complete private key content ...]
-----END PRIVATE KEY-----

# AUTOMATION_APPS_CONFIG (only needed for uninstall operations)
{
  "Iv1.abc123": {
    "app_id": "54321",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
  }
}
```

### 3. GitHub App Configuration

Ensure you have:

1. **Installer App**: Enterprise-owned app with "Enterprise organization installations" (read/write) permission
2. **Automation App(s)**: The apps you want to install across organizations

## Example Workflows

### Standard Installation
```yaml
# Manual trigger with default settings:
# Uses all repository variables and secrets
# Installs apps to all repositories
```

### Parallel Installation
```yaml
# Manual trigger with these inputs:
parallel: true
workers: "10"
```

### Dry Run Preview
```yaml
# Manual trigger with these inputs:
dry_run: true
```

### Uninstall Apps
```yaml
# Manual trigger with these inputs:
uninstall: true
# Note: Requires AUTOMATION_APPS_CONFIG secret
```

## Outputs

The workflow creates the following artifacts:

- **github-app-installation-results**: Complete execution results including logs and JSON output
- **organizations-csv**: List of discovered organizations in CSV format

## Security Considerations

- Private keys are stored as repository secrets and never exposed in logs
- Temporary key files are created with restricted permissions (`600`)
- All sensitive files are cleaned up after execution
- The workflow only has `contents: read` permissions

## Troubleshooting

### Common Issues

1. **Missing required variables/secrets**: Ensure all required repository variables and secrets are set
2. **Invalid private key format**: Ensure the PEM key includes header and footer lines
3. **Insufficient permissions**: Verify the installer app has correct enterprise permissions
4. **Rate limiting**: Use the `workers` parameter to adjust parallel execution

### Debug Mode

To enable verbose logging, the workflow automatically includes the `--verbose` flag. Check the workflow logs for detailed execution information.

## Related Documentation

- [GitHub Enterprise App Installation API](https://docs.github.com/en/enterprise-cloud@latest/admin/managing-github-apps-for-your-enterprise/automate-installations)
- [GitHub Actions Workflow Syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions)
- [Managing Repository Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)

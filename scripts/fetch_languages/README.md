# GitHub Enterprise Language Analysis

A Python tool for analyzing programming languages used across all repositories in a GitHub Enterprise using GraphQL API. This tool provides comprehensive language statistics and usage patterns across your entire enterprise.

## Features

- **Enterprise-wide Coverage**: Automatically discovers and analyzes all organizations and repositories
- **GraphQL API**: Uses GitHub's GraphQL API for efficient data retrieval
- **Comprehensive Analysis**: 
  - Language distribution by repository
  - Byte counts and percentages for each language
  - Primary language identification
- **Rich Reporting**: 
  - Detailed repository-language breakdowns
  - Aggregated language statistics
  - Multiple output formats (CSV)
- **Robust Error Handling**: Retry logic, multi-token support, comprehensive logging, and error CSV with details
- **Smart Parsing**: Extracts project codes and cost centers from organization names
- **Progressive CSV Writing**: Language and error CSV files are written incrementally as each organization is processed
- **Detailed Logging**: All operations and errors are logged with timestamps
- **Execution Summary**: At the end, the script logs total execution time and success/failure counts

## Prerequisites

- Python 3.9+
- GitHub Personal Access Token (PAT) with appropriate permissions:
  - `read:org` - Read organization data
  - `repo` - Read repository data (for private repos)
  - `read:enterprise` - Read enterprise data (if querying enterprise-level data)

## Setup

### 1. Install Dependencies

Navigate to the project root and install required packages:

```bash
pip install -r requirements.txt
```

Required packages:
- `requests>=2.31.0`
- `pandas>=2.0.0`
- `openpyxl>=3.1.0`
- `python-dotenv>=1.0.0`
- `PyJWT>=2.8.0` (for GitHub App authentication)

### 2. Configure Environment Variables

Create a `.env` file in the project root directory (or use the `.env.example` as a template):

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required: Your GitHub Enterprise slug
GH_ENTERPRISE_SLUG=your-enterprise-slug

# Required: GitHub Personal Access Token(s)
# Can use a single token or comma-separated list for rotation
GH_PATS=ghp_your_token_here
# Or multiple tokens for better rate limiting
GH_PATS=ghp_token1,ghp_token2,ghp_token3

# Optional: Output format (currently only CSV is implemented in the script)
OUTPUT_FORMAT=csv
```

**Note**: The script uses Personal Access Token (PAT) authentication. Multiple tokens can be provided for better rate limit handling.

## Usage

### Basic Usage

Run the language analysis script directly:

```bash
cd scripts/fetch_languages
python fetch_languages.py
```

The script will:
1. Look for an organizations CSV file at `scripts/output/organizations.csv`
2. If not found, it will suggest running the fetch_orgs.py script first
3. Process each organization and fetch language data for all repositories
4. Generate output files in `scripts/fetch_languages/output/`

### Getting Organization Data

If you don't have an organizations CSV file, you need to run the organization fetcher first:

```bash
cd scripts/fetch_Orgs
python fetch_orgs.py
```

This will generate `scripts/output/organizations.csv` which the language script will use.

### Output

The script generates reports in `scripts/fetch_languages/output/` directory:

- `languages_report_YYYYMMDD_HHMMSS.csv`: Progressive language data for all repositories
- `languages_errors_YYYYMMDD_HHMMSS.csv`: Progressive error log for organizations that failed
- `languages_summary_YYYYMMDD_HHMMSS.csv`: Aggregated language statistics summary

#### Error CSV Schema
| Column        | Description                                 |
|--------------|---------------------------------------------|
| Organization | Organization name                           |
| Error_Type   | Categorized error (e.g., TOKEN_POLICY, SAML) |
| Error_Message| Full error message                          |
| Timestamp    | When error occurred                         |

### Console Output

The script provides progress updates in the console:
```
Scanning organization: example-org (1/10)
  ✓ Processed 25 repositories
  ✓ Found 150 language records
Scanning organization: another-org (2/10)
  ⚠ SKIP: Token Policy Restriction (SSO/Expiry)
...
Total execution time: 45.23 seconds
Organizations processed: 10
Successful: 8
Failed: 2
```

## Output Data Schema

### Languages Report CSV

| Column | Description |
|--------|-------------|
| Organization | GitHub organization name |
| Repository | Repository name |
| Language | Programming language name |
| Bytes | Bytes of code in this language |
| Percentage | Percentage of repository code in this language |

### Languages Summary CSV

| Column | Description |
|--------|-------------|
| Language | Programming language name |
| Repository_Count | Number of repositories using this language |
| Total_Bytes | Total bytes of code in this language |

## Organization Name Parsing

The script can parse organization names in the format `xxxxx-yyyyy-zzzzz`:
- **Project_Code**: First segment (xxxxx)
- **Cost_Center**: Last segment (zzzzz)

Organizations not following this format will be processed as-is.

## Performance & Rate Limits

- **GraphQL Efficiency**: Fetches up to 50 repositories per query with pagination
- **Multi-token Support**: Can rotate through multiple tokens provided in `GH_PATS` for better rate limits
- **Retry Logic**: Exponential backoff for transient failures
- **Rate Limit Handling**: Automatic delays when rate limits are low

### Estimated Execution Time

- Small enterprise (< 50 repos): 1-2 minutes
- Medium enterprise (50-500 repos): 5-10 minutes
- Large enterprise (> 500 repos): 15-30 minutes

## Troubleshooting

### Authentication Errors

```
ValueError: Please set GH_PATS and GH_ENTERPRISE_SLUG in .env file
```
**Solution**: Ensure `GH_PATS` and `GH_ENTERPRISE_SLUG` are set in your `.env` file

### Organizations CSV Not Found

```
Organizations CSV file not found
```
**Solution**: 
- Run the fetch_orgs.py script first to generate the organizations.csv file
- Or ensure the organizations.csv file exists at `scripts/output/organizations.csv`

### Rate Limit Issues

```
GraphQL errors: API rate limit exceeded
```
**Solution**:
- Use multiple tokens in `GH_PATS` (comma-separated)
- Wait for rate limit to reset (check logs for reset time)

### Missing Repositories

If some repositories are missing from the report:
- Check repository access permissions
- Verify token has appropriate scopes (`read:org`, `repo`, `read:enterprise`)
- Review the error CSV file for specific organization failures

## Advanced Configuration

### Custom Language Count

To fetch more than 10 languages per repository, modify the GraphQL query in the script:

```python
languages(first: 20, orderBy: {field: SIZE, direction: DESC})
```

### Custom Repository Filters

The script currently fetches repositories ordered by `UPDATED_AT`. You can modify the query to add additional filters if needed.

## GitHub Actions Integration

This script is automated by the 'Analyze Repository Languages' workflow in .github/workflows/fetch-language-analysis.yml.

## Support

For issues or questions:
1. Check the error CSV file in `scripts/fetch_languages/output/`
2. Review the troubleshooting section above
3. Verify your token permissions and enterprise access
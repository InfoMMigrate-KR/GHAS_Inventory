# GitHub Enterprise Language Analysis

A Python tool for analyzing programming languages used across all repositories in a GitHub Enterprise using GraphQL API. This tool provides comprehensive language statistics and usage patterns across your entire enterprise.

## Features


- **Enterprise-wide Coverage**: Automatically discovers and analyzes all organizations and repositories
- **Comprehensive Analysis**: 
  - Language distribution by repository
  - Byte counts and percentages for each language
  - Primary language identification
  - Language colors and metadata
- **Rich Reporting**: 
  - Detailed repository-language breakdowns
  - Aggregated language statistics
  - Multiple output formats (Excel, CSV)
- **Robust Error Handling**: Retry logic, multi-token support, comprehensive logging, and error CSV with details
- **Smart Parsing**: Extracts project codes and cost centers from organization names
- **Progressive CSV Writing**: Language and error CSV files are written incrementally as each organization is processed
- **Detailed Logging & Timing**: All operations and errors are logged to a timestamped log file in `scripts/fetch_languages/output/logs/`, with a timing report CSV for per-organization analytics
- **Execution Summary**: At the end, the script logs total execution time, success/failure counts, average/fastest/slowest org times, and processing rate

## Prerequisites

- Python 3.9+
- GitHub Personal Access Token(s) with appropriate permissions:
  - `admin:org` - Read organization data
  - `repo` - Read repository data (for private repos)
  - `admin:enterprise` - Read enterprise data

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
# Single token:
GITHUB_TOKEN=ghp_your_token_here

# Or multiple tokens (comma-separated) for better rate limit handling:
GITHUB_TOKENS=ghp_token1,ghp_token2,ghp_token3

# Optional: Output format (default: excel)
OUTPUT_FORMAT=excel  # Options: excel, csv
```

## Usage

### Basic Usage

Run the script from the project root or scripts directory:

```bash
python scripts/fetch_languages/fetch_languages.py
```

### Output

The script generates reports in `scripts/fetch_languages/output/` directory:

- `languages_report_YYYYMMDD_HHMMSS.csv`: Progressive language data
- `languages_errors_YYYYMMDD_HHMMSS.csv`: Progressive error log
- `languages_summary_YYYYMMDD_HHMMSS.csv`: Language summary
- `logs/language_scan_YYYYMMDD_HHMMSS.log`: Detailed execution log
- `logs/timing_report_YYYYMMDD_HHMMSS.csv`: Per-org timing analytics

#### Error CSV Schema
| Column        | Description                                 |
|--------------|---------------------------------------------|
| Organization | Organization name                           |
| Error_Type   | Categorized error (e.g., TOKEN_POLICY, SAML) |
| Error_Message| Full error message                          |
| Timestamp    | When error occurred                         |
| HTTP_Status  | HTTP status code if applicable              |

#### Timing Report CSV Schema
| Column           | Description                                 |
|------------------|---------------------------------------------|
| organization     | Organization name                           |
| duration_seconds | Time taken to process (seconds)             |
| repositories     | Number of repositories processed            |
| language_records | Number of language records extracted        |
| status           | SUCCESS or error type                       |

### Logs
- All logs are saved to `scripts/fetch_languages/output/logs/`.
- Includes start/end time, per-org timing, error details, and summary statistics.

### Execution Summary Example
```
=== EXECUTION SUMMARY ===
Total execution time: 125.45 seconds (2.1 minutes)
Organizations processed: 185
Successful organizations: 167
Failed organizations: 18
Average time per successful org: 0.68 seconds
Fastest organization: 0.12 seconds
Slowest organization: 5.23 seconds (customer-sandbox)
Processing rate: 1,247.3 language records per second
```

## Output Data Schema

### Repository Languages Sheet

| Column | Description |
|--------|-------------|
| Organization_Name | GitHub organization name |
| Project_Code | Parsed project code from org name (first segment) |
| Cost_Center | Parsed cost center from org name (last segment) |
| Repository_Name | Repository name |
| Repository_Full_Name | Full repository path (org/repo) |
| Is_Private | Whether repository is private |
| Is_Archived | Whether repository is archived |
| Is_Fork | Whether repository is a fork |
| Primary_Language | Primary language detected by GitHub |
| Language | Specific language being reported |
| Language_Bytes | Bytes of code in this language |
| Language_Percentage | Percentage of repository code in this language |
| Language_Color | GitHub color code for the language |
| Total_Languages_Count | Total number of languages in repository |
| Total_Code_Bytes | Total bytes of code in repository |
| Topics | Repository topics (comma-separated) |
| Created_At | Repository creation timestamp |
| Updated_At | Repository last update timestamp |
| Pushed_At | Repository last push timestamp |

### Language Summary Sheet

| Column | Description |
|--------|-------------|
| Language | Programming language name |
| Repository_Count | Number of repositories using this language |
| Total_Bytes | Total bytes of code in this language |
| Percentage_Of_Total_Code | Percentage of all code in enterprise |
| Percentage_Of_Repos | Percentage of repositories using this language |

## Organization Name Parsing

The script parses organization names in the format `xxxxx-yyyyy-zzzzz`:
- **Project_Code**: First segment (xxxxx)
- **Cost_Center**: Last segment (zzzzz)

Organizations not following this format will have:
- Project_Code: "NO PROJECT CODE"
- Cost_Center: "NO COST CENTER"

## Performance & Rate Limits

- **GraphQL Efficiency**: Fetches up to 100 repositories per query
- **Multi-token Support**: Rotates through multiple tokens for better rate limits
- **Retry Logic**: Exponential backoff for transient failures
- **Rate Limit Consideration**: Small delays between organization queries

### Estimated Execution Time

- Small enterprise (< 50 repos): 1-2 minutes
- Medium enterprise (50-500 repos): 5-10 minutes
- Large enterprise (> 500 repos): 15-30 minutes

## Troubleshooting

### Authentication Errors

```
ValueError: No GitHub token found
```
**Solution**: Ensure `GITHUB_TOKEN` or `GITHUB_TOKENS` is set in your `.env` file

### Enterprise Not Found

```
ValueError: Enterprise not found or not accessible
```
**Solution**: 
- Verify `GH_ENTERPRISE_SLUG` is correct
- Ensure your token has `read:enterprise` permission
- Check you have access to the enterprise

### Rate Limit Issues

```
GraphQL errors: API rate limit exceeded
```
**Solution**:
- Use multiple tokens in `GITHUB_TOKENS` (comma-separated)
- Wait for rate limit to reset (check logs for reset time)
- Reduce concurrent operations

### Missing Repositories

If some repositories are missing from the report:
- Check repository access permissions
- Verify token has appropriate scopes
- Review logs for errors during fetching

## Advanced Configuration

### Custom Language Count

To fetch more than 10 languages per repository, modify the `LANGUAGES_PER_REPO` constant:

```python
LANGUAGES_PER_REPO = 20  # Fetch top 20 languages per repo
```

And update the GraphQL query `languages(first: 20, ...)`

### Custom Repository Filters

Add filters to the GraphQL query to exclude certain repositories:

```graphql
repositories(first: 100, after: $after, isArchived: false) {
  # Only fetch non-archived repositories
}
```

## Integration with CI/CD

This script can be integrated into GitHub Actions or other CI/CD pipelines:

```yaml
- name: Analyze Enterprise Languages
  env:
    GH_ENTERPRISE_SLUG: ${{ secrets.ENTERPRISE_SLUG }}
    GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
    OUTPUT_FORMAT: csv
  run: |
    python scripts/fetch_languages/fetch_languages.py
```

## Contributing

When contributing, ensure:
1. Code follows existing patterns and style
2. Error handling is comprehensive
3. Logging is informative
4. Documentation is updated

## Support

For issues or questions:
1. Check the logs in `scripts/fetch_languages/output/logs/`
2. Review the troubleshooting section above
3. Verify your token permissions and enterprise access


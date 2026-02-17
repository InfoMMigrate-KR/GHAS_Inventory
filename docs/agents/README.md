# GitHub Copilot Custom Agents

This directory contains custom agent definitions for GitHub Copilot that provide specialized capabilities for migration and automation tasks.

## 📁 Agent Definitions

### Jenkins to GitHub Actions Migration Agent

**File**: `jenkins-migrator.agent.md`

**Purpose**: Specialized agent for migrating existing Jenkins pipelines (declarative, scripted, and YAML-based) to GitHub Actions workflows.

**Capabilities**:
- Converts Jenkins declarative pipelines to GitHub Actions workflows
- Handles Jenkins scripted pipelines (Groovy-based)
- Supports YAML-based Jenkins configurations
- Expands Jenkins shared library calls inline
- Migrates credential bindings to GitHub Secrets
- Validates converted workflows with actionlint
- Creates comprehensive migration documentation

**Usage**: This agent should be deployed to the `.github/agents/` directory when ready for production use.

## 🔒 Deployment Notes

### Protection Rules

The `.github/agents/` directory is protected by repository rules to ensure agent definitions are reviewed before deployment. This is a security measure to prevent unauthorized agent configurations from being introduced.

### Deployment Process

To deploy an agent from this documentation directory to the active agents directory:

1. **Review**: Ensure the agent definition has been reviewed and approved
2. **Test**: Validate the agent configuration follows GitHub Copilot agent standards
3. **Request Bypass**: Use the protection bypass workflow to deploy to `.github/agents/`
4. **Verify**: Test the agent functionality after deployment

## 📖 Agent Configuration Reference

Each agent file follows the GitHub Copilot custom agent format:

```markdown
---
name: "Agent Display Name"
description: "Brief description of agent purpose"
infer: true  # Allow automatic delegation to this agent
---

# Agent Instructions

Detailed instructions and guidance for the agent...
```

### Required Fields

- **name**: Display name for the agent (shown in Copilot UI)
- **description**: Brief description (used for agent selection)
- **infer**: Whether Copilot can automatically delegate to this agent

### Optional Fields

- **tools**: Array of allowed tools (omit to allow all tools)
- **metadata**: Custom metadata for organizational purposes

## 🔗 Related Documentation

- [GitHub Copilot Custom Agents Documentation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-custom-agents)
- [Custom Agents Configuration Reference](https://docs.github.com/en/copilot/reference/custom-agents-configuration)

## 📝 Creating New Agents

When creating new agent definitions:

1. Create the agent file in this `docs/agents/` directory first
2. Use the `.agent.md` naming convention
3. Include YAML front matter with required fields
4. Provide comprehensive instructions in the markdown body
5. Test the agent configuration format
6. Follow the deployment process to move to `.github/agents/`

## ⚠️ Important Notes

- Agent definitions in this directory are for **documentation and review**
- Only agents in `.github/agents/` are active and available to Copilot
- Always review agent permissions and capabilities before deployment
- Follow security best practices when defining agent instructions
- Keep agent definitions version-controlled and reviewed

# RACI Matrix - GitHub Secret Scanning

## Overview
This RACI matrix defines roles and responsibilities for GitHub Advanced Security (GHAS) Secret Scanning implementation and operations.

### RACI Legend
- **R** (Responsible): Person(s) who perform the work
- **A** (Accountable): Person ultimately answerable for the activity
- **C** (Consulted): People who provide input and expertise
- **I** (Informed): People who are kept updated on progress

---

## Roles

| Role | Description |
|------|-------------|
| **AppSec** | Application Security team responsible for defining security policies, tracking metrics, and overseeing secret scanning implementation |
| **Security Champions** | Embedded security advocates within development teams who assist with security practices and alert triage |
| **Developers** | Development team members who write code and are responsible for remediating security issues |
| **GitHub Admin** | Platform administrators who manage GitHub organization settings, permissions, and configurations |

---

## RACI Matrix

| Activity | AppSec | Security Champions | Developers | GitHub Admin |
|----------|--------|-------------------|------------|--------------|
| **Planning & Setup** |
| Define secret management & scanning policy | A | C | I | I |
| Maintain GitHub org-wide scanning settings | C | C | I | A/R |
| Enable secret scanning | A | R | I | R |
| Manage GitHub Access/Permissions | C | I/C | I | A/R |
| Configure patterns | A | R | I | A |
| **Monitoring & Reporting** |
| Track and Report Metrics | A | I | R | I |
| Monitor secret scanning alerts | A | R | I | I |
| **Operations** |
| Triage alerts | A | R | I | I |
| Validate false positives / false negatives | A | R | C | I |
| Notify developers | A | R | I | I |
| Investigate alerts exposure impact | A | R | I | I |
| **Remediation** |
| Revoke/Rotate secrets | C | R | R | I |
| Implement remediation steps in code | I | C | R | I |
| Create incident review (PR) | I | R | R | I |

---

## Key Workflows

### 1. New Secret Alert Workflow

```
1. Alert Generated (GitHub) → AppSec (I), Security Champions (I)
2. Initial Triage → Security Champions (R), AppSec (A)
3. Validation → Security Champions (R), AppSec (A)
4. Notify Developers → Security Champions (R), AppSec (A)
5. Investigate Exposure Impact → Security Champions (R), AppSec (A)
6. Remediation → Developers (R), Security Champions (C)
7. Verification → Security Champions (R), AppSec (A)
8. Closure → AppSec (A)
```

### 2. Push Protection Bypass Workflow

```
1. Bypass Request → Developer (R)
2. Review Request → Security Champions (R), AppSec (A)
3. Approve/Deny → AppSec (A)
4. Track Exception → Security Champions (R)
5. Follow-up Review → AppSec (A)
```

### 3. Incident Review Process

```
1. Identify Incident → Security Champions (R), AppSec (A)
2. Investigate Impact → Security Champions (R), AppSec (A)
3. Revoke/Rotate Secrets → Developers (R), Security Champions (R)
4. Implement Code Fix → Developers (R)
5. Create Incident Review PR → Developers (R), Security Champions (R)
6. Review & Approve → Security Champions (C), AppSec (A)
7. Document Lessons Learned → Security Champions (R), AppSec (A)
```

### 4. Monthly Metrics Review

```
1. Generate Reports → AppSec (A)
2. Track Metrics → Developers (R), AppSec (A)
3. Analyze Trends → Security Champions (C), AppSec (A)
4. Identify Improvements → AppSec (A), Security Champions (C)
```

---

## Service Level Agreements (SLAs)

| Alert Severity | Initial Triage | Remediation | Responsible |
|----------------|---------------|-------------|-------------|
| **Critical** (Known pattern, public repo) | 1 hour | 4 hours | AppSec (A), Security Champions (R), Developers (R) |
| **High** (Known pattern, private repo) | 4 hours | 24 hours | AppSec (A), Security Champions (R), Developers (R) |
| **Medium** (Custom pattern) | 24 hours | 3 days | AppSec (A), Security Champions (R), Developers (R) |
| **Low** (Potential match) | 3 days | 7 days | Security Champions (R), Developers (R) |

---

## Escalation Path

1. **Level 1**: Developer → Security Champions
2. **Level 2**: Security Champions → AppSec
3. **Level 3**: AppSec → Security Leadership/Management

---

## Notes

- This matrix should be reviewed and updated quarterly
- Roles may be adapted based on organizational structure and team size
- GitHub Admin is responsible for platform configuration and access management
- Security Champions act as the bridge between AppSec and development teams
- Clear communication channels should be established between all roles
- Automation should be leveraged where possible to reduce manual overhead
- All incidents should be documented with post-incident reviews (PRs)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-01-21 | Initial RACI matrix creation | - |


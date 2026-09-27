# Data Backup Policy

## Overview
All company data must be stored in approved locations. Data stored only on local devices is not backed up and is at risk of permanent loss.

## Approved Storage Locations
| Location | Backup Frequency | Retention | Access |
|---|---|---|---|
| OneDrive (personal) | Real-time sync | 1 year recycle bin | Individual |
| SharePoint (team) | Real-time sync | 1 year recycle bin | Team |
| Azure Blob Storage | Daily snapshot | 90 days | IT-managed |
| SQL Server (prod) | Every 15 minutes | 35 days | DBA team |
| Local device | NOT BACKED UP | N/A | Individual risk |

## What Must Be Backed Up
- All work documents, spreadsheets, presentations.
- Source code (must be in Git — GitHub/Azure DevOps).
- Email (automatically retained in Microsoft 365 for 7 years).
- Client data and contracts (must be in SharePoint, not local).

## Recovery Procedures

### Accidentally Deleted OneDrive / SharePoint File
1. Check the recycle bin in OneDrive/SharePoint (retained 93 days).
2. If not in recycle bin, submit an IT ticket for a version restore.
3. IT can restore files up to 1 year old from backup.

### Local Drive Failure
1. Raise a P1 ticket immediately.
2. IT will attempt data recovery using forensic tools.
3. Recovery is not guaranteed — always sync to OneDrive.

### Database Recovery
1. Only DBAs can initiate database restores.
2. Raise a P1 ticket and escalate to the DBA team.
3. Point-in-time recovery available within the 35-day window.

## Compliance
- Data backup logs are audited quarterly.
- Storing sensitive data (PII, financial) locally on devices without encryption is a policy violation.
- Violations are reported to the Compliance team.
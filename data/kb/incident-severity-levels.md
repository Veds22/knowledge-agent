# Incident Severity Levels

## Overview
All IT incidents are classified into four severity levels (P1–P4) to ensure appropriate response times and escalation paths.

## P1 — Critical
**Definition:** Complete outage or security breach affecting the entire organisation or critical business systems.

**Examples:**
- Company-wide network or internet outage.
- Core business application (ERP, CRM) completely unavailable.
- Confirmed security breach or ransomware attack.
- Data loss affecting production systems.

**Response SLA:** Immediate response within 15 minutes. 24/7 on-call engineer notified.
**Escalation:** Automatically escalated to Head of IT and CTO.
**Resolution target:** 4 hours.

## P2 — High
**Definition:** Major functionality impaired for a significant group of users or a critical system degraded.

**Examples:**
- Email service unavailable for a department.
- VPN inaccessible for more than 10 users.
- Payment processing system degraded.
- Security vulnerability actively being exploited.

**Response SLA:** 30 minutes during business hours; 1 hour outside.
**Escalation:** Senior IT Engineer assigned.
**Resolution target:** 8 hours.

## P3 — Medium
**Definition:** Single user or small group impacted. Workaround available.

**Examples:**
- Individual unable to connect to VPN.
- Printer not working in one department.
- Software installation failure on one machine.
- Password reset required.

**Response SLA:** 4 business hours.
**Escalation:** Standard IT Helpdesk queue.
**Resolution target:** 2 business days.

## P4 — Low
**Definition:** Minor issue or service request with no productivity impact.

**Examples:**
- Hardware upgrade request.
- New software installation request.
- Account access request for a new tool.
- General IT query or information request.

**Response SLA:** 1 business day.
**Escalation:** None — handled in standard queue.
**Resolution target:** 5 business days.

## Escalation Path
```
P4 → Helpdesk Queue
P3 → Helpdesk Queue → Senior Engineer (if unresolved in 2 days)
P2 → Senior Engineer → IT Manager (if unresolved in 4 hours)
P1 → On-call Engineer → IT Manager → CTO (immediate)
```
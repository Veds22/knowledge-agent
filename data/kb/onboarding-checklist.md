# IT Onboarding Checklist

## Overview
This checklist must be completed for every new employee within their first 3 business days. IT completes items marked [IT]; the employee completes items marked [Employee].

## Day 1

### Account Setup [IT]
- [ ] Create Active Directory account with corporate email.
- [ ] Assign Microsoft 365 licence (E3 or E5 based on role).
- [ ] Add to relevant distribution lists and Teams channels.
- [ ] Create Slack account and add to company workspace and team channels.
- [ ] Set up MFA on Microsoft Authenticator.

### Device Setup [IT]
- [ ] Provision and image laptop (Windows or macOS per role).
- [ ] Install mandatory software: Cisco AnyConnect, CrowdStrike, Microsoft 365, Slack.
- [ ] Enable BitLocker (Windows) or FileVault (macOS).
- [ ] Enrol in JAMF (macOS) or SCCM (Windows) for remote management.
- [ ] Label device with asset tag and record in asset register.

### Employee Actions [Employee]
- [ ] Log in with temporary password and set new password meeting policy requirements.
- [ ] Register MFA device at `https://mfa.internal`.
- [ ] Set up Outlook email signature using the approved template.
- [ ] Connect to corporate WiFi (`CORP-INTERNAL`).
- [ ] Install and test Cisco AnyConnect VPN.
- [ ] Activate 1Password company account (invite sent to corporate email).

## Day 2

### Access Provisioning [IT]
- [ ] Grant access to role-specific systems (ERP, CRM, GitHub org, etc.).
- [ ] Add to relevant SharePoint sites and OneDrive shared folders.
- [ ] Set up Jira/Linear account if applicable.

### Employee Actions [Employee]
- [ ] Complete IT Security Awareness training (link sent via email — mandatory within 7 days).
- [ ] Review and acknowledge the Acceptable Use Policy.
- [ ] Set up OneDrive sync on the laptop.
- [ ] Test VPN connection from outside the office network.

## Day 3

### Verification [IT]
- [ ] Confirm all software is licensed and activated.
- [ ] Verify CrowdStrike agent is reporting to the management console.
- [ ] Confirm device backup/MDM enrolment is active.

### Employee Actions [Employee]
- [ ] Raise any access issues via `https://itportal.internal/helpdesk`.
- [ ] Confirm receipt of hardware accessories (keyboard, mouse, monitor, etc.).
- [ ] Schedule 15-minute IT orientation call if needed (optional).

## IT Contacts
- Helpdesk: ext. 1001 | `helpdesk@company.com`
- IT Portal: `https://itportal.internal`
- Emergency (P1 only): `+91 98xxx xxxxx` (24/7 on-call)
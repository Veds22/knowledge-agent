# Network Access Policy

## Overview
Network access is granted based on role and employment status. All access is logged and monitored.

## Network Segments

### Corporate Network (Wired)
- Full access to internal systems and internet.
- Available in all office locations.
- Requires corporate device with CrowdStrike installed.

### Corporate WiFi (WPA3-Enterprise)
- SSID: `CORP-INTERNAL`
- Authenticated via your Active Directory credentials.
- Same access level as wired corporate network.
- Available in all office floors and meeting rooms.

### Guest WiFi
- SSID: `COMPANY-GUEST`
- Password rotated weekly — obtain from IT Helpdesk or reception.
- Internet access only — no access to internal systems.
- Use for personal devices or client/visitor devices.

### Developer Network
- SSID: `DEV-SANDBOX`
- Isolated sandbox environment for development and testing.
- No access to production systems from this network.
- Available to Engineering team only.

## Remote Access
- All remote access to internal systems requires VPN (Cisco AnyConnect).
- Direct RDP/SSH to internal servers from outside the network is not permitted.
- See VPN Setup Guide for connection instructions.

## Access Request Process
1. Submit request at `https://itportal.internal/network-access`.
2. Specify: resource needed, duration, business justification.
3. Manager approval required.
4. IT provisions access within 1 business day.

## Prohibited Activities on Corporate Network
- Port scanning or network enumeration.
- Running personal servers or hosting services.
- Bypassing network controls using tunnelling or proxies.
- Accessing streaming services that consume excessive bandwidth during business hours.

## Monitoring
All network traffic is logged. Anomalous activity triggers automatic alerts to the Security team.
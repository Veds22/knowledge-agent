# Software Installation Policy

## Overview
Only approved software may be installed on company devices. Unauthorised software installations are a violation of the Acceptable Use Policy.

## Approved Software Categories
- **Productivity:** Microsoft 365 suite, Slack, Zoom, Notion.
- **Development:** VS Code, JetBrains IDEs, Docker Desktop, Git, Postman.
- **Security:** Cisco AnyConnect, CrowdStrike Falcon, 1Password (company licence).
- **Design:** Figma, Adobe Creative Cloud (licensed users only).

## How to Request New Software
1. Submit a request at `https://itportal.internal/software-request`.
2. Include: software name, version, business justification, and manager approval.
3. IT Security reviews the request within 2 business days.
4. Approved software is deployed via SCCM (Windows) or JAMF (macOS) — no manual install required.

## Prohibited Software
- Peer-to-peer file sharing applications (BitTorrent, LimeWire).
- Unauthorised remote access tools (TeamViewer personal, AnyDesk free).
- Cryptocurrency mining software.
- Personal VPN clients while on corporate network.
- Cracked or unlicensed software of any kind.

## Developer Exceptions
Developers may install open-source CLI tools and libraries within their local development environment without prior approval, provided:
- The tool is open-source with a permissive licence (MIT, Apache 2.0, BSD).
- It is not exposed as a network service.
- It does not require elevated/root access outside the dev environment.

Exceptions do not apply to GUI applications or system-level tools.

## Enforcement
Endpoint monitoring (CrowdStrike) scans all devices continuously. Detected unauthorised software triggers an automatic alert to IT Security. Repeated violations may result in disciplinary action.
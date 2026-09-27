# VPN Setup Guide

## Overview
The company uses Cisco AnyConnect for secure remote access. All remote work requires an active VPN connection.

## Installation

### Windows
1. Download the Cisco AnyConnect installer from the IT portal at `https://itportal.internal/vpn`.
2. Run the installer as Administrator.
3. Accept the license agreement and complete the installation.
4. Restart your machine after installation.

### macOS
1. Download the macOS package from `https://itportal.internal/vpn`.
2. Open the `.dmg` file and run the installer.
3. Grant the required system extensions when prompted under System Preferences > Security & Privacy.
4. Restart your machine.

### Linux
1. Install via terminal: `sudo apt install openconnect network-manager-openconnect`.
2. Connect using: `sudo openconnect vpn.company.com`.

## Connecting to VPN
1. Open Cisco AnyConnect.
2. Enter the server address: `vpn.company.com`.
3. Click Connect.
4. Enter your corporate email and Active Directory password.
5. Complete the MFA prompt (Microsoft Authenticator or SMS).

## Troubleshooting

### VPN keeps disconnecting
- Check your internet connection stability.
- Reconnect to a 5GHz WiFi band rather than 2.4GHz.
- Set the VPN reconnect timeout to 60 seconds under Preferences > Connection.
- If using a home router, disable SPI firewall temporarily to test.

### Cannot connect — Authentication failed
- Ensure you are using your corporate email (not personal).
- Reset your Active Directory password at `https://passwordreset.internal`.
- Contact IT if MFA is not working: raise a ticket or call ext. 1001.

### Connected but cannot reach internal resources
- Disconnect and reconnect the VPN.
- Flush DNS: Windows: `ipconfig /flushdns` | macOS: `sudo dscacheutil -flushcache`.
- Ensure split tunneling is disabled — check with IT if unsure.

## VPN Policy
- VPN is mandatory for accessing any internal system remotely.
- Sessions automatically expire after 8 hours of inactivity.
- Simultaneous connections from more than one device are not permitted.
- Using a personal VPN while connected to the corporate VPN is prohibited.
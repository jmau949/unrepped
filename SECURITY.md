# Security

## Reporting

If you find a vulnerability, open a private security advisory on the GitHub repository
("Security" tab → "Report a vulnerability") rather than a public issue. Expect an
acknowledgement within a week; this is a volunteer-maintained personal tool.

## Threat model, in one paragraph

The app is designed to run on one machine on a home network and be reached only from
devices on that LAN. It has **no authentication**, because it assumes the network
boundary is the boundary: `hb serve` binds `0.0.0.0` so phones and tablets on the same
Wi-Fi can open it, and the Windows setup script scopes the firewall rule to the local
subnet on Private-profile networks only (`ops/windows-lan.ps1`). Do not port-forward it,
put it behind a public reverse proxy, or run it on a shared network without adding your
own authentication layer first. The database holds scraped listing data, your tour
notes, and your buyer profile (cash, down payment); treat it as personal data.

The Tailscale setup keeps the same rule with a different boundary: the tailnet decides who
reaches the app, and `tailscale serve` gives it HTTPS. Sharing the machine shares the whole
no-login app, favorites and buyer profile included.

- **On your own computer** (`docs/11` §2c) the app runs as you, beside your files, and under
  Tailscale's default policy someone you share the computer with can reach every port on it:
  limit `autogroup:shared` to port 443 before sharing (the snippet is in `docs/11` §2c).
- **In a VM or on an alternate machine** (`docs/16`, optional extras) the app has its own
  host: it listens only behind `tailscale serve`, the host firewall admits only `tailscale0`
  and blocks outbound traffic to the LAN, and the tailnet policy grants port 443 alone, so a
  compromise of the app stays on that host.

## Secrets

API keys live in `.env` (gitignored; template in `.env.example`). Nothing in the repo
or the database contains a key, and the test suite never touches the network.

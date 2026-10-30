# 16 — Optional extras for the Tailscale setup: a VM, an alternate machine, or both

The Tailscale setup runs the app on your own computer (`11` §2c). Two independent extras build
on it, and this document covers both:

| Extra | What it gives you | Where it runs |
|---|---|---|
| **A VM** | the app is isolated from your computer's files and your home network: a compromise of the app stays inside the VM | on your own computer (Hyper-V, VirtualBox, UTM) or on an alternate machine |
| **An alternate machine** | the app keeps running, scans and alerts on time, while your computer is off | any always-on x86 machine at home, the app installed directly or in a VM |

Use either one or both. Either way the app runs on its own Ubuntu Server host — the VM, or the
alternate machine — reached from any of your devices, anywhere, over Tailscale with a real
HTTPS certificate; nothing is opened on the router, nothing is exposed to the internet, and
the Field page (`08` §11) works at the open house itself. The numbered sections work on any
Ubuntu Server host (x86 recommended; untested on ARM, where the multi-GB Redfin CSV crunch is
the worry). **Appendix A** is the reference build that uses both extras: Proxmox VE on a small
x86 PC with the app in one Ubuntu VM, which adds the hypervisor's per-VM firewall and whole-VM
backups.

**A VM on your own computer.** Create an Ubuntu Server VM with 4 vCPUs, 8 GB RAM and a
~150 GB dynamically sized disk, then follow §4 onward inside it. The machine items in §3
(Ethernet, USB stick, monitor) and the fixed LAN address in §4.1 do not apply (the VM is
reached by its Tailscale name), and §4.4's outbound rules still keep it off your computer and
the rest of the LAN; with NAT networking, `<router-ip>` there is the VM's gateway
(`ip route`). It sleeps and wakes with your computer, so scans and
alerts catch up when it wakes, exactly as without the VM. Deploys go to the VM by its
Tailscale name (`DEPLOY = server`, `11` §2b).

`docs/11` §2b is the part the repo implements (the systemd units, the sudoers line, the deploy
script); this document is the walk-through from a blank box to the first deploy, and what to do
afterwards.

The `__` blanks stay blank in this file, which is committed: record your own values in
`home-server.local.md` beside it at the repo root (gitignored; `ops/deploy-server.sh` never
ships it). Secrets go in a password manager, never in either file or the repo.

## 1. What this setup gives you

- The app runs 24/7 on the server, not on the machine you develop on.
- It starts on its own after a reboot or power loss, with no login or manual step.
- No surprise downtime from automatic OS updates or restarts.
- The scheduled pipelines (daily, listing scan, alerts) keep running on schedule.
- Scrapers leave from your home connection, so listing sites see a residential IP.
- Alerts reach your phone; the Windows `toast` channel is not needed.
- Any existing data moves over intact: the database, the photos and the raw cache (§8).
- The data is backed up, and a restore has been tested (§9).
- Room for the data to keep growing.
- The full app from your phone away from home, on cellular, over an encrypted connection.
- Only devices on your tailnet reach it, or ones you share it with: nothing public, no router
  ports open.
- The server cannot reach the rest of your network (§4.4 on any host, plus A.3 step 7 at
  the hypervisor for a VM; §5 step 3 on the tailnet).
- No secrets in the repo.
- Deploying a code change stays one command.
- Low ongoing maintenance (§10).

§11 traces each of these to the step that provides it.

## 2. The stack

| Layer | Choice | Why this one |
|---|---|---|
| Host | any x86 Ubuntu Server LTS host: bare metal or a VM. The reference build (Appendix A) is Proxmox VE on a small x86 PC with the app in one VM | one small box that never reboots on its own; a hypervisor adds a hard boundary, a stateful firewall per VM, scheduled whole-VM backups with retention, and room for more services later, each isolated the same way |
| App host `hb` | Ubuntu Server LTS; 2 vCPU / 4 cores, 8 GB RAM; 40 GB for the OS and the database; optionally a second disk or partition (~240 GB) for the photos and the raw cache, excluded from backups (§4.2) | with a second disk everything that grows lives on it, so a host backup holds only the OS and the database and stays a few GB a copy for good; the photos have no backup (a listing's photos can be fetched again only while it is live), and the raw cache is re-downloadable and bounded by `RAW_KEEP_DAYS=90` (§12) |
| App runtime | `uv` + one systemd service + three hourly systemd timers | the three mirror the Windows tasks and `ops/crontab.txt`; no Docker layer on a host that is already the boundary |
| Remote access | Tailscale on the host; `tailscale serve` terminates HTTPS with a Let's Encrypt cert | no router ports; directional device ACLs; real certificate on the phone; no exit node, so scrapers still leave from home |
| Deploy | `make deploy` with `DEPLOY = server` from your development machine: build the SPA locally, stream the tree over Tailscale SSH, sync, restart, poll health | one command; deploys the working tree |
| Local backup | whatever the host offers (§9): a nightly whole-VM backup on a hypervisor (the reference build keeps the last 7 nights plus 1 monthly with Proxmox vzdump, A.4), or a nightly copy of the database and photos off the box | whole-VM restore to a new VM ID is the easiest restore test; with the photos and the raw cache on an excluded second disk a copy is roughly 4 GB and a set of at most 8 copies stays under about 35 GB |
| Offsite backup | none by default | everything, the local backup set included, is on the one drive: a dead drive, fire or theft loses the data (§13) |
| Alerts | the app's `pushover` channel, alone, to the phone (`email` works the same way, `11` §2a); a hypervisor can notify through Pushover too | no mail credential on the server, and a leaked Pushover token can only page you; no external uptime monitor, so a stopped server shows up in the monthly check (§10) |

## 3. What you need

### Hardware
- [ ] An always-on box with 4 cores, 8 GB RAM or more and a ~500 GB SSD, or a VM with the
      same (the reference build, A.1: a fanless Intel N150 small-form-factor PC, 16 GB, 512 GB). For a VM
      host, virtualization (Intel VT-x / AMD-V) must be enabled in firmware. Record yours:
      RAM `__` GB, disk `__` GB.
- [ ] Disk budget: the app settles near 125 GB as the raw cache fills to its 90-day retention
      (§4.2), plus 1–2 GB of photos a month; a 500 GB drive runs it for years with room for a
      local backup set.
- [ ] Ethernet cable from the box to the router. Wifi is never used: a wireless client cannot
      carry a VM bridge, and the data move (§8) wants a wire anyway.
- [ ] One USB stick, 8 GB or more, written with the Ubuntu Server installer (or, for the
      reference build, the Proxmox installer; the Ubuntu ISO is then uploaded through the
      Proxmox UI, A.3).
- [ ] Monitor and keyboard for the install. Headless afterwards.

### Downloads on your computer
- [ ] Ubuntu Server LTS ISO (24.04 or 26.04; `uv` brings its own Python either way)
- [ ] Rufus (x64) or balenaEtcher to write the ISO to the stick
- [ ] Tailscale for your computer, the Tailscale app on the phone

### Accounts
- [ ] Tailscale, free Personal plan
- [ ] Pushover (pushover.net), optional: one account (a one-time purchase per phone platform
      after the trial), the phone app, and an application named `hb`. Record the user key and
      the app token. With Pushover no mail account is involved anywhere; `email` (`11` §2a) is
      the alternative.
- [ ] Router admin: a DHCP reservation for the server's fixed address (§4.1), made before it
      is typed into the installer. The address is set by hand on the machine, and the router
      does not know that: without a reservation it can lend the same address to a phone or a
      guest, and the server drops off the network while both claim it. (A hypervisor host
      needs its own reservation too, A.2.)

### Record these (in `home-server.local.md`)
- Server LAN IP `__`, user `hb` password; LAN subnet `__`, router IP `__`, your computer's
  LAN IP `__` (the addresses in §4.4 and A.3)
- Tailnet name `__.ts.net`, so the app URL is `https://hb.__.ts.net`
- The Pushover user key and the `hb` app token
- The reference build adds the hypervisor's own values (A.1, A.2)

## 4. Prepare the host

### 4.1 Install Ubuntu Server
Minimal install; user `hb`; install OpenSSH server; no extra snaps. Network: the interface set
to a static IPv4 address on the LAN subnet, gateway and DNS = the router, after reserving that
address on the router for the machine's MAC (§3 Accounts; a VM's MAC is shown by the
hypervisor, A.3). Afterwards:
```
sudo apt update && sudo apt install -y ufw curl git sqlite3
sudo timedatectl set-timezone <the timezone in geography.toml>   # e.g. America/Chicago
```
The timezone matters: `--catch-up` reads the geography's zone from `geography.toml` on its
own, but log timestamps and `systemctl list-timers` are wall-clock on this host, and Ubuntu
Server installs as UTC unless told otherwise.

The machine's hostname is what `tailscale up` registers it under (§5), and the docs and the
deploy script's default `hb@hb` assume it is `hb`: name it `hb` at install, rename it later in
the Tailscale admin console, or set `HB_SSH` (§7).

### 4.2 Data layout
Everything under `/srv/hb`: the tree at `/srv/hb/app`, the data at `/srv/hb/data`
(`DATA_DIR`); the app derives `raw/`, `photos/` and `backups/` under it.

One disk:
```
sudo mkdir -p /srv/hb/app /srv/hb/data
sudo chown -R hb:hb /srv/hb
```

With a second disk (the reference build: a 240 GB disk the host backup skips), the photos and
the raw cache go on it, bind-mounted into the data folder so the app sees one tree:
```
sudo mkdir -p /srv/hb/bulk /srv/hb/data/raw /srv/hb/data/photos /srv/hb/app
sudo mkfs.ext4 -L hb-bulk /dev/sdb
printf '%s\n' \
  "LABEL=hb-bulk /srv/hb/bulk ext4 defaults,nofail 0 2" \
  "/srv/hb/bulk/raw /srv/hb/data/raw none bind,nofail 0 0" \
  "/srv/hb/bulk/photos /srv/hb/data/photos none bind,nofail 0 0" | sudo tee -a /etc/fstab
sudo mount /srv/hb/bulk && sudo mkdir -p /srv/hb/bulk/raw /srv/hb/bulk/photos && sudo mount -a
sudo chown -R hb:hb /srv/hb
```
Bind mounts rather than symlinks, so `data/raw` and `data/photos` are plain directories to
every tool that walks the tree. Size it from the growth: the cache grows about 8 GB a week
(three ~5.5 GB Redfin releases a fortnight plus ~210 MB of Zillow a day), `RAW_KEEP_DAYS=90`
(§12) keeps thirteen weeks of it, so it settles near 105 GB, and the photos add about 1–2 GB a
month beside it.

The units that write data (`hb.service`, `hb-daily.service`, `hb-scan.service`) carry
`RequiresMountsFor=/srv/hb/data/photos /srv/hb/data/raw`. With a second disk that means: if
it is missing they stay down rather than fill the empty mountpoints on the system disk.
Without one the two paths are plain directories, the requirement resolves to the root
filesystem's mount, and the units start normally; nothing needs editing.

### 4.3 Unattended security updates, no auto-reboot
`sudo apt install unattended-upgrades`, then in `/etc/apt/apt.conf.d/50unattended-upgrades`
leave `Automatic-Reboot "false"`. A new kernel waits for your next planned reboot (§10).

### 4.4 Firewall on the host (ufw)
```
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0
sudo ufw allow from <lan-subnet> to any port 22 proto tcp   # bootstrap only; remove in §5 step 6
# Outbound: the router for DNS and DHCP only, then nothing else on the LAN. ufw takes the
# first matching rule, so the two allows come before the denies.
sudo ufw allow out to <router-ip> port 53
sudo ufw allow out to <router-ip> port 67 proto udp
sudo ufw deny out to 10.0.0.0/8
sudo ufw deny out to 172.16.0.0/12
sudo ufw deny out to 192.168.0.0/16
sudo ufw deny out to 169.254.0.0/16
sudo ufw enable
```
The denies keep a compromised app off your other devices; the internet (what the scrapers
need) and the tailnet are unaffected. These rules are IPv4 only, and the router also hands
every device a global IPv6 address in one shared /64, so the LAN interface runs with IPv6
off (`<lan-if>` is its name in `ip link`, e.g. `enp1s0`; `tailscale0` keeps its own IPv6):
```
echo 'net.ipv6.conf.<lan-if>.disable_ipv6 = 1' | sudo tee /etc/sysctl.d/60-hb-no-lan-ipv6.conf
sudo sysctl --system >/dev/null
```
After §5 the host is reachable only over the tailnet. A VM gets a second, outer copy of these
rules at the hypervisor (A.3 step 7), which holds even if the VM itself is compromised.

## 5. Tailscale

1. On the host: `curl -fsSL https://tailscale.com/install.sh | sh`, then
   `sudo tailscale up --ssh`. Open the printed URL on your computer to authenticate.
2. Admin console → DNS: enable MagicDNS and HTTPS certificates. Machines → `hb`: disable key
   expiry (the tag comes after step 3).
3. **ACL policy** (Access controls). Nothing grants `tag:hb` as a source, so the server can
   initiate nothing on the tailnet, which is what keeps your other machines unreachable from
   it:
   ```json
   {
     "tagOwners": { "tag:hb": ["autogroup:admin"] },
     "acls": [
       { "action": "accept", "src": ["autogroup:member", "autogroup:shared"], "dst": ["tag:hb:443"] },
       { "action": "accept", "src": ["you@example.com"], "dst": ["tag:hb:22"] }
     ],
     "ssh": [
       { "action": "accept", "src": ["you@example.com"], "dst": ["tag:hb"], "users": ["hb"] }
     ]
   }
   ```
   `you@example.com` is your own Tailscale login, in both places. The web app (443) is open to
   your tailnet's members and to `autogroup:shared`, anyone who accepted a share of the
   machine; SSH is yours alone, because the app has no logins of its own but a shell as `hb`
   reads `.env` and owns the data.

   **Letting someone else view the app.** Share the machine rather than inviting them as a
   member: Machines → `hb` → ⋯ → Share… → their email, or Copy share link. Only an Owner,
   Admin or IT admin can share. The recipient accepts it while logged in to their own
   Tailscale, and `hb` appears in their tailnet alone: they see none of your other machines,
   take no user seat, and fall under no rule written for `autogroup:member`. Sharing strips
   the tag on their side, and a share can only be accepted by a user, never by a tagged
   machine. They must use the full name, `https://hb.<tailnet>.ts.net`; the short name `hb`
   does not resolve for a shared machine. Their own tailnet policy must also let their device
   reach it (the default policy does). The app has no logins, so they can change everything a
   member can: favorites, notes, the Tracker, the buyer profile. Revoke from the same Share…
   dialog. If Share… is ever unavailable for the tagged machine, invite them under Users
   instead: the rules above still hold them to port 443.
   Port 22 is in the `acls` rule because Tailscale SSH needs network access to the port as
   well as the `ssh` rule. Save the policy, then tag the machine: Machines → `hb` → ⋯ → Edit ACL tags… → `tag:hb`. A
   tag can only be applied once `tagOwners` defines it.
4. **HTTPS front door**: `sudo tailscale serve --bg 18800`. The app is now
   `https://hb.<tailnet>.ts.net` with a real certificate, proxied to the local plain-HTTP
   listener. Port 18800 itself is not in the ACL, so it is reachable only through the proxy.
5. **Phone**: install Tailscale, sign in, open the URL, add it to the home screen.
   **Your computer**: install Tailscale; `ssh hb@hb` works with no keys, via Tailscale SSH.
6. Remove the bootstrap SSH rule from §4.4 (and, on the reference build, the one from A.3
   step 7). From here on the host is reachable only over the tailnet.

## 6. Install the app

1. On the host, as `hb`: `curl -LsSf https://astral.sh/uv/install.sh | sh`. No Node on the
   server; the SPA is built on your development machine and shipped as `frontend/dist`.
2. First copy of the tree from your checkout (repo root; Git Bash on Windows, any POSIX shell
   elsewhere):
   ```
   (cd frontend && npm run build)
   tar --exclude=node_modules --exclude=.venv --exclude=__pycache__ \
       --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.git --exclude=.env \
       --exclude=./backend/data --exclude=./data --exclude=./.claude \
       --exclude=./home-server.local.md --exclude=./CLAUDE.local.md --exclude=./config.mk -cf - . \
     | ssh hb@hb 'tar -xf - -C /srv/hb/app'
   ```
   These are the excludes `ops/deploy-server.sh` uses (§7). `.env` is excluded on purpose:
   the server's copy (step 3) differs from your checkout's and must survive every deploy. A
   repo-root `geography.toml` is not excluded: it holds no secret, the two copies must match,
   and shipping it with the tree is how an edit on your computer reaches the server. Without
   one, both run the packaged example geography. The data excludes are anchored so only the
   two data folders are skipped. `.gitattributes` keeps `*.sh` and `ops/linux/*` LF in a
   Windows working tree, because the tar ships the working tree byte for byte and bash,
   systemd and sudo reject CRLF.
3. `/srv/hb/app/.env` on the server, written by hand from your checkout's `.env` (the tar
   never carries it):
   ```
   DATA_DIR=/srv/hb/data
   HB_HTTP_PORT=18800
   APP_BASE_URL=https://hb.<tailnet>.ts.net
   ALERT_CHANNELS=pushover
   PUSHOVER_TOKEN=__
   PUSHOVER_USER=__
   HB_SERVE_SCHEDULER=false
   ```
   plus the API keys as they are in your checkout; no `SMTP_*` lines unless `email` is your
   channel. `HB_SERVE_SCHEDULER=false` keeps the hourly check inside `hb serve` off because
   the timers run the jobs; `hb.service` sets it too, so the `.env` line is belt and braces; then `chmod 600 /srv/hb/app/.env` (every deploy moves the file, so the mode
   sticks). `ALERT_CHANNELS` is `pushover` alone, not `pushover,log`: delivery marks an alert
   delivered as soon as any channel succeeds, and `log` always succeeds, so with both enabled
   a Pushover outage would stamp every alert delivered and never retry it. With `pushover`
   alone a failed push leaves the row for the next :30 run. The token is the only
   notification secret on the server and it can do one thing, send pushes to your user key;
   if the server is ever compromised, regenerate it on the Pushover dashboard.
4. `sudo bash /srv/hb/app/ops/linux/install.sh` (through `bash`: a tar from Windows does not
   carry the executable bit) installs the units below, the sudoers line that lets `hb` stop,
   start and restart `hb.service` without a password (`visudo` checks it before it goes live),
   and enables `hb.service`. The three timers are enabled separately: on a fresh install right
   after step 6; when moving data from a local instance, only at §8 step 5, since a pipeline
   run before then writes into the fresh database that the move replaces. Re-run it after any
   change under `ops/linux/`.
5. The units from step 4 (`ops/linux/`; the table is in `11` §2b):
   - `hb.service`: `uv run --no-sync hb serve`, `Restart=always`, after network-online, with `HB_SERVE_SCHEDULER=false` (the timers run the jobs, so the hourly check inside `hb serve` stays off).
     Every unit that writes data carries `RequiresMountsFor=` the two data paths (§4.2): with
     a second disk missing they stay down instead of filling the empty mountpoints; without a
     second disk they start normally.
   - `hb-daily.timer` hourly at :00 → `hb pipeline daily --catch-up`
   - `hb-scan.timer` hourly at :00 → `hb pipeline listing-scan --catch-up`
   - `hb-alerts.timer` hourly at :30 → `hb alerts send`
   All timers carry `Persistent=true`; `--catch-up` already makes a missed slot run on the
   next hour, exactly as on Windows.
6. `cd /srv/hb/app/backend && uv sync && sudo systemctl start hb`, then
   `curl -s localhost:18800/api/ops/health` must report a migrated DB. (`uv` is on the
   `PATH` from the next login after step 1; the units call it as `/home/hb/.local/bin/uv`.)
   Open `https://hb.<tailnet>.ts.net` on the phone. On a fresh install, enable the schedules
   now: `sudo systemctl enable --now hb-daily.timer hb-scan.timer hb-alerts.timer`; then do
   the first data load by hand on the server, which has no `make` — in `/srv/hb/app/backend`,
   `uv run --no-sync hb pipeline hazards-fetch --if-missing`, then `uv run --no-sync hb
   pipeline daily`, then `uv run --no-sync hb pipeline listing-scan` (the three steps of
   `make load`, `11` §1; allow about an hour for the first run).

## 7. Deploy from your development machine

With the server answering (§6 step 6), every later code change ships with one command from
the repo root on your development machine (Git Bash on Windows; any POSIX shell with `tar`,
`ssh` and `curl`):
```
cp config.mk.example config.mk    # once; then set DEPLOY = server
make deploy
```
`config.mk` is gitignored and per checkout. `HB_SSH = user@host` there (or in the
environment) changes the SSH target from the default `hb@hb`, the MagicDNS name of a machine
called `hb` reached as its user `hb`; the Makefile exports it to `ops/deploy-server.sh`.

The script builds the SPA locally, streams the working tree over Tailscale SSH into a fresh
`/srv/hb/app.new` with the excludes of §6 step 2 (so the server's `.env` is never touched and
the freshly built `frontend/dist` rides along), moves the server's `.env` and `backend/.venv`
into it, swaps it into place so a file deleted or renamed in your checkout does not linger on
the server (a stale migration file would give alembic two heads), runs `uv sync` and
`sudo -n systemctl restart hb`, then reads `APP_BASE_URL` from the server's `.env` and polls
`<APP_BASE_URL>/api/ops/health` through the `tailscale serve` front door for up to 20 s,
failing if nothing answers — the same gate as `deploy-windows`. The numbered steps are in
`11` §2b → Deploy. It refuses to run if the server has no `/srv/hb/app/.env` yet. On Linux a
running server does not lock the venv, so `uv sync` under it is safe.

If your conventions differ from the repo's (another user than `hb`, another root than
`/srv/hb`, another unit name), the places to change are the four `ops/linux/*.service` files
(`User=`, `Group=`, `WorkingDirectory=`, `ExecStart=`, `RequiresMountsFor=`),
`ops/linux/hb.sudoers`, and the `/srv/hb` paths and `systemctl restart hb` in
`ops/deploy-server.sh`; `HB_SSH` covers the host and login.

## 8. Move data from an existing local instance (optional)

Precious set: the database and the photos; the raw cache moves too (step 4).

1. On the local machine: stop everything that writes — on Windows `make schedule-remove`
   (unregisters "HB Daily Pipelines", "HB Listing Scan" and "HB Alerts Send") plus, in an
   elevated PowerShell, `Stop-ScheduledTask -TaskName "HB API Server"; Disable-ScheduledTask
   -TaskName "HB API Server"` (stopping alone does not keep the logon trigger from starting it
   again); on macOS/Linux `make schedule-remove` (the launchd agents, systemd `--user` timers or crontab
   block that `make schedule` wrote) plus whatever runs `hb serve` — so nothing writes during
   the copy.
2. `cd backend && uv run --no-sync hb db backup` writes a clean single-file copy to
   `backend/data/backups/hb-<today>.sqlite3`. Never copy the live `hb.sqlite3` with its
   `-wal` and `-shm` files.
3. Tidy first: delete or move aside any hand-made copies under `backend/data/` (`*.bak-*`,
   stray `-shm`/`-wal` files) and anything in `backups/` the 14-day rule never prunes; they
   are not part of the set. Then check that `tailscale status` on your computer lists `hb` as
   `direct`, not `relay`: tens of GB through a relay takes hours. Stream it all over the
   tailnet from the repo root (Git Bash on Windows):
   ```
   tar -C backend/data -cf - photos backups raw | ssh hb@hb 'tar -xf - -C /srv/hb/data'
   ssh hb@hb 'sudo -n systemctl stop hb && cd /srv/hb/data \
     && rm -f hb.sqlite3 hb.sqlite3-wal hb.sqlite3-shm \
     && cp backups/hb-<today>.sqlite3 hb.sqlite3 && sudo -n systemctl start hb'
   ```
   The server is stopped and the fresh database §6 step 6 created is removed with its `-wal`
   and `-shm` before the copy goes in: SQLite would otherwise replay the old `-wal` into the
   copied file and corrupt it. A few months of use is tens of GB, most of it the raw cache:
   tens of minutes on a wired LAN with a direct path. `raw/` and `photos/` land on the second
   disk, if there is one, through the bind mounts of §4.2.
4. The whole raw cache moves, not just the latest folders: one of its folders is not
   re-fetched by the daily run. The undated `raw/hazards/` is read by the daily `hazards` job,
   which fails every day until the files exist (`hb pipeline hazards-fetch` is standalone).
   Every other folder is dated — the Redfin and Zillow downloads, and the CAASPP files the
   standalone `school-ratings` job fetches into `raw/caaspp/<date>/` — and re-downloadable;
   `RAW_KEEP_DAYS=90` (§12) deletes each one 90 days after its download, at the tail of the
   daily job.
5. Start the schedules:
   `sudo systemctl enable --now hb-daily.timer hb-scan.timer hb-alerts.timer`
   (`systemctl list-timers 'hb-*'` shows the next run of each). Open the app on the phone;
   check the Data Log page; run `uv run --no-sync hb pipeline listing-scan --catch-up` once
   by hand on the server (in `/srv/hb/app/backend`) to prove the scrapers work from there.
6. Leave the local schedules off for good. An accidental overlap is harmless: alert dedup
   keys absorb a double scan.

## 9. Backups and the restore test

**What matters.** The database and the photos. The raw cache is re-downloadable except one
undated folder a job reads: `raw/hazards/` (the daily `hazards` job fails every day until
the files exist; `hb pipeline hazards-fetch` is standalone). The CAASPP files for the
standalone `school-ratings` job sit in dated `raw/caaspp/<date>/` folders like every other
download, pruned by `RAW_KEEP_DAYS` and fetched again by the next run. The photos have no
other source: a listing's photos can be fetched again only while it is live.

**On the host.** The tail of the daily job already writes a clean single-file copy of the
database to `/srv/hb/data/backups/` every night and keeps 14 days (`11` §2 step 3); those
copies sit on the same disk as the live file. A copy off the box is yours to arrange, by one
of:
- a whole-VM backup on a hypervisor (the reference build: nightly Proxmox vzdump to the host's
  own storage, 7 nights plus 1 monthly, with the second disk excluded so a copy stays about
  4 GB; A.4), or
- `rsync` or `restic` of `/srv/hb/data` minus `raw/` (`backups/` and `photos/`, which is all
  that needs to leave the box) to another machine or a bucket, nightly from the host's cron
  or a systemd timer.

Never copy the live `hb.sqlite3` on its own without its `-wal`/`-shm`; the nightly file in
`backups/` is the one to take.

**Restore test, now and then quarterly.** Restore to an isolated copy — a new VM ID, a spare
box, a container — with networking off, because the copy carries the live server's Tailscale
identity and timers and must never come up on the network. In it run
`curl -s localhost:18800/api/ops/health` and
`sqlite3 /srv/hb/data/hb.sqlite3 'PRAGMA integrity_check'`; both must be clean. `photos/`
and `raw/` may be empty in a copy that excludes the second disk; that is expected. Then
destroy the copy. Record each passed test in `home-server.local.md`.

## 10. Running it

- Your development machine no longer serves the app. If it ran the Windows always-on setup,
  the pipeline tasks stay unregistered and "HB API Server" disabled for good (§8 step 1), and
  `make deploy-windows` is not run there again;
  its `config.mk` says `DEPLOY = server`, so shipping is: commit, `make deploy`. The repo
  stays for development, verified with `make test`, `make build` and `make dev-api`.
- Phone: the home-screen shortcut to `https://hb.<tailnet>.ts.net`.
- You hear about trouble as pushes on the phone: the app's own `scan_failure` alert through
  its `pushover` channel, and the hypervisor when a backup fails, if yours notifies (A.2 step
  9). Nothing pushes when the server itself stops; the monthly check catches that.
- Monthly: `apt upgrade` and a planned reboot if a kernel is waiting (§4.3), the hypervisor's
  own updates if there is one, a glance at free disk space (`df -h /srv/hb`), and
  `systemctl --failed` (must list no `hb-*` unit).

## 11. How the requirements are met

| Requirement | How it is met |
|---|---|
| Runs 24/7 on the server, not your development machine | the host of §4 (a VM on Proxmox in A.3) |
| Starts after reboot or power loss, no login | firmware power-on policy (A.1 for the reference build) + the hypervisor's "start at boot" (A.3) + systemd units (§6) |
| No surprise downtime from updates | unattended-upgrades never reboots (§4.3); on the reference build, host updates are manual (A.2 step 5) |
| Pipelines keep their schedule | three hourly timers with `--catch-up` (§6 step 5), same slots as `ops/windows-tasks.ps1` |
| Scrapers run from home | the host egresses through the home router; no Tailscale exit node (§5) |
| Alerts reach your phone | `pushover` channel alone, so a failed push is retried (§6 step 3); every signal is a phone push, no mail account anywhere; a stopped server is caught by the monthly check (§10) |
| Data moves intact | DB from `hb db backup`; photos, backups and the whole raw cache by tar stream (§8) |
| Backed up, restore tested | a host-level copy (§9; vzdump with Pushover on failure in A.4); no offsite copy (§2); restore log in `home-server.local.md` |
| Room to grow | 40 GB + an optional second disk (§4.2); photos and raw cache outside the backups, so the backup set has a fixed size (§9); `RAW_KEEP_DAYS=90` (§12) |
| Phone access on cellular | Tailscale + `tailscale serve` (§5) |
| Only your devices; no public exposure; no router ports | tailnet ACL (§5 step 3): tailnet members, plus web-only access for anyone the machine is shared with; SSH only from your login; nothing listens on the LAN after §5 step 6; never port-forward |
| Encrypted phone connection | WireGuard tunnel plus HTTPS with a Let's Encrypt cert (§5 step 4) |
| Field app not required | not installed: the Field page (`/field`) is an ordinary page, used in the phone's browser over Tailscale HTTPS |
| Your other machines unreachable from the server | no ACL rule with `tag:hb` as source (§5 step 3); ufw default deny (§4.4); on a VM, hypervisor egress DROP to LAN ranges (A.3 step 7) |
| No secrets in the repo | `.env` lives only on the server (§6); `geography.toml` holds no secret, is gitignored, and ships with every deploy from the checkout (§6 step 2) |
| App compromise cannot reach host or neighbours | on the reference build: KVM boundary + Proxmox output rules dropping all RFC1918 (A.3 step 7, live only with the Datacenter switch of A.2 step 8) + ufw default deny (§4.4) |
| More services later, isolated the same way | on a hypervisor, a new VM or LXC per service, each with its own firewall section and tailnet tag |
| One-command deploy | `make deploy` with `DEPLOY = server`, run from your development machine (§7) |
| Low maintenance | monthly update pass (§10); everything else is scheduled |
| Return to stock | firmware Windows key (A.2 step 3) + clean reinstall (A.5), on the reference build |
| One codebase for both setups | §12: the server pieces are additive, and `config.mk` picks the deploy target per checkout, so a local-only user is unaffected |

## 12. What the repo implements

Everything lives on `main` beside the local setup; nothing here changes how a local-only
checkout runs. The server pieces:
- `ops/linux/hb.service`, `hb-daily.service` + `.timer`, `hb-scan.service` + `.timer`,
  `hb-alerts.service` + `.timer`, `hb.sudoers`, `install.sh` (`11` §2b)
- `ops/deploy-server.sh`: the build / tar / sync / restart / health-poll sequence of §7, with
  the excludes of §6 step 2 (`.env` above all) and the `app.new` swap
- `Makefile`: `deploy-server` beside `deploy-local` / `deploy-windows`, and `deploy:`
  dispatching to `deploy-$(DEPLOY)` from the gitignored `config.mk` (template
  `config.mk.example`), which also carries `HB_SSH`; with `DEPLOY` unset it fails with
  instructions
- `docs/11-deployment.md` §2b describing the above
- `.env.example`: the server values of §6 step 3 as comments
- `CLAUDE.md` "Running and deploying" and "Live DB": both keyed on `DEPLOY`, so an agent
  session in a server-driving checkout deploys to the server and reads its database over SSH
- `.gitattributes`: `*.sh` and `ops/linux/**` checked out LF (§6 step 2)
- The Field page (`frontend/src/pages/Field.tsx`, `08` §11, `13` §11), which this setup makes
  usable at the open house itself: the phone reaches the server over Tailscale, and each
  answer saves as you tap

Two settings this setup depends on, useful to every single-machine user too:
- A retention rule for the raw cache. `JobRunner` writes every download to a new dated folder
  under `data/raw/<source>/`; at about three 5.5 GB Redfin releases a fortnight and 210 MB of
  Zillow a day that is about 8 GB a week. `RAW_KEEP_DAYS` (`config.py`, `.env`, default 90)
  deletes dated folders older than N days at the tail of `hb pipeline daily` and by
  `hb prune-raw`. Unpruned, the cache outgrows any disk within months. Thirteen weeks at about
  8 GB a week is roughly 105 GB at steady state, which with the photos beside it is why the
  reference build's second disk is 240 GB.
- The `pushover` alert channel, so the server carries no mail credential (`send_pushover` in
  `alerts/channels.py`, `PUSHOVER_TOKEN` / `PUSHOVER_USER`).

## 13. Further hardening

- Tailscale on the hypervisor host as well, as its own tailnet node with its own ACL line,
  for managing it from away (A.2 step 10).
- An offsite copy of the data (none by default, §2): a cloud bucket or a second USB disk kept
  in another building; the `rsync`/`restic` option of §9 is the hook.

## Appendix A. The reference build: Proxmox VE on a small x86 PC

Proxmox VE on the box's one drive, installed straight over the Windows it shipped with and
with no image taken (return to stock is a clean Windows reinstall that activates from the key
in firmware, A.5); one Ubuntu Server VM (`hb`, ID 100) for the app, set up exactly as §4–§6
with the additions below; nightly Proxmox backups of the VM kept on the host.

### A.1 Hardware, firmware, and before the shipped OS is wiped

The reference build is a fanless small-form-factor PC (Intel N150, 4 cores; 16 GB on most configurations,
12 GB soldered on some; a 512 GB SSD) that shipped with Windows 11 Home. Its one drive carries
everything: Proxmox, the VM disks and the local backup set. Virtualization (Intel VT-x) must be
enabled in firmware.

Downloads on your computer, beyond §3: the Proxmox VE ISO; Rufus (x64) or balenaEtcher to
write it (Proxmox needs DD mode in Rufus). The Ubuntu ISO is uploaded through the Proxmox UI,
not written to a stick.

Record these too (in `home-server.local.md`): Windows edition `__` (step 1) and firmware key
`__` (A.2 step 3); Proxmox host IP `__`, root password, TOTP seed; the VM's LAN IP `__` (A.3
step 4). Both the host's and the VM's addresses get a DHCP reservation (§3 Accounts) before
each is typed into its installer.

No disk image is taken: the Windows key lives in firmware, so return to stock is a clean
reinstall (A.5), and nothing on the shipped disk is worth keeping.

1. **Read the edition without finishing setup.** Leave Wi-Fi and Ethernet disconnected. At any
   first-boot screen (region, Wi-Fi, …) press Shift+F10 (Fn+Shift+F10 on some keyboards) for
   a command prompt:
   ```
   reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" /v EditionID
   ```
   `Core` is Home, `Professional` is Pro. Turn it off from the same prompt with
   `shutdown /s /t 0`; do not finish setup. The firmware key is read later from the Proxmox
   host (A.2 step 3), where it needs no typing at this prompt.
2. **Firmware.** Tap Del at power-on (the vendor's AMI firmware):
   - Advanced → CPU Configuration → Intel VMX Virtualization = Enabled (it ships enabled).
   - State After G3 = **S0 State** (it ships S5), so the machine powers on when power returns.
   - Boot order and Secure Boot unchanged: F7 at power-on gives a one-time boot menu for the
     stick, and current Proxmox installs under Secure Boot.
   - Save and exit with F4.

### A.2 The Proxmox host

1. Write the Proxmox ISO to the stick with Rufus (partition scheme GPT, target UEFI; choose
   **DD Image mode** when it asks), connect Ethernet, and boot it with F7 at power-on.
2. Installer: target disk = the **512 GB SSD**; filesystem = ext4 with LVM-thin, and under its
   Advanced Options set `maxroot` to 110 (GB): the root volume is the `local` storage that
   holds the ISOs and the backup set of A.4, the installer allows it at most a quarter of the
   disk and its own default is smaller, and the rest of the disk becomes the `local-lvm` thin
   pool for the VM disks (280 GB of caps against roughly 340 GB of pool); country, keyboard,
   and timezone = the `timezone` in `geography.toml` (the backup schedule in A.4 is read on
   this clock); admin email = your address; management interface = the wired NIC; hostname as
   an FQDN, e.g. `pve.home.arpa`; a static IP, reserved on the router first (§3 Accounts) for
   the machine's wired MAC address; the router as gateway and DNS.
3. First login at `https://<host-ip>:8006` as `root`. Dismiss the subscription notice.
   Record the Windows firmware key from the host shell (Node → Shell):
   `cat /sys/firmware/acpi/tables/MSDM`; the key is the last 29 characters. If the file is
   missing, there is no embedded key and A.5 needs a purchased one.
4. **Repositories** (Node → Repositories): disable the enterprise entries, add the
   No-Subscription repository. Node → Updates → Refresh → Upgrade. Reboot once.
5. **Update policy**: updates are manual, from Node → Updates, roughly monthly. Nothing on
   the host reboots unattended. A new kernel waits for your next planned reboot.
6. **Two-factor** for `root`: Datacenter → Permissions → Two Factor → add TOTP.
7. **Backup storage**: nothing to add. `local` (the root volume sized in step 2, directory
   `/var/lib/vz`) already lists the content type "VZDump backup file"; A.4 points the backup
   job at it.
8. **Firewall master switch**: Datacenter → Firewall → Options → Firewall = Yes. Proxmox's
   firewall is completely off by default, and the per-VM rules in A.3 step 7 do nothing until
   this is on. Turning it on puts the host's input policy at DROP with built-in exceptions for
   the `management` IPSet, which is pre-filled with the local subnet, so the web UI on 8006
   and SSH on 22 stay reachable from your computer; confirm that from your computer while the
   monitor is still attached. Leave Host → Firewall → Options → nftables off: the default
   iptables backend accepts established connections before a VM's rules are consulted,
   which is what A.3 step 7 relies on, while the nftables backend evaluates VM rules even
   for connections already in the conntrack table.
9. **Notifications**: Datacenter → Notifications → add a **Webhook** target (PVE 8.3 and
   later) that POSTs to `https://api.pushover.net/1/messages.json` with the app token and
   user key stored as the target's secrets and `{{ title }}` / `{{ message }}` in the body
   (the Discord and Slack examples in the Proxmox notification docs show the templating);
   the default matcher then pushes every backup failure to the phone. No SMTP target.
10. **Exposure**: the web UI and SSH are reachable from the LAN only. Never port-forward 8006
    or 22. Optional later: install Tailscale on the host too for management from away, as its
    own tailnet node with its own ACL line.

### A.3 The app VM `hb`

1. Upload the Ubuntu ISO: `local` storage → ISO Images → Upload.
2. Create VM: ID `100`, name `hb`; the Ubuntu ISO; machine `q35`, BIOS `OVMF (UEFI)` with an
   EFI disk; SCSI controller `VirtIO SCSI single`; disk `scsi0` 40 GB on `local-lvm` with
   Discard on; CPU 2 cores, type `host`; memory 8192 MB; network `virtio` on `vmbr0` with
   the Firewall box ticked.
3. Hardware → Add → Hard Disk: `scsi1`, 240 GB, `local-lvm`, Discard on, **Backup unticked**.
   Options → Start at boot = Yes; QEMU Guest Agent = enabled.
4. Install Ubuntu Server as in §4.1. The VM's MAC for the router reservation is under `hb` →
   Hardware → Network Device. Add the guest agent to the apt line and enable it:
   ```
   sudo apt install -y qemu-guest-agent && sudo systemctl enable --now qemu-guest-agent
   ```
5. Data layout as in §4.2 with the second disk: `scsi1` appears as `/dev/sdb`. It is 240 GB
   because the cache grows about 8 GB a week and `RAW_KEEP_DAYS=90` keeps thirteen weeks of it
   (a cache that has been running for months settles at about 105 GB) and the photos add
   about 1.4 GB a month beside it.
6. §4.3 and §4.4 as written; the bootstrap rule in §4.4 pairs with the one in step 7 below,
   and both go in §5 step 6.
7. **Firewall at the Proxmox level** (VM 100 → Firewall), the isolation requirement. The
   firewall is stateful, so replies to connections the phone or your computer open still
   flow.
   - Options: Firewall = Yes; Input policy = DROP; Output policy = ACCEPT.
   - Input rules: ACCEPT UDP 41641 from anywhere (Tailscale direct connections); ACCEPT TCP 22
     from your computer's LAN IP (bootstrap only; remove in §5 step 6).
   - Output rules, in order: ACCEPT to the router IP on UDP/TCP 53, UDP 67 (the VM's DHCP
     lease renewals go to the router by unicast) and UDP 123; DROP to `10.0.0.0/8`,
     `172.16.0.0/12`, `192.168.0.0/16`; everything else falls through to ACCEPT.
   - Proxmox inserts each new rule at the top of the list, and rules are checked top to
     bottom, so add the three DROPs first and the ACCEPTs after them (or drag them into order).
   These rules are IPv4 only, and the router also hands every device a global IPv6 address
   in one shared /64, so the VM's LAN interface runs with IPv6 off (a prefix-based DROP would
   break whenever the ISP renumbers the prefix; Tailscale and the scrapers need only IPv4):
   ```
   echo 'net.ipv6.conf.ens18.disable_ipv6 = 1' | sudo tee /etc/sysctl.d/60-hb-no-lan-ipv6.conf
   sudo sysctl --system >/dev/null
   ```
   `ens18` is the VM's LAN interface (`ip link`); `tailscale0` keeps its own IPv6.
   The VM can now reach the internet and nothing on the home LAN, including the Proxmox host
   and your computer. None of this is in force until the Datacenter switch of A.2 step 8 is
   on; check with `pve-firewall status` on the host (it must say `enabled/running`).

### A.4 Backups: vzdump and the restore test

**Local, whole VM.** Datacenter → Backup → Add: storage `local`; schedule `03:00`
daily (host wall-clock, A.2 step 2); selection VM 100; mode Snapshot; compression ZSTD;
retention keep-daily 7, keep-monthly 1 (a week of nights plus the newest backup of an
earlier month); notify on failure. Disk 2 is excluded by its Backup flag, so each backup is
the OS plus the database and its nightly copies: roughly 4 GB compressed, and it stays that
size because everything that grows, the photos and the raw cache, is on disk 2. The set of
at most 8 copies is under about 35 GB on the 110 GB `local` volume (A.2 step 2); a glance at
its free space is on the monthly list (§10). This set is for a broken VM: a bad upgrade, a
wrong edit, a corrupted database. The photos are not in it and have no other backup, and
nothing here survives the drive itself.

**Restoring the live VM** (as opposed to the test below): restore the backup to a new ID,
say `101`, then hand it the live VM's disk 2, which no backup contains:
`qm move-disk 100 scsi1 --target-vmid 101 --target-disk scsi1`; confirm Backup is still
unticked on it, start 101, and destroy 100 once the app answers. Restoring over VM 100 in
place erases the current VM's disks, disk 2 included, which is why the restore goes to a
new ID.

**Restore test, now and then quarterly:**
1. Proxmox UI → `local` → Backups → latest → Restore → new VM ID `199`, storage
   `local-lvm`, "start after restore" off.
2. VM 199 → Hardware → Network Device → tick Disconnect. The restored VM carries the live
   VM's Tailscale identity and schedules; it must never come up with a network.
3. Start it, open the console, log in, run `curl -s localhost:18800/api/ops/health` and
   `sqlite3 /srv/hb/data/hb.sqlite3 'PRAGMA integrity_check'`. Both must be clean. `photos/`
   and `raw/` are empty here because disk 2 is not in the backup; that is expected.
4. Stop and destroy VM 199. Record the date in `home-server.local.md`.

### A.5 Return to stock

1. Stop the VM. The reinstall below replaces everything on the disk, the backup set included,
   so first copy the newest file in `/srv/hb/data/backups/` and the photos off the machine.
2. On your computer, Microsoft's Media Creation Tool writes Windows 11 install media to the
   stick. Boot it with F7; at "Which type of installation" choose Custom, delete every
   partition on the 512 GB disk, and install to the unallocated space.
3. Windows 11 Home installs and activates from the firmware key once online. Windows Update
   brings the drivers; the vendor's support site has the driver pack for anything left.
   Set State After G3 back to S5 if the machine should stay off after a power cut.

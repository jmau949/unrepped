#!/usr/bin/env bash
# Installs the home server's systemd units and sudoers line (docs/11 §2b; the
# walk-through is docs/16). Idempotent: re-run after changing anything in ops/linux/.
#
#   sudo bash /srv/hb/app/ops/linux/install.sh
#
# Enables hb.service only. The three timers are enabled separately, with the command
# printed below: on a fresh install right away; when moving data from a local
# instance, only once it has moved (docs/16 §8), since a pipeline run before then
# would write into the fresh database the move replaces.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "install.sh: run with sudo" >&2; exit 1; }
here="$(cd "$(dirname "$0")" && pwd)"

install -m 644 "$here"/hb*.service "$here"/hb*.timer /etc/systemd/system/

# visudo checks the file before it goes live: a broken sudoers.d file locks out sudo
install -m 440 "$here/hb.sudoers" /tmp/hb.sudoers.check
visudo -cqf /tmp/hb.sudoers.check
mv /tmp/hb.sudoers.check /etc/sudoers.d/hb

systemctl daemon-reload
systemctl enable hb.service

echo "installed. Enable the schedules (after any data move, docs/16 section 8):"
echo "  sudo systemctl enable --now hb-daily.timer hb-scan.timer hb-alerts.timer"

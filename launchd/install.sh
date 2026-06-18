#!/usr/bin/env bash
# install.sh — load/unload the Acme engine launchd jobs (STEP C scheduling).
#
# The committed *.plist files are REFERENCE copies with this machine's absolute paths.
# This script regenerates them for the ACTUAL checkout location + python interpreter,
# installs into ~/Library/LaunchAgents, and (un)loads them. It does NOT touch any
# OpenClaw job — these are co.acme.engine.* labels only.
#
#   ./install.sh install     # generate + load all 4 jobs
#   ./install.sh uninstall   # unload + remove all 4 jobs
#   ./install.sh status      # show load state + next-run for each
#
# ⚠️ Loading starts the timers. Publishing is still SUPERVISED (dry-run) until you
#    `touch output/GO_LIVE`. The produce/review/approvals jobs are safe to run early.
#    Create the dedicated bot first so review/approvals have ENGINE_TELEGRAM_* keys.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$HERE/.." && pwd)"
PYTHON="$(command -v python3)"
# Prefer the framework python if it (not /usr/bin) has `requests`.
if [ -x /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 ]; then
  PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
fi
LA="$HOME/Library/LaunchAgents"
LABELS=(produce review approvals publish)
REF_PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
REF_WD=/Users/operator/.openclaw/workspace/acme

mkdir -p "$LA" "$WORKDIR/logs"

gen() {  # render a reference plist with the live paths into LaunchAgents
  local label="$1" src="$HERE/co.acme.engine.$1.plist" dst="$LA/co.acme.engine.$1.plist"
  sed -e "s#$REF_PY#$PYTHON#g" -e "s#$REF_WD#$WORKDIR#g" "$src" > "$dst"
  echo "  wrote $dst"
}

case "${1:-}" in
  install)
    echo "Installing Acme engine jobs (WORKDIR=$WORKDIR, PYTHON=$PYTHON):"
    for l in "${LABELS[@]}"; do
      gen "$l"
      launchctl unload "$LA/co.acme.engine.$l.plist" 2>/dev/null || true
      launchctl load "$LA/co.acme.engine.$l.plist"
      echo "  loaded co.acme.engine.$l"
    done
    echo "Done. Publishing is SUPERVISED (dry-run) until you: touch $WORKDIR/output/GO_LIVE"
    ;;
  uninstall)
    for l in "${LABELS[@]}"; do
      launchctl unload "$LA/co.acme.engine.$l.plist" 2>/dev/null || true
      rm -f "$LA/co.acme.engine.$l.plist"
      echo "  removed co.acme.engine.$l"
    done
    ;;
  status)
    launchctl list | grep -E "co\.acme\.engine\." || echo "(no engine jobs loaded)"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status}"; exit 1 ;;
esac

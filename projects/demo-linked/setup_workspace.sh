#!/usr/bin/env bash
# Creates the demo-linked workspace: a git repo seeded from ./seed.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
ws="${1:-$here/../../work/demo-linked-workspace}"
if [ -e "$ws" ]; then echo "$ws already exists" >&2; exit 1; fi
mkdir -p "$ws"
cp -R "$here/seed/." "$ws/"
git -C "$ws" init -q
git -C "$ws" checkout -q -b main
git -C "$ws" add -A
git -C "$ws" -c user.name=Factory -c user.email=factory@localhost commit -q -m "Seed demo workspace"
echo "Demo workspace created at $ws"

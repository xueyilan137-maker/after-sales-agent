#!/bin/sh
set -eu
cd /app/frontend
# Preserve the original fixed-base config when an interrupted container restarts.
if [ ! -f next.pinned.config.mjs ]; then
  cp next.config.js next.pinned.config.mjs
fi
cp /build-config/next.config.mjs next.config.js
export NEXT_TELEMETRY_DISABLED=1 SKIP_ENV_VALIDATION=1
export DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=http://gateway:8001
export NODE_OPTIONS=--max-old-space-size=2048
pnpm exec next typegen
pnpm exec tsc --noEmit
printf 'STANDALONE_TYPECHECK_OK\n'
pnpm exec next build --webpack
test -s .next/BUILD_ID
printf 'PRODUCTION_BUILD_ID='
cat .next/BUILD_ID
# Only disposable compiler cache inside this isolated build container is removed.
node -e "require('node:fs').rmSync('/app/frontend/.next/cache',{recursive:true,force:true})"

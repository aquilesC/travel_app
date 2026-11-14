#!/bin/sh
# Build and test TripsKit on Linux in the official Swift image (no Mac needed).
# The whole repo is mounted because TripsAPI reads ../../api/openapi.json through a symlink.
cd "$(dirname "$0")/.." || exit 1
docker volume create trips-swiftpm-cache >/dev/null
EXTRA=""
if [ "$1" = "e2e" ]; then
  # Against the isolated dev server (container trips-dev-web on network trips-dev), never production.
  shift
  EXTRA="--network trips-dev -e TRIPS_E2E_URL=${TRIPS_E2E_URL:-http://trips-dev-web:8000}
         -e TRIPS_E2E_EMAIL=${TRIPS_E2E_EMAIL:-dev@example.com} -e TRIPS_E2E_PASSWORD=${TRIPS_E2E_PASSWORD:-dev-pass-123}"
  set -- test --filter LiveServerTests
fi
exec docker run --rm $EXTRA -v "$PWD":/repo -v trips-swiftpm-cache:/root/.cache \
  -w /repo/ios/TripsKit swift:6.4 sh -c "swift ${*:-test} --scratch-path /root/.cache/tripskit-build 2>&1"

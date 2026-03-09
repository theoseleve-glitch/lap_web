#!/usr/bin/env bash
# Generate a changelog from conventional commits since the last tag.
#
# Usage:
#   ./scripts/generate_changelog.sh           # since last tag
#   ./scripts/generate_changelog.sh v1.3.0    # since specific tag
#
# Requires conventional commit format (feat:, fix:, etc.)

set -euo pipefail

SINCE="${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo '')}"
RANGE="${SINCE:+${SINCE}..HEAD}"

echo "# Changelog"
echo ""
if [ -n "$SINCE" ]; then
  echo "## Changes since ${SINCE}"
else
  echo "## All changes"
fi
echo ""

# Features
FEATS=$(git log ${RANGE} --pretty=format:'- %s (%h)' --grep='^feat' 2>/dev/null || true)
if [ -n "$FEATS" ]; then
  echo "### Features"
  echo "$FEATS"
  echo ""
fi

# Bug Fixes
FIXES=$(git log ${RANGE} --pretty=format:'- %s (%h)' --grep='^fix' 2>/dev/null || true)
if [ -n "$FIXES" ]; then
  echo "### Bug Fixes"
  echo "$FIXES"
  echo ""
fi

# Performance
PERF=$(git log ${RANGE} --pretty=format:'- %s (%h)' --grep='^perf' 2>/dev/null || true)
if [ -n "$PERF" ]; then
  echo "### Performance"
  echo "$PERF"
  echo ""
fi

# Documentation
DOCS=$(git log ${RANGE} --pretty=format:'- %s (%h)' --grep='^docs' 2>/dev/null || true)
if [ -n "$DOCS" ]; then
  echo "### Documentation"
  echo "$DOCS"
  echo ""
fi

# Other (refactor, chore, ci, build, test, style)
OTHER=$(git log ${RANGE} --pretty=format:'- %s (%h)' \
  --grep='^refactor\|^chore\|^ci\|^build\|^test\|^style' 2>/dev/null || true)
if [ -n "$OTHER" ]; then
  echo "### Other"
  echo "$OTHER"
  echo ""
fi

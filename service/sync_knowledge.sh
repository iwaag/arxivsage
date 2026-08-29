#!/bin/sh
# Refresh the public knowledge tree. This is run by an operator, never by sage.
set -eu

cd "$(dirname "$0")/.."

if [ -d knowledge/.git ]; then
  exec git -C knowledge pull --ff-only
fi

if [ -e knowledge ]; then
  echo "knowledge exists but is not a Git checkout" >&2
  exit 1
fi

exec git clone https://github.com/iwaag/study-arxiv-trend.git knowledge

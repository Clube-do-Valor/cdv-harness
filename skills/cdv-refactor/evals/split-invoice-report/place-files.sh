#!/usr/bin/env bash
# Lays the task repository out in the working directory and commits it as the base of the run.
set -eu
cp -R "$(dirname "$0")/files/." .
git init -q -b main
git add -A
git -c user.name="Eval Fixture" -c user.email="fixture@example.com" commit -q -m "chore: initial import"

#!/usr/bin/env bash
#
# ddl.sh — print the current DDL of a MySQL table from the application database,
# or list all tables when called without an argument.
#
# Usage:
#   ./ddl.sh                  # list all tables
#   ./ddl.sh orders           # full DDL via SHOW CREATE TABLE (default — includes indexes and FKs)
#   ./ddl.sh -d orders        # concise column list via DESCRIBE
#
# Sanitizes the table name to [A-Za-z0-9_]+ to avoid SQL injection. Delegates
# the actual exec to tinker.sh in the same directory.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="create"

usage() {
  cat <<EOF
Usage: $0 [-d|-c] [TABLE]

Options:
  -d  DESCRIBE mode (concise column list).
  -c  SHOW CREATE TABLE mode (full DDL with indexes and FKs, default).
  -h  Show this help.

Without TABLE, lists all tables in the current database.
EOF
}

while getopts ":dch" opt; do
  case "$opt" in
    d) MODE="describe" ;;
    c) MODE="create" ;;
    h) usage; exit 0 ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

TABLE="${1:-}"

if [[ -n "$TABLE" && ! "$TABLE" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "Invalid table name '$TABLE': must match [A-Za-z0-9_]+" >&2
  exit 2
fi

if [[ -z "$TABLE" ]]; then
  "$HERE/tinker.sh" -e 'foreach (DB::select("SHOW TABLES") as $r) { echo array_values((array)$r)[0].PHP_EOL; }'
  exit 0
fi

case "$MODE" in
  describe)
    "$HERE/tinker.sh" -e "foreach (DB::select('DESCRIBE $TABLE') as \$c) { printf('%-40s %-25s null=%s key=%s default=%s'.PHP_EOL, \$c->Field, \$c->Type, \$c->Null, \$c->Key, \$c->Default ?? ''); }"
    ;;
  create)
    "$HERE/tinker.sh" -e "\$rows = DB::select('SHOW CREATE TABLE $TABLE'); echo (\$rows[0]->{'Create Table'} ?? '').PHP_EOL;"
    ;;
esac

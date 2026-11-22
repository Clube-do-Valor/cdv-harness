#!/usr/bin/env node
'use strict';

// slugkit <command> [--legacy] <text>
// Commands are resolved from this table, so a helper can be added without touching the parser.
const path = require('path');

const COMMANDS = {
  slug: { file: path.join(__dirname, '..', 'lib', 'helpers', 'slugify.js'), fn: 'mkSlug', legacyFn: 'mkSlugLegacy' },
  truncate: { file: path.join(__dirname, '..', 'lib', 'helpers', 'truncate.js'), fn: 'truncate' },
};

function main(argv) {
  const [command, ...rest] = argv;
  const legacy = rest.includes('--legacy');
  const args = rest.filter((arg) => arg !== '--legacy');
  const entry = COMMANDS[command];
  if (!entry) {
    process.stderr.write(`unknown command: ${command}\n`);
    return 2;
  }
  const mod = require(entry.file);
  const fnName = legacy && entry.legacyFn ? entry.legacyFn : entry.fn;
  const result = command === 'truncate' ? mod[fnName](args[0], Number(args[1])) : mod[fnName](args.join(' '));
  process.stdout.write(result + '\n');
  return 0;
}

process.exitCode = main(process.argv.slice(2));

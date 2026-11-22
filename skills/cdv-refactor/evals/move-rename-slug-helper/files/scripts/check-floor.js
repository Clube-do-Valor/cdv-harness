'use strict';
// Runs the suite and fails when a test fails or when fewer tests ran than test-floor.json demands.
// The floor exists so that a test file cannot disappear without anyone noticing.
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const testDir = path.join(root, 'test');
const files = fs.readdirSync(testDir).filter((f) => f.endsWith('.test.js')).map((f) => path.join('test', f));
const run = spawnSync(process.execPath, ['--test', '--test-reporter=tap', ...files], { cwd: root, encoding: 'utf8' });
process.stdout.write(run.stdout);
process.stderr.write(run.stderr);
const pass = Number((run.stdout.match(/^# pass (\d+)/m) || [])[1] || 0);
const fail = Number((run.stdout.match(/^# fail (\d+)/m) || [])[1] || 0);
const { min_tests: floor } = JSON.parse(fs.readFileSync(path.join(root, 'test-floor.json'), 'utf8'));
if (run.status !== 0 || fail > 0) {
  console.error(`check-floor: FAIL - ${fail} failing test(s)`);
  process.exit(1);
}
if (pass < floor) {
  console.error(`check-floor: FAIL - ${pass} tests ran, the floor is ${floor}`);
  process.exit(1);
}
console.log(`check-floor: PASS - ${pass} tests, floor ${floor}`);

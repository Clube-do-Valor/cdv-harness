'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { mkSlugLegacy } = require('../lib/helpers/slugify');

test('legacy: spaces become underscores', () => assert.strictEqual(mkSlugLegacy('Hello World'), 'hello_world'));
test('legacy: punctuation is kept', () => assert.strictEqual(mkSlugLegacy('Hi, there!'), 'hi,_there!'));
test('legacy: trims', () => assert.strictEqual(mkSlugLegacy('  Hi  '), 'hi'));

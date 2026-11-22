'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { mkSlug } = require('../lib/helpers/slugify');

test('lower case and dashes', () => assert.strictEqual(mkSlug('Hello World'), 'hello-world'));
test('accents are removed', () => assert.strictEqual(mkSlug('Crème Brûlée'), 'creme-brulee'));
test('ampersand becomes and', () => assert.strictEqual(mkSlug('Salt & Pepper'), 'salt-and-pepper'));
test('edges are trimmed', () => assert.strictEqual(mkSlug('  --Hi!--  '), 'hi'));
test('custom separator', () => assert.strictEqual(mkSlug('a b c', '_'), 'a_b_c'));

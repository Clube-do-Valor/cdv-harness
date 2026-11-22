'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { articlePath, cardTitle } = require('../src/titles');

test('article path', () =>
  assert.strictEqual(articlePath('Crème Brûlée', new Date('2026-03-04T10:00:00Z')), '/articles/2026-03-04/creme-brulee'));
test('card title is truncated', () => assert.strictEqual(cardTitle('x'.repeat(50)).length, 40));

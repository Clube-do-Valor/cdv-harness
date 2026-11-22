'use strict';

function truncate(text, max) {
  if (text.length <= max) return text;
  return text.slice(0, Math.max(0, max - 1)) + '…';
}

module.exports = { truncate };

'use strict';

// Turn any title into a URL slug: accents removed, lower case, one separator between words.
function mkSlug(input, separator = '-') {
  return String(input)
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, separator)
    .replace(new RegExp(`^${separator}+|${separator}+$`, 'g'), '');
}

// The slug format used before the URL migration: spaces become underscores, nothing else changes.
function mkSlugLegacy(input) {
  return String(input).trim().toLowerCase().replace(/\s+/g, '_');
}

module.exports = { mkSlug, mkSlugLegacy };

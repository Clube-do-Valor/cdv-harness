'use strict';

const { mkSlug } = require('../lib/helpers/slugify');
const { truncate } = require('../lib/helpers/truncate');

function articlePath(title, date) {
  const day = date.toISOString().slice(0, 10);
  return `/articles/${day}/${mkSlug(title)}`;
}

function cardTitle(title) {
  return truncate(title, 40);
}

module.exports = { articlePath, cardTitle };

#!/usr/bin/env node
// Fails if a test report contains tests that did not run (CLAUDE.md §2: zero skipped tests).
// Usage: node scripts/check_no_skips.mjs <vitest|playwright> <report.json>
import { readFileSync } from 'node:fs';

const [kind, file] = process.argv.slice(2);
if (!kind || !file) {
  console.error('Usage: check_no_skips.mjs <vitest|playwright> <report.json>');
  process.exit(2);
}

const report = JSON.parse(readFileSync(file, 'utf8'));
let ran;
let notRun;
if (kind === 'vitest') {
  ran = report.numPassedTests;
  notRun = report.numPendingTests + report.numTodoTests;
} else if (kind === 'playwright') {
  ran = report.stats.expected;
  notRun = report.stats.skipped + report.stats.flaky;
} else {
  console.error(`Unknown report kind: ${kind}`);
  process.exit(2);
}

if (!Number.isInteger(ran) || !Number.isInteger(notRun)) {
  console.error(`${file}: report does not have the expected ${kind} fields`);
  process.exit(2);
}
if (ran === 0) {
  console.error(`${kind}: no tests ran`);
  process.exit(1);
}
if (notRun > 0) {
  console.error(`${kind}: ${notRun} test(s) were skipped, pending or flaky`);
  process.exit(1);
}
console.log(`${kind}: ${ran} tests ran, 0 skipped`);

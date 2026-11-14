// Generates src/state/wsTypes.ts from ../shared/ws_schema.json (PROMPT.md §6.1).
// `--check` fails if the committed file is out of date.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { compile } from 'json-schema-to-typescript';

const schemaPath = new URL('../../shared/ws_schema.json', import.meta.url);
const outPath = new URL('../src/state/wsTypes.ts', import.meta.url);
const schema = JSON.parse(readFileSync(schemaPath, 'utf8'));
const banner =
  '/* Generated from shared/ws_schema.json by `npm run gen:types`. Do not edit by hand. */\n/* eslint-disable */\n';
const text = await compile(schema, 'ServerMessage', {
  bannerComment: banner,
  additionalProperties: false,
  unreachableDefinitions: true,
  style: { singleQuote: true },
});
if (process.argv.includes('--check')) {
  if (!existsSync(outPath) || readFileSync(outPath, 'utf8') !== text) {
    console.error('src/state/wsTypes.ts is out of date. Run: npm run gen:types');
    process.exit(1);
  }
  console.log('src/state/wsTypes.ts is up to date');
} else {
  writeFileSync(outPath, text);
  console.log('Wrote src/state/wsTypes.ts');
}

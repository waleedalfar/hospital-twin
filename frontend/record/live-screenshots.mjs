// Screenshots of the deployed site for docs/evidence/cp8: `node record/live-screenshots.mjs https://hospital-twin.us`
import { chromium } from '@playwright/test';

const base = (process.argv[2] ?? 'https://hospital-twin.us').replace(/\/$/, '');
const out = '../docs/evidence/cp8';
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const wait = (ms) => page.waitForTimeout(ms);

await page.goto(`${base}/`);
await page.getByTestId('hospital-mercy').waitFor({ timeout: 60000 });
await wait(4000);
await page.screenshot({ path: `${out}/live-network-map.png` });

await page.getByTestId('hospital-mercy').click();
await page.waitForFunction(() => window.__TWIN_DEBUG__.frameStats().frames > 10, null, { timeout: 60000 });
await wait(4000);
await page.screenshot({ path: `${out}/live-mercy-free-fly.png` });

await page.getByRole('button', { name: /^X-ray/ }).click();
await page.getByRole('button', { name: 'ICU close-up' }).click();
await wait(4000);
await page.screenshot({ path: `${out}/live-xray-icu.png` });
await page.getByRole('button', { name: /^X-ray/ }).click();
await page.getByRole('button', { name: 'Outside' }).click();
await wait(3000);

await page.getByTestId('ask-input').fill('who is most likely to crash in the ICU');
await page.getByTestId('ask-send').click();
await page.getByTestId('ask-answer').waitFor({ timeout: 40000 });
await wait(2500);
await page.screenshot({ path: `${out}/live-ask.png` });
await page.getByTestId('ask-answer').getByRole('button', { name: 'Close' }).click();

await page.getByTestId('governance-button').click();
await wait(5000);
await page.screenshot({ path: `${out}/live-governance-drift.png` });
await page.getByRole('tab', { name: 'Federated training' }).click();
await wait(3000);
await page.screenshot({ path: `${out}/live-federated.png` });
await browser.close();
console.log('saved to', out);

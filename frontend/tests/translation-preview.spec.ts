import { test, expect } from '@playwright/test';
import path from 'path';

const SCREENSHOTS = path.resolve(__dirname, '../../artifacts/screenshots');

test('translation preview flow works', async ({ page }) => {
  await page.goto('http://localhost:3000');

  // Screenshot 1: home/compose view
  await page.screenshot({ path: `${SCREENSHOTS}/01-home.png`, fullPage: true });

  await expect(page.locator('body')).toContainText(/Bridge/i);

  const textbox = page.locator('textarea').first();
  await textbox.fill('Mẹ ơi dạo này con rất mệt và không biết nói sao cho mẹ hiểu.');

  await page.getByRole('button', { name: /translate/i }).click();

  // Wait for review gate to appear (backend call may take a moment)
  await expect(page.locator('body')).toContainText(/translated by bridge|ai-mediated/i, {
    timeout: 20_000,
  });

  // Screenshot 2: review gate
  await page.screenshot({ path: `${SCREENSHOTS}/02-review-gate.png`, fullPage: true });
});

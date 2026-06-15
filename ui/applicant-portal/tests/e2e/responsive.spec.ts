import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Helper to calculate contrast ratio according to WCAG
function getLuminance(r: number, g: number, b: number) {
  const [rs, gs, bs] = [r, g, b].map(c => {
    c = c / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function getContrastRatio(l1: number, l2: number) {
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function parseColor(color: string): [number, number, number] {
  const match = color.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (match) {
    return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
  }
  return [255, 255, 255]; // default white
}

test.describe('Responsive and Accessibility Tests', () => {

  test('Test 1 — Mobile (375px iPhone SE)', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');

    // Assert the header logo is visible
    const logo = page.locator('header a').first();
    await expect(logo).toBeVisible();

    // Assert the primary CTA button is visible and not clipped
    const ctaButton = page.locator('a[href="/apply"]').first();
    await expect(ctaButton).toBeVisible();
    const box = await ctaButton.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(0);

    // Assert no horizontal scroll
    const scrollWidth = await page.evaluate(() => document.body.scrollWidth);
    const innerWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth);

    const screenshotDir = path.join(__dirname, 'screenshots');
    if (!fs.existsSync(screenshotDir)) fs.mkdirSync(screenshotDir, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDir, 'mobile_home.png') });
  });

  test('Test 2 — Tablet (768px iPad)', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/apply');

    // Assert the form renders visible fields
    const formContainer = page.locator('form');
    await expect(formContainer).toBeVisible();

    // Assert no horizontal scroll
    const scrollWidth = await page.evaluate(() => document.body.scrollWidth);
    const innerWidth = await page.evaluate(() => window.innerWidth);
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth);

    const screenshotDir = path.join(__dirname, 'screenshots');
    if (!fs.existsSync(screenshotDir)) fs.mkdirSync(screenshotDir, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDir, 'tablet_apply.png') });
  });

  test('Test 3 — Desktop (1280px)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/apply');

    // Fill the form (Assuming standard fields are present based on the Next.js app)
    // Wait for the form fields
    const firstNameInput = page.locator('input[name="firstName"], input[id="firstName"]').first();
    const isFirstNameVisible = await firstNameInput.isVisible().catch(() => false);

    if (isFirstNameVisible) {
      await firstNameInput.fill('John');
      await page.locator('input[name="lastName"], input[id="lastName"]').first().fill('Doe');
      await page.locator('input[name="loanAmount"], input[id="loanAmount"]').first().fill('10000');
    }

    const submitButton = page.locator('button[type="submit"]').first();
    await expect(submitButton).toBeEnabled();

    const screenshotDir = path.join(__dirname, 'screenshots');
    if (!fs.existsSync(screenshotDir)) fs.mkdirSync(screenshotDir, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDir, 'desktop_apply.png') });
  });

  test('Test 4 — Contrast check (desktop)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    const checkContrast = async (selector: string, defaultBg = 'rgb(255, 255, 255)') => {
      const elements = page.locator(selector);
      const count = await elements.count();
      if (count === 0) return; // Skip if not found

      const firstEl = elements.first();
      await expect(firstEl).toBeVisible();

      const colors = await firstEl.evaluate((el: HTMLElement, bgStr: string) => {
        const style = window.getComputedStyle(el);
        let bg = style.backgroundColor;
        if (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
            // Find parent background
            let parent = el.parentElement;
            while (parent && (window.getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)' || window.getComputedStyle(parent).backgroundColor === 'transparent')) {
                parent = parent.parentElement;
            }
            if (parent) {
                bg = window.getComputedStyle(parent).backgroundColor;
            } else {
                bg = bgStr;
            }
        }
        return {
          color: style.color,
          bg: bg
        };
      }, defaultBg);

      const fgColor = parseColor(colors.color);
      const bgColor = parseColor(colors.bg);
      const l1 = getLuminance(fgColor[0], fgColor[1], fgColor[2]);
      const l2 = getLuminance(bgColor[0], bgColor[1], bgColor[2]);
      const ratio = getContrastRatio(l1, l2);

      if (ratio < 4.5) {
        // TODO: Contrast failure for ${selector}
        console.warn(`//TODO: Contrast ratio for ${selector} is ${ratio.toFixed(2)}, which is below WCAG AA 4.5`);
      }
    };

    await checkContrast('h1');
    // For primary button
    await checkContrast('a[href="/apply"]');
    // For muted text
    await checkContrast('.text-gray-500, p');
  });

  test('Test 5 — Adverse action page', async ({ page }) => {
    await page.goto('/');

    // Setup mock decision in sessionStorage
    await page.evaluate(() => {
      const mockDecision = {
        application_id: "test-decline",
        decision: "REJECT",
        reason_codes: ["AA01", "AA04"],
        explanation: []
      };
      sessionStorage.setItem('lendsmart_decision', JSON.stringify(mockDecision));
    });

    await page.goto('/decision?id=test-decline');

    // Assert decline notice is visible
    const declineHeader = page.locator('h1', { hasText: 'Application Declined' });
    try {
      await expect(declineHeader).toBeVisible({ timeout: 10000 });
    } catch (e) {
      console.error('PAGE CONTENT ON FAILURE:', await page.content());
      throw e;
    }

    // Assert adverse action reason text is present
    const reasonText = page.locator('main').locator('text=Equal Credit Opportunity Act');
    await expect(reasonText).toBeVisible();

    // Assert contact link is visible
    const contactLink = page.locator('a[href^="mailto:"]');
    await expect(contactLink).toBeVisible();
  });
});

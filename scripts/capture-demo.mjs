// Real browser captures of simulated data; no account pages or credentials.
import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const browser = await chromium.launch()
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
  const page = await context.newPage()
  await mkdir('docs/screenshots', { recursive: true })
  await page.goto('http://127.0.0.1:5180')
  await page.getByRole('button', { name: 'Try simulated demo', exact: true }).click()
  await page.getByRole('button', { name: 'Reset replay only' }).click()
  await page.getByText('Stage 1 of 5: Normal operation', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Advance replay' }).click()
  await page.getByText('Stage 2 of 5: Detectable overnight anomaly', { exact: true }).waitFor()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: 'docs/screenshots/desktop-anomaly.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth))
    throw Error('Mobile overflow')
  await page.screenshot({ path: 'docs/screenshots/mobile-anomaly.png', fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1080 })
  await page.getByLabel('Maintenance note').fill('Simulated inspection: checking tank overflow')
  await page.getByRole('button', { name: 'Start investigation' }).click()
  await page.getByText('Simulated inspection: checking tank overflow', { exact: true }).waitFor()
  for (let stage = 3; stage <= 5; stage++) {
    await page.getByRole('button', { name: 'Advance replay' }).click()
    await page.getByText(new RegExp(`Stage ${stage} of 5:`)).waitFor()
  }
  const evidence = page.getByRole('region', { name: 'Repair verification' })
  await evidence.getByText('Compared', { exact: true }).waitFor()
  await evidence.screenshot({ path: 'docs/screenshots/repair-comparison.png' })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: 'docs/screenshots/desktop-outcome.png', fullPage: true })
  await page.getByRole('button', { name: 'Reset replay only' }).click()
  await page.getByText('Stage 1 of 5: Normal operation', { exact: true }).waitFor()
  await context.close()
  console.log(
    'Captured four real simulated-workflow screenshots; replay reset to stage 1. Uploads unchanged.',
  )
} finally {
  await browser.close()
}

import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { execFileSync } from 'node:child_process'

test.beforeEach(() => {
  execFileSync(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python', [
    '-m',
    'backend.tests.reset_e2e',
  ])
})

test('demo, building switch, accessible data, and example upload', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'See what happens after lights out.' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(page.getByText('Simulated data', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Select building')).toHaveValue('Hostel B')
  await expect(
    page.getByRole('heading', { name: 'Possible water loss', exact: true }),
  ).toBeVisible()
  await expect(page.getByText('4 consecutive hours', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-demo.png'), fullPage: true })
  await page.getByText('View hourly readings and baseline').click()
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page.getByRole('row')).toHaveCount(25)
  await page.getByLabel('Select building').selectOption('Hostel A')
  await expect(page.getByRole('heading', { name: 'No sustained pattern' })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Normal use' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('simulated-normal.csv')
  await page.getByLabel('Choose water readings CSV').setInputFiles('examples/simulated-normal.csv')
  await expect(page.getByRole('status')).toContainText('0 with possible water loss')
})

test('validation errors preserve previous analysis', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(page.getByLabel('Select building')).toHaveValue('Hostel B')
  await page.getByLabel('Choose water readings CSV').setInputFiles({
    name: 'bad.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'building_id,timestamp,consumption_liters\nA,2026-09-29T00:00:00+05:30,-10',
    ),
  })
  await expect(page.getByRole('alert')).toContainText('Line 2: consumption_liters')
  await expect(page.getByRole('alert')).toContainText('previous successful analysis')
  await expect(
    page.getByRole('heading', { name: 'Possible water loss', exact: true }),
  ).toBeVisible()
})

test('loading, server failure, and retry states', async ({ page }) => {
  await page.goto('/')
  let finish: (() => void) | undefined
  const gate = new Promise<void>((resolve) => {
    finish = resolve
  })
  await page.route('**/api/demo', async (route) => {
    await gate
    await route.fulfill({ status: 503, body: 'Unavailable' })
  })
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Analyzing readings…' })).toBeDisabled()
  finish!()
  await expect(page.getByRole('alert')).toContainText('backend is running on port 8000')
  await page.unroute('**/api/demo')
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Possible water loss', exact: true }),
  ).toBeVisible()
})

test('mobile layout and insufficient history upload', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByLabel('Choose water readings CSV').setInputFiles({
    name: 'short.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'building_id,timestamp,consumption_liters\nNew hostel,2026-09-29T05:00:00+05:30,80',
    ),
  })
  await expect(page.getByRole('heading', { name: 'Insufficient history' })).toBeVisible()
  await expect(page.getByText('5 of 6 overnight readings are missing.')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(overflow).toBe(false)
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Possible water loss', exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  const chart = page.getByRole('region', { name: 'Hourly consumption chart' })
  await chart.focus()
  await expect(chart).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => chart.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  await page.screenshot({ path: testInfo.outputPath('mobile-demo.png'), fullPage: true })
})

test('keyboard entry and WCAG accessibility checks', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
  await page.keyboard.press('Enter')
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
  await page.getByRole('button', { name: 'Load demo data', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Possible water loss', exact: true }),
  ).toBeVisible()
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
})

test('complete persisted incident workflow and isolated replay', async ({ page }, testInfo) => {
  test.setTimeout(90_000)
  const rows = ['building_id,timestamp,consumption_liters']
  for (let day = 1; day <= 20; day++) {
    for (let hour = 0; hour < 24; hour++) {
      const liters = (day === 15 || day === 16) && hour < 6 ? 180 : day >= 17 && hour < 6 ? 20 : 40
      rows.push(
        `Workflow hostel,2026-09-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:00:00+05:30,${liters}`,
      )
    }
  }
  await page.goto('/')
  await page.getByLabel('Choose water readings CSV').setInputFiles({
    name: 'workflow.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(rows.join('\n')),
  })
  await expect(page.getByLabel('Select building')).toHaveValue('Workflow hostel')
  await page.getByLabel('Evaluate as of (Asia/Kolkata)').fill('2026-09-15T06:00')
  await page.getByRole('button', { name: 'Apply cutoff' }).click()
  await page.getByRole('button', { name: 'Create incident from alert' }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await page.getByRole('button', { name: 'Create incident from alert' }).click()
  await expect(
    page.getByText('Linked to the existing incident; no duplicate was created.', { exact: true }),
  ).toBeVisible()
  await page.getByLabel('Maintenance note').fill('Inspecting tank valve')
  await page.getByRole('button', { name: 'Start investigation' }).click()
  await expect(page.getByText('Inspecting tank valve', { exact: true })).toBeVisible()
  await page.getByLabel('Evaluate as of (Asia/Kolkata)').fill('2026-09-16T12:00')
  await page.getByRole('button', { name: 'Apply cutoff' }).click()
  await expect(page.getByLabel('Repair time (Asia/Kolkata)')).toHaveValue('2026-09-16T12:00')
  await page.getByLabel('Maintenance note').fill('Valve replaced')
  await page.getByRole('button', { name: 'Record repair' }).click()
  await expect(page.getByRole('region', { name: 'Repair verification' })).toContainText(
    'Awaiting data',
  )
  await page.getByRole('button', { name: 'Latest available', exact: true }).click()
  const verification = page.getByRole('region', { name: 'Repair verification' })
  await expect(verification).toContainText('18/18 matched hours (100%)')
  await expect(verification).toContainText('Percentage difference: 50%')
  await page.reload()
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByText('Valve replaced', { exact: true })).toBeVisible()
  await expect(verification).toContainText('Percentage difference: 50%')
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
  await page.getByRole('button', { name: 'Start / resume guided replay' }).click()
  await expect(page.getByText('Stage 1 of 5: Normal operation', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Advance replay' }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await page.reload()
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(
    page.getByText('Stage 2 of 5: Detectable overnight anomaly', { exact: true }),
  ).toBeVisible()
  for (let stage = 3; stage <= 5; stage++) {
    await page.getByRole('button', { name: 'Advance replay' }).click()
    await expect(page.locator('.replay-stage')).toContainText(`Stage ${stage} of 5`)
  }
  await expect(page.getByRole('region', { name: 'Repair verification' })).toContainText('Compared')
  await page.getByRole('button', { name: 'Reset replay only' }).click()
  await expect(page.getByRole('article')).toHaveCount(0)
  await page.getByRole('button', { name: 'View saved uploads' }).click()
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByText('Valve replaced', { exact: true })).toBeVisible()
  await page.getByRole('heading', { name: 'Water consumption overview' }).click()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: testInfo.outputPath('workflow-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(
    false,
  )
  await page.screenshot({ path: testInfo.outputPath('workflow-mobile.png'), fullPage: true })
})

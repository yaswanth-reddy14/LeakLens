// Live, billable smoke check using only disposable simulated data in new sessions.
// No mocks, trace/HAR/video capture, storage exports, or credential logging.
// Run: node scripts/verify-hosted.mjs https://demo.APP_ID.amplifyapp.com
import { chromium, expect as playwrightExpect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdir, writeFile } from 'node:fs/promises'

const origin = process.argv[2]
if (!origin || new URL(origin).origin !== origin || !origin.startsWith('https://'))
  throw new Error('Provide the exact authorized HTTPS frontend origin, without a trailing slash.')
const api = 'https://p31t0ua4hk.execute-api.ap-southeast-2.amazonaws.com'
const report = { origin, api, checkedAt: new Date().toISOString(), checks: [] }
const pass = (name) => {
  report.checks.push(name)
  console.log(`PASS: ${name}`)
}
let step = 'browser startup'
const browser = await chromium.launch()
const expect = playwrightExpect.configure({ timeout: 25000 })
const contexts = []
const failures = []
const monitor = (page) => {
  const state = { sessions: 0, workspace: null, cors: false }
  page.on('pageerror', () => failures.push('Browser JavaScript error'))
  page.on('response', async (response) => {
    const url = new URL(response.url())
    if (url.origin !== api) return
    if (response.status() >= 500 || response.status() === 429)
      failures.push(`${response.status()} ${url.pathname}`)
    if (url.pathname === '/api/sessions' && response.request().method() === 'POST') {
      state.sessions++
      // Never read the response body: it contains a bearer credential.
      state.cors = response.status() === 200 || response.status() === 201
      state.cors &&= (await response.headerValue('access-control-allow-origin')) === origin
    }
    if (url.pathname === '/api/workspace' && response.ok()) state.workspace = await response.json()
  })
  return state
}
const ready = async (page) => {
  await expect(page.getByRole('button', { name: 'View saved uploads', exact: true })).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
}
const click = async (page, name) => {
  // Pace user actions below the small demo's API throttles; never retry mutations.
  await page.waitForTimeout(1100)
  await page.getByRole('button', { name, exact: true }).click()
  await ready(page)
}
const reload = async (page) => {
  await page.waitForTimeout(1100)
  await page.reload()
  await ready(page)
}
try {
  await mkdir('.tools/hosted-verification', { recursive: true })
  const first = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
  contexts.push(first)
  const page = await first.newPage()
  const state = monitor(page)
  step = 'frontend and session creation'
  await page.goto(origin)
  await ready(page)
  await expect(page.getByText('Temporary private demo session', { exact: true })).toBeVisible()
  expect(state.sessions).toBe(1)
  expect(state.cors).toBe(true)
  expect(state.workspace?.analysis.reading_count).toBe(0)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
  pass(
    'HTTPS frontend, real session creation, exact-origin CORS, empty workspace and keyboard entry',
  )

  step = 'CSV upload and incident lifecycle'
  const rows = ['building_id,timestamp,consumption_liters']
  for (let day = 1; day <= 20; day++) {
    for (let hour = 0; hour < 24; hour++) {
      const liters = (day === 15 || day === 16) && hour < 6 ? 180 : day >= 17 && hour < 6 ? 20 : 40
      rows.push(
        `Simulated hosted hostel,2026-09-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:00:00+05:30,${liters}`,
      )
    }
  }
  const file = {
    name: 'simulated-hosted-workflow.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(rows.join('\n')),
  }
  await page.getByLabel('Choose water readings CSV').setInputFiles(file)
  await expect(page.getByLabel('Select building')).toHaveValue('Simulated hosted hostel')
  await ready(page)
  await page.getByLabel('Evaluate as of (Asia/Kolkata)').fill('2026-09-15T06:00')
  await click(page, 'Apply cutoff')
  await click(page, 'Create incident from alert')
  await expect(page.getByRole('article')).toHaveCount(1)
  await click(page, 'Create incident from alert')
  await expect(
    page.getByText('Linked to the existing incident; no duplicate was created.', { exact: true }),
  ).toBeVisible()
  await page.getByLabel('Maintenance note').fill('Simulated inspection: checking tank valve')
  await click(page, 'Start investigation')
  await page.getByLabel('Evaluate as of (Asia/Kolkata)').fill('2026-09-16T12:00')
  await click(page, 'Apply cutoff')
  await page.getByLabel('Maintenance note').fill('Simulated repair: valve replaced')
  await click(page, 'Record repair')
  const comparison = page.getByRole('region', { name: 'Repair verification' })
  await expect(comparison).toContainText('Awaiting data')
  await click(page, 'Latest available')
  await expect(comparison).toContainText('18/18 matched hours (100%)')
  await expect(comparison).toContainText('Percentage difference: 50%')
  await expect(comparison).toContainText('Comparison window:')
  await expect(comparison).toContainText('Reference window:')
  await reload(page)
  await expect(page.getByRole('article')).toHaveCount(1)
  await expect(page.getByText('Simulated repair: valve replaced', { exact: true })).toBeVisible()
  await expect(comparison).toContainText('Percentage difference: 50%')
  expect(state.sessions).toBe(1)
  const savedIncident = state.workspace.incidents[0]
  expect(savedIncident.status).toBe('Repaired')
  expect(savedIncident.verification.observed_liters).toBe(360)
  expect(savedIncident.verification.expected_liters).toBe(720)
  expect(savedIncident.verification.difference_liters).toBe(360)
  pass(
    '480-row upload, incident deduplication, investigation/repair notes, Awaiting data, 720 L baseline vs 360 L observed, reload persistence',
  )

  step = 'upload idempotency and atomic conflicts'
  await page.waitForTimeout(1100)
  await page.getByLabel('Choose water readings CSV').setInputFiles(file)
  await ready(page)
  await reload(page)
  expect(state.workspace.analysis.reading_count).toBe(480)
  expect(state.workspace.incidents[0].id).toBe(savedIncident.id)
  const conflict = {
    ...file,
    buffer: Buffer.from(rows.join('\n').replace('+05:30,40', '+05:30,41')),
  }
  await page.waitForTimeout(1100)
  const conflictResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/analyze',
  )
  await page.getByLabel('Choose water readings CSV').setInputFiles(conflict)
  expect((await conflictResponse).status()).toBe(409)
  await expect(page.getByRole('alert')).toBeVisible()
  await reload(page)
  expect(state.workspace.analysis.reading_count).toBe(480)
  expect(state.workspace.incidents[0].verification.expected_liters).toBe(720)
  pass('Repeat upload idempotency and conflicting upload rejection preserve saved analysis')

  step = 'second independent visitor'
  const second = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  })
  contexts.push(second)
  const other = await second.newPage()
  const otherState = monitor(other)
  await other.goto(origin)
  await ready(other)
  expect(otherState.workspace.analysis.reading_count).toBe(0)
  expect(otherState.workspace.incidents).toHaveLength(0)
  expect(otherState.sessions).toBe(1)
  expect(otherState.cors).toBe(true)
  await click(other, 'Start / resume guided replay')
  await click(other, 'Advance replay')
  await expect(other.locator('.workflow-controls .replay-stage')).toContainText('Stage 2 of 5')
  await other.getByLabel('Maintenance note').fill('Simulated visitor two investigation')
  await click(other, 'Start investigation')
  await reload(other)
  const otherIncidentId = otherState.workspace.incidents[0].id
  await expect(
    other.getByText('Simulated visitor two investigation', { exact: true }),
  ).toBeVisible()
  pass('Independent mobile browser session starts empty and owns a separate investigation')

  step = 'five-stage real replay'
  await click(page, 'Start / resume guided replay')
  await expect(page.locator('.workflow-controls .replay-stage')).toContainText('Stage 1 of 5')
  await expect(page.getByRole('article')).toHaveCount(0)
  for (let stage = 2; stage <= 5; stage++) {
    await click(page, 'Advance replay')
    await expect(page.locator('.workflow-controls .replay-stage')).toContainText(
      `Stage ${stage} of 5`,
    )
    await expect(page.getByRole('article')).toHaveCount(1)
    if (stage === 2) {
      await reload(page)
      await expect(page.locator('.workflow-controls .replay-stage')).toContainText('Stage 2 of 5')
      await expect(page.getByRole('article')).toHaveCount(1)
    }
    if (stage === 4) await expect(comparison).toContainText('Awaiting data')
  }
  await expect(comparison).toContainText('Compared')
  await expect(comparison).toContainText('18/18 matched hours (100%)')
  await expect(comparison.getByRole('heading')).toHaveText(
    'Estimated consumption reduction against baseline',
  )
  await comparison.getByText('Baseline method and coverage details').click()
  await expect(comparison).toContainText('known incident hours excluded')
  pass(
    'All five simulated replay stages use live backend; no duplicate on reload; repair comparison and baseline details render',
  )

  step = 'desktop/mobile layout and accessibility'
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
  await page.screenshot({ path: '.tools/hosted-verification/desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect(await other.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  const mobileChart = other.getByRole('region', { name: 'Hourly consumption chart' })
  await mobileChart.focus()
  await expect(mobileChart).toBeFocused()
  await other.keyboard.press('ArrowRight')
  await expect.poll(() => mobileChart.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  expect(
    (await new AxeBuilder({ page: other }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
  await page.screenshot({ path: '.tools/hosted-verification/mobile.png', fullPage: true })
  pass(
    'Desktop 1440px and mobile 390px: no horizontal overflow; Chromium mobile workflow; axe WCAG A/AA checks passed',
  )

  step = 'reset boundaries'
  await click(page, 'Reset replay only')
  await expect(page.locator('.workflow-controls .replay-stage')).toContainText('Stage 1 of 5')
  await expect(page.getByRole('article')).toHaveCount(0)
  await reload(other)
  await expect(other.locator('.workflow-controls .replay-stage')).toContainText('Stage 2 of 5')
  await expect(
    other.getByText('Simulated visitor two investigation', { exact: true }),
  ).toBeVisible()
  expect(otherState.workspace.incidents[0].id).toBe(otherIncidentId)
  await click(page, 'View saved uploads')
  await expect(page.getByText('Simulated repair: valve replaced', { exact: true })).toBeVisible()
  await expect(comparison).toContainText('Percentage difference: 50%')
  expect(state.sessions).toBe(1)
  expect(otherState.sessions).toBe(1)
  expect(await page.evaluate(() => localStorage.getItem('leaklens-session-v1') === null)).toBe(true)
  expect(await other.evaluate(() => localStorage.getItem('leaklens-session-v1') === null)).toBe(
    true,
  )
  pass(
    'Reset affects only visitor one replay; visitor two investigation and visitor one uploaded incident persist; reloads reuse sessions',
  )

  step = 'CORS rejection and unauthenticated boundary'
  const preflight = await first.request.fetch(`${api}/api/workspace`, {
    method: 'OPTIONS',
    headers: {
      Origin: origin,
      'Access-Control-Request-Method': 'GET',
      'Access-Control-Request-Headers': 'authorization',
    },
  })
  expect(preflight.ok()).toBe(true)
  expect(preflight.headers()['access-control-allow-origin']).toBe(origin)
  const denied = await first.request.get(`${api}/api/workspace?scope=uploads`, {
    headers: { Origin: 'https://example.invalid' },
  })
  expect(denied.status()).toBe(403)
  const anonymous = await first.request.get(`${api}/api/workspace?scope=uploads`, {
    headers: { Origin: origin },
  })
  expect(anonymous.status()).toBe(401)
  expect(failures).toEqual([])
  pass(
    'Allowed-origin preflight succeeds; previous placeholder origin is rejected; unauthenticated workspace rejected; no observed 429/5xx or JavaScript errors',
  )
  report.result = 'passed'
} catch (error) {
  report.result = 'failed'
  report.failedStep = step
  console.error(`FAIL at ${step}: ${error.message}`)
  process.exitCode = 1
} finally {
  await writeFile('.tools/hosted-verification/result.json', JSON.stringify(report, null, 2))
  for (const context of contexts) await context.close()
  await browser.close()
}

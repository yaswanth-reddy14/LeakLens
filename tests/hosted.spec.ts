import { test, expect, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('hosted browser uses private bearer sessions and does not silently renew expired state (mock API)', async ({
  page,
  browser,
}) => {
  const empty = {
    scope: 'uploads',
    cutoff: '2026-09-01T00:00:00+05:30',
    analysis: {
      source: 'upload',
      timezone: 'Asia/Kolkata',
      reading_count: 0,
      building_count: 0,
      buildings: [],
      period_start: null,
      period_end: null,
    },
    incidents: [],
  }
  let sessions = 0
  let expired = false
  const calls: { url: string; auth: string | undefined }[] = []
  const mockApi = async (route: Route) => {
    const request = route.request()
    if (request.method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': 'http://127.0.0.1:5175',
          'Access-Control-Allow-Headers': 'Authorization,Content-Type',
          'Access-Control-Allow-Methods': 'GET,POST',
        },
      })
      return
    }
    if (new URL(request.url()).pathname === '/api/sessions') {
      sessions++
      expired = false
      await route.fulfill({ json: { token: String(sessions).repeat(43), expires_at: 9999999999 } })
    } else {
      calls.push({ url: request.url(), auth: request.headers().authorization })
      await route.fulfill({
        status: expired ? 401 : 200,
        json: expired ? { detail: 'Expired' } : empty,
      })
    }
  }
  await page.route('https://mock-api.example.com/**', mockApi)
  await page.goto('http://127.0.0.1:5175')
  await expect(page.getByText('Temporary private demo session', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'View saved uploads' })).toBeEnabled()
  expect(sessions).toBe(1)
  expect(calls.length).toBeGreaterThan(0)
  expect(
    calls.every((c) => c.auth === `Bearer ${'1'.repeat(43)}` && !c.url.includes('1'.repeat(43))),
  ).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('leaklens-session-v1'))).toBeNull()
  expect(await page.evaluate(() => sessionStorage.getItem('leaklens-session-v1'))).toBe(
    '1'.repeat(43),
  )
  await page.reload()
  await expect(page.getByRole('button', { name: 'View saved uploads' })).toBeEnabled()
  expect(sessions).toBe(1)
  expired = true
  await page.getByRole('button', { name: 'View saved uploads' }).click()
  await expect(page.getByRole('alert')).toContainText('session has expired')
  expect(sessions).toBe(1)
  await page.getByRole('button', { name: 'Start new hosted session' }).click()
  await expect(page.getByRole('button', { name: 'View saved uploads' })).toBeEnabled()
  expect(sessions).toBe(2)
  expect(await page.evaluate(() => sessionStorage.getItem('leaklens-session-v1'))).toBe(
    '2'.repeat(43),
  )
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([])
  const other = await browser.newContext()
  const otherPage = await other.newPage()
  await otherPage.route('https://mock-api.example.com/**', mockApi)
  await otherPage.goto('http://127.0.0.1:5175')
  await expect(otherPage.getByRole('button', { name: 'View saved uploads' })).toBeEnabled()
  expect(await otherPage.evaluate(() => sessionStorage.getItem('leaklens-session-v1'))).toBe(
    '3'.repeat(43),
  )
  expect(await page.evaluate(() => sessionStorage.getItem('leaklens-session-v1'))).toBe(
    '2'.repeat(43),
  )
  await other.close()
})

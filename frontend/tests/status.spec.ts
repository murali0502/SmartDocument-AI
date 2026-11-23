import { expect, test } from "@playwright/test"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const backend = fileURLToPath(new URL("../../backend/", import.meta.url))
const database = fileURLToPath(new URL("../test-results/fixture.sqlite3", import.meta.url))

test("reports real API and SQLite state and refreshes after migration", async ({ page }, info) => {
  const pageErrors: string[] = []
  page.on("pageerror", (error) => pageErrors.push(error.message))

  const initialProbe = page.waitForResponse((response) => response.url().endsWith("/health/ready"))
  await page.goto("/")
  expect((await initialProbe).status()).toBe(503)
  await expect(page.getByRole("heading", { name: "System needs attention" })).toBeVisible()
  await expect(page.getByText("Responding", { exact: true })).toBeVisible()
  await expect(page.getByText("Database missing")).toBeVisible()
  await expect(page.getByText("Run the database migrations", { exact: false })).toBeVisible()

  execFileSync("uv", ["run", "--frozen", "alembic", "upgrade", "head"], {
    cwd: backend,
    env: { ...process.env, SMARTDOC_DATABASE_PATH: database },
  })

  const readyProbe = page.waitForResponse((response) => response.url().endsWith("/health/ready"))
  await page.getByRole("button", { name: "Refresh checks" }).click()
  expect((await readyProbe).status()).toBe(200)
  await expect(page.getByRole("heading", { name: "System ready" })).toBeVisible()
  await expect(page.getByText("Schema current")).toBeVisible()
  await expect(page.locator("time")).toHaveAttribute("datetime", /^\d{4}-\d{2}-\d{2}T/)
  await page.screenshot({ path: info.outputPath("status-desktop.png") })

  await page.setViewportSize({ width: 375, height: 760 })
  await page.reload()
  await expect(page.getByRole("heading", { name: "System ready" })).toBeVisible()
  const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(hasOverflow).toBe(false)
  await page.screenshot({ path: info.outputPath("status-mobile.png") })

  await expect(page.getByRole("link", { name: "API workspace" })).toHaveAttribute(
    "href", "/api/v1/docs",
  )
  const schema = await page.request.get("/api/v1/openapi.json")
  expect((await schema.json()).info.title).toBe("SmartDoc AI")
  expect(pageErrors).toEqual([])
})

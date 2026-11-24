import { expect, test } from "@playwright/test"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const backend = fileURLToPath(new URL("../../backend/", import.meta.url))
const database = fileURLToPath(new URL("../test-results/fixture.sqlite3", import.meta.url))

test("reports real API and SQLite state and refreshes after migration", async ({ page }, info) => {
  const pageErrors: string[] = []
  page.on("pageerror", (error) => pageErrors.push(error.message))

  const initialProbe = page.waitForResponse((response) => response.url().endsWith("/health/ready"))
  await page.goto("/?status")
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

test("uploads, answers, opens a citation, and abstains", async ({ page }) => {
  execFileSync("uv", ["run", "--frozen", "alembic", "upgrade", "head"], {
    cwd: backend,
    env: { ...process.env, SMARTDOC_DATABASE_PATH: database },
  })
  await page.goto("/")
  await page.getByLabel("Choose a document").setInputFiles({
    name: "maintenance.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("The pump requires a ceramic filter.\n"),
  })
  await page.getByRole("button", { name: "Upload document" }).click()
  await expect(page.locator(".document-list")).toContainText("Ready", { timeout: 30000 })
  await page.getByLabel("Document", { exact: true }).selectOption({ label: "maintenance.txt" })
  await page.getByRole("textbox", { name: "Question" }).fill("What does the pump require?")
  await page.getByRole("button", { name: "Ask SmartDoc" }).click()
  await expect(page.locator(".answer-result")).toContainText("The pump requires a ceramic filter.")
  await page.getByRole("button", { name: /Open citation/ }).click()
  await expect(page.locator(".source-card")).toContainText("The pump requires a ceramic filter.")
  const download = page.waitForEvent("download")
  await page.getByRole("link", { name: "Download original" }).click()
  expect((await download).suggestedFilename()).toBe("maintenance.txt")
  await page.getByRole("textbox", { name: "Question" }).fill("Who designed the pump?")
  await page.getByRole("button", { name: "Ask SmartDoc" }).click()
  await expect(page.getByRole("heading", { name: "Insufficient evidence" })).toBeVisible()
  await expect(page.locator(".source-card")).toHaveCount(0)
  await page.setViewportSize({ width: 375, height: 760 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test("explores documents, concepts, relationships, and comparisons", async ({ page }) => {
  execFileSync("uv", ["run", "--frozen", "alembic", "upgrade", "head"], {
    cwd: backend,
    env: { ...process.env, SMARTDOC_DATABASE_PATH: database },
  })
  const fixtures = [
    ["pump-manual.txt", "A filter means a mesh screen. The pump requires a filter."],
    ["motor-manual.txt", "The motor requires a regulator."],
  ]
  const ids: string[] = []
  for (const [filename, text] of fixtures) {
    const receipt = await page.request.post(`/api/v1/workspaces/local/uploads?filename=${filename}`, {
      headers: { "Content-Type": "application/octet-stream", "X-SmartDoc-Upload": "1" },
      data: Buffer.from(text),
    })
    expect(receipt.ok()).toBe(true)
    const { document } = await receipt.json()
    ids.push(document.id)
    await expect.poll(async () => {
      const state = await page.request.get(`/api/v1/workspaces/local/documents/${document.id}/ncm`)
      return (await state.json()).status
    }, { timeout: 25000 }).toBe("ready")
  }
  await expect.poll(async () => {
    const state = await page.request.get("/api/v1/workspaces/local/graph")
    return (await state.json()).latest?.sources.some((source: { document_id: string }) => source.document_id === ids[1])
  }, { timeout: 25000 }).toBe(true)

  await page.goto(`/?view=documents&document=${ids[0]}`)
  await expect(page.getByRole("heading", { name: "Document details" })).toBeVisible()
  await page.locator("details summary").first().click()
  await expect(page.locator(".passage").first()).toContainText("The pump requires a filter.")

  await page.getByRole("link", { name: "Search", exact: true }).click()
  await page.getByLabel("Search uploaded documents").fill("mesh screen")
  await page.getByRole("button", { name: "Search passages" }).click()
  await page.locator("summary").filter({ hasText: "pump-manual.txt" }).first().click()
  await expect(page.locator(".evidence-block").first()).toContainText("mesh screen")

  await page.getByRole("link", { name: "Concepts", exact: true }).click()
  await page.getByLabel("Document", { exact: true }).selectOption(ids[0])
  await expect(page.locator("summary").filter({ hasText: /^filter/ })).toBeVisible()

  await page.getByRole("link", { name: "Knowledge graph" }).click()
  await page.getByLabel("Concept name").fill("pump")
  await page.getByRole("button", { name: "Find concepts" }).click()
  await page.getByRole("button", { name: "pump", exact: true }).first().click()
  await expect(page.locator("summary").filter({ hasText: /requires.*filter/ }).first()).toBeVisible()

  await page.getByRole("link", { name: "Compare", exact: true }).click()
  await page.getByLabel("First document").selectOption(ids[0])
  await page.getByLabel("Second document").selectOption(ids[1])
  await expect(page.locator("summary").filter({ hasText: /only (left|right)/ }).first()).toBeVisible()
})

// In-memory render tests for the redesigned shell: keyboard + mouse via the
// official test renderer (mockInput/mockMouse send real sequences).

import { expect, test } from "bun:test"
import { testRender } from "@opentui/solid"
import { App, quit } from "../src/App"
import {
  setApps,
  setBusyText,
  setConfirmReq,
  setConnected,
  setCoreInfo,
  setLogs,
  setOverlay,
  setSelectedAlias,
  setView,
  setToasts,
  view,
} from "../src/state"

const demoApp = {
  alias: "demo",
  name: "Demo App",
  version: "1.2.3",
  arch: "x86_64",
  size: 4096,
  integrated: 1,
  source_type: "github",
  source_repo: "owner/repo",
  update_status: "up_to_date",
  latest_version: "1.2.3",
  last_check_at: "2026-01-01T00:00:00Z",
  icon_path: null,
  autoupdate: "manual",
  updated_at: "2026-01-01T00:00:00Z",
}

const secondApp = { ...demoApp, alias: "beta", name: "Beta App", version: "0.9.0" }

/** Poll until the condition holds, letting the renderer progress. */
async function until(
  cond: () => boolean,
  pump?: () => Promise<unknown>,
  tries = 40,
): Promise<void> {
  for (let i = 0; i < tries; i++) {
    if (cond()) return
    if (pump) await pump()
    await new Promise((r) => setTimeout(r, 10))
  }
}

function seed(): void {
  setConnected(true)
  setBusyText(null)
  setConfirmReq(null)
  setOverlay(null)
  setLogs([])
  setToasts([])
  setSelectedAlias("demo")
  setView("apps")
  setApps([demoApp])
  setCoreInfo({
    version: "test",
    config_path: "/x",
    state_dir: "/x",
    storage_dir: "/x",
    backup_dir: "/x",
    icon_dir: "/x",
    platform: "linux",
  })
}

test("renders the shell: tabs, app rows, status hints", async () => {
  seed()
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("quiver")
    expect(frame).toContain("apps")
    expect(frame).toContain("updates")
    expect(frame).toContain("settings")
    expect(frame).toContain("demo")
    expect(frame).toContain("menu")
    expect(frame).toContain("help")
  } finally {
    quit()
    setup.renderer.destroy()
  }
})

test("keyboard: tab cycles views, digits jump", async () => {
  seed()
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    setup.mockInput.pressKey("tab")
    await until(() => view() === "updates")
    setup.mockInput.pressKey("4")
    await until(() => view() === "activity")
  } finally {
    quit()
    setup.renderer.destroy()
  }
})

test("mouse: clicking the updates tab switches views", async () => {
  seed()
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    const col = frame.indexOf("2 updates")
    expect(col).toBeGreaterThanOrEqual(0)
    await setup.mockMouse.click(col + 3, 0)
    await until(() => view() === "updates")
  } finally {
    quit()
    setup.renderer.destroy()
  }
})

test("mouse: clicking an app row selects it", async () => {
  seed()
  setApps([demoApp, secondApp])
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    const idx = frame.indexOf("beta")
    expect(idx).toBeGreaterThanOrEqual(0)
    await setup.mockMouse.click((idx % 100) + 2, Math.floor(idx / 100))
    await until(() => view() === "apps")
    const after = setup.captureCharFrame()
    expect(after).toContain("beta")
  } finally {
    quit()
    setup.renderer.destroy()
  }
})

test("command menu opens with ':' and lists actions", async () => {
  seed()
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    setup.mockInput.pressKey(":")
    await until(
      () => Boolean(setup.captureCharFrame().includes("NAVIGATE")),
      () => setup.renderOnce(),
    )
    const frame = setup.captureCharFrame()
    expect(frame).toContain("LIBRARY")
    expect(frame).toContain("APP: DEMO")
    await new Promise((r) => setTimeout(r, 60)) // menu input armed
    await setup.mockInput.typeText("check all")
    await until(
      () => {
        const f = setup.captureCharFrame()
        return f.includes("Check all apps for updates") && !f.includes("Go to settings")
      },
      () => setup.renderOnce(),
    )
    const filtered = setup.captureCharFrame()
    expect(filtered).toContain("Check all apps for updates")
    expect(filtered).not.toContain("Go to settings")
  } finally {
    quit()
    setup.renderer.destroy()
  }
})

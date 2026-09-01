// In-memory render tests for the TUI shell (no backend, no real terminal).

import { expect, test } from "bun:test"
import { testRender } from "@opentui/solid"
import { App } from "../src/App"
import { setApps, setConnected, setCoreInfo } from "../src/state"

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

test("renders the shell chrome", async () => {
  setConnected(true)
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
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("QUIVER")
    expect(frame).toContain("Dashboard")
    expect(frame).toContain("Settings")
    expect(frame).toContain("ready")
  } finally {
    setup.renderer.destroy()
  }
})

test("dashboard lists apps from state", async () => {
  setApps([demoApp])
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("demo")
    expect(frame).toContain("1.2.3")
  } finally {
    setup.renderer.destroy()
  }
})

test("dashboard survives a failed backend fetch", async () => {
  setApps([])
  setConnected(false)
  const setup = await testRender(() => <App />, { width: 100, height: 30 })
  try {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    expect(frame).toContain("Dashboard")
  } finally {
    setup.renderer.destroy()
  }
})

// Every operation the TUI can run, mapped 1:1 onto the Python RPC surface.
// The Python backend owns the business logic; this file only sequences calls
// and updates local signals/toasts.

import { getRpc, refreshApps, toast, withBusy, pushLog, setSelectedAlias } from "./state"

export async function checkApp(alias: string): Promise<void> {
  await withBusy(`checking ${alias}`, async () => {
    const r = await getRpc().call<{ status: string; latest_version?: string | null }>(
      "updates.check",
      { alias },
    )
    if (r.status === "update_available") {
      toast("warn", `${alias}: ${r.latest_version} available`)
    } else if (r.status === "up_to_date") {
      toast("ok", `${alias}: up to date`)
    } else if (r.status === "no_source") {
      toast("info", `${alias}: no update source configured`)
    } else {
      toast("err", `${alias}: ${r.status.replace(/_/g, " ")}`)
    }
  })
  await refreshApps()
}

export async function checkAll(): Promise<void> {
  await withBusy("checking all apps", async () => {
    const results = await getRpc().call<{ alias: string; status: string }[]>("updates.check")
    const available = results.filter((r) => r.status === "update_available").length
    const problems = results.filter((r) => /error|unavailable/.test(r.status)).length
    toast(available ? "warn" : "ok", `${available} update(s) available, ${problems} problem(s)`)
  })
  await refreshApps()
}

export async function updateApp(alias: string, force = false): Promise<void> {
  await withBusy(`updating ${alias}`, async () => {
    const r = await getRpc().call<{ status: string; new_version: string | null; error?: string }>(
      "updates.apply",
      { alias, force },
    )
    if (r.status === "updated") toast("ok", `${alias} ${GLYPH_OK} ${r.new_version}`)
    else if (r.status === "up_to_date") toast("info", `${alias}: already up to date`)
    else toast("err", `${alias}: ${r.status.replace(/_/g, " ")}${r.error ? ` — ${r.error}` : ""}`)
  })
  await refreshApps()
}

export async function updateAll(): Promise<void> {
  await withBusy("updating all apps", async () => {
    const results = await getRpc().call<{ alias: string; status: string }[]>("updates.applyAll")
    const updated = results.filter((r) => r.status === "updated").length
    const failed = results.filter((r) => r.status === "failed").length
    toast(failed ? "warn" : "ok", `${updated} updated, ${failed} failed`)
  })
  await refreshApps()
}

export async function launchApp(alias: string): Promise<void> {
  await withBusy(`launching ${alias}`, async () => {
    await getRpc().call("apps.launch", { alias })
    toast("ok", `${alias} launched (detached)`)
  })
}

export async function removeApp(alias: string, purge: boolean): Promise<void> {
  await withBusy(`removing ${alias}`, async () => {
    await getRpc().call("apps.remove", { alias, purge })
    toast("ok", `${alias} removed${purge ? " (file deleted)" : ""}`)
  })
  setSelectedAlias(null)
  await refreshApps()
}

export async function refreshMetadata(alias?: string): Promise<void> {
  await withBusy(alias ? `refreshing ${alias}` : "refreshing metadata", async () => {
    const r = await getRpc().call<{ refreshed: { alias: string; changes: Record<string, unknown> }[] }>(
      "system.refresh",
      alias ? { alias } : {},
    )
    toast(
      "ok",
      r.refreshed.length
        ? r.refreshed
            .map((x) => `${x.alias}${x.changes.version ? ` ${String((x.changes.version as unknown[])[1])}` : ""}`)
            .join(", ")
        : "everything already in sync",
    )
  })
  await refreshApps()
}

export async function rollbackApp(alias: string): Promise<void> {
  await withBusy(`rolling back ${alias}`, async () => {
    const r = await getRpc().call<{ status: string; new_version: string | null; error?: string }>(
      "updates.rollback",
      { alias },
    )
    if (r.status === "rolled_back") toast("ok", `${alias} rolled back to ${r.new_version}`)
    else toast("err", `${alias}: ${r.error ?? r.status}`)
  })
  await refreshApps()
}

export async function detectSource(alias?: string): Promise<void> {
  await withBusy(alias ? `detecting source for ${alias}` : "detecting sources", async () => {
    const r = await getRpc().call<{ apps: { alias: string; set?: string; candidates: unknown[] }[] }>(
      "sources.detect",
      alias ? { alias, set: true } : { all: true },
    )
    const resolved = r.apps.filter((a) => a.set)
    const missing = r.apps.filter((a) => !a.candidates.length)
    if (resolved.length) toast("ok", resolved.map((a) => `${a.alias} ${GLYPH_ARROW} ${a.set}`).join(", "))
    if (missing.length) toast("warn", `no source found: ${missing.map((a) => a.alias).join(", ")}`)
    if (!resolved.length && !missing.length) toast("info", "every app already has a source")
  })
  await refreshApps()
}

export async function fixAll(alias?: string): Promise<void> {
  await withBusy(alias ? `fixing ${alias}` : "fixing integrations", async () => {
    const r = await getRpc().call<{ steps: string[] }>("system.repair", alias ? { alias } : {})
    toast("ok", r.steps.length ? `${r.steps.length} fix(es) applied` : "nothing to repair")
  })
  await refreshApps()
}

export async function scanSystem(): Promise<void> {
  await withBusy("scanning", async () => {
    const r = await getRpc().call<{ appimages: unknown[]; desktop_entries: unknown[]; icons: unknown[] }>(
      "system.scan",
    )
    toast(
      "info",
      `${r.appimages.length} AppImage(s), ${r.desktop_entries.length} entries, ${r.icons.length} icons`,
    )
  })
}

export async function importApps(): Promise<void> {
  await withBusy("importing found AppImages", async () => {
    const preview = await getRpc().call<{ adopted: { alias: string }[] }>("system.import", {
      dry_run: true,
    })
    if (!preview.adopted.length) {
      toast("info", "nothing new to import")
      return
    }
    const names = preview.adopted.map((a) => a.alias).join(", ")
    const done = await getRpc().call<{ adopted: unknown[] }>("system.import", {})
    toast("ok", `imported ${done.adopted.length}: ${names}`)
  })
  await refreshApps()
}

export async function cleanSystem(): Promise<void> {
  await withBusy("cleaning", async () => {
    const preview = await getRpc().call<{ removed: unknown[] }>("system.clean", { dry_run: true })
    if (!preview.removed.length) {
      toast("ok", "nothing to clean")
      return
    }
    const done = await getRpc().call<{ removed: unknown[] }>("system.clean", {})
    toast("ok", `removed ${done.removed.length} item(s)`)
  })
}

export async function addApp(path: string): Promise<void> {
  await withBusy(`adding ${path}`, async () => {
    const r = await getRpc().call<{ alias: string; warnings?: string[] }>("apps.add", { path })
    toast("ok", `added ${r.alias}`)
    for (const w of r.warnings ?? []) pushLog("warn", w)
  })
  await refreshApps()
}

const GLYPH_OK = "✓"
const GLYPH_ARROW = "→"

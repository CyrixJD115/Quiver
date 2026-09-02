// Health: doctor diagnostics with clear severity colors and action buttons.
// Destructive actions always confirm first.

import { createResource, onMount, Show } from "solid-js"
import { getRpc } from "../state"
import { C } from "../theme"
import { Button, EmptyState } from "../components/ui"
import { confirm } from "../components/Overlays"
import { cleanSystem, fixAll, importApps, scanSystem } from "../actions"
import { registerController } from "./registry"

interface Diagnostic {
  level: string
  area: string
  message: string
  hint: string | null
}

export function HealthView(): unknown {
  const [doctor, { refetch }] = createResource(async () => {
    try {
      return await getRpc().call<{
        diagnostics: Diagnostic[]
        ok: number
        info: number
        warn: number
        error: number
      }>("system.doctor")
    } catch {
      return null
    }
  })

  onMount(() => {
    registerController({
      id: "health",
      move: () => undefined,
      jump: () => undefined,
      primary: () => void refetch(),
      hints: () => [{ key: "enter", label: "rerun doctor", run: () => void refetch() }],
    })
  })

  const color = (level: string) =>
    level === "error" ? C.red : level === "warn" ? C.amber : level === "info" ? C.teal : C.green

  const issues = () => (doctor.latest?.diagnostics ?? []).filter((d) => d.level !== "ok")

  return (
    <box width="100%" height="100%" flexDirection="column">
      <box flexGrow={1} flexDirection="column" borderStyle="single" borderColor={C.border}>
        <box height={1} paddingX={1}>
          <text fg={C.dimmer}>
            DOCTOR{" "}
            {doctor.latest
              ? `${doctor.latest.ok} ok · ${doctor.latest.info} info · ${doctor.latest.warn} warn · ${doctor.latest.error} error`
              : "running…"}
          </text>
        </box>
        <Show
          when={issues().length}
          fallback={
            <Show when={doctor.latest} fallback={<text fg={C.dimmer}> running…</text>}>
              <EmptyState glyph="✓" title="all clear" hint="nothing to report" />
            </Show>
          }
        >
          {issues().map((d) => (
            <box flexDirection="column">
              <box flexDirection="row" height={1}>
                <box width={8}>
                  <text fg={color(d.level)}>{d.level === "error" ? "✗" : d.level === "warn" ? "▲" : "·"}</text>
                  <text fg={C.dimmer} wrapMode="none">
                    {` ${d.area}`}
                  </text>
                </box>
                <text fg={C.fg} wrapMode="none">
                  {d.message.slice(0, 70)}
                </text>
              </box>
              {d.hint ? (
                <box flexDirection="row" height={1}>
                  <box width={10} />
                  <text fg={C.dimmer} wrapMode="none">
                    {`↳ ${d.hint.slice(0, 66)}`}
                  </text>
                </box>
              ) : null}
            </box>
          ))}
        </Show>
      </box>
      <box height={3} flexDirection="row" borderStyle="single" borderColor={C.border} alignItems="center" paddingX={1}>
        <Button label="Fix" onClick={() => void fixAll()} />
        <box width={1} />
        <Button label="Scan" onClick={() => void scanSystem()} />
        <box width={1} />
        <Button
          label="Clean"
          onClick={() =>
            confirm(
              "Remove leftovers?",
              "Partial downloads, old backups, stale entries and unreferenced icons.",
              () => void cleanSystem(),
            )
          }
        />
        <box width={1} />
        <Button
          label="Import"
          onClick={() =>
            confirm(
              "Import AppImages from collection dirs?",
              "Adopts everything found without asking.",
              () => void importApps(),
            )
          }
        />
      </box>
    </box>
  )
}

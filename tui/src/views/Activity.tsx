// Activity: sticky-bottom scrollback of every backend event this session.

import { onMount } from "solid-js"
import { logs } from "../state"
import { C } from "../theme"
import { registerController } from "./registry"

export function ActivityView(): unknown {
  onMount(() => {
    registerController({
      id: "activity",
      move: () => undefined,
      jump: () => undefined,
      primary: () => undefined,
      key: () => false,
      hints: () => ["live feed", ": palette", "q quit"],
    })
  })

  const color = (level: string) =>
    level === "warn" ? C.yellow : level === "error" ? C.red : level === "ok" ? C.green : C.dim

  return (
    <box width="100%" height="100%" flexDirection="column" borderStyle="single" borderColor={C.border}>
      <scrollbox width="100%" flexGrow={1} stickyScroll={true} stickyStart="bottom">
        {logs().map((l) => (
          <box flexDirection="row" height={1} paddingX={1}>
            <box width={10}>
              <text fg={C.dimmer} wrapMode="none">
                {new Date().toISOString().slice(11, 19)}
              </text>
            </box>
            {l.alias ? (
              <box width={16}>
                <text fg={C.blue} wrapMode="none">
                  {l.alias}
                </text>
              </box>
            ) : null}
            <text fg={color(l.level)} wrapMode="none">
              {l.message}
            </text>
          </box>
        ))}
        {logs().length === 0 ? <text fg={C.dim}> waiting for events…</text> : null}
      </scrollbox>
    </box>
  )
}

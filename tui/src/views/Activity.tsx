// Activity: sticky-bottom scrollback of every backend event this session.
// The wheel scrolls; hover shows nothing special — it's a log.

import { onMount } from "solid-js"
import { logs } from "../state"
import { C, LEVEL_COLOR } from "../theme"
import { registerController } from "./registry"

export function ActivityView(): unknown {
  onMount(() => {
    registerController({
      id: "activity",
      move: () => undefined,
      jump: () => undefined,
      primary: () => undefined,
      hints: () => [{ label: "wheel scrolls" }],
    })
  })

  return (
    <box width="100%" height="100%" flexDirection="column" borderStyle="single" borderColor={C.border}>
      <box height={1} paddingX={1}>
        <text fg={C.dimmer}>ACTIVITY — every backend event this session</text>
      </box>
      <scrollbox width="100%" flexGrow={1} stickyScroll={true} stickyStart="bottom">
        {logs().map((l) => (
          <box flexDirection="row" height={1} paddingX={1}>
            <box width={10}>
              <text fg={C.dimmer} wrapMode="none">
                {l.time}
              </text>
            </box>
            {l.alias ? (
              <box width={16}>
                <text fg={C.teal} wrapMode="none">
                  {l.alias}
                </text>
              </box>
            ) : null}
            <text fg={LEVEL_COLOR[l.level] ?? C.dim} wrapMode="none">
              {l.message}
            </text>
          </box>
        ))}
        {logs().length === 0 ? (
          <box paddingX={1}>
            <text fg={C.dimmer}> waiting for events…</text>
          </box>
        ) : null}
      </scrollbox>
    </box>
  )
}

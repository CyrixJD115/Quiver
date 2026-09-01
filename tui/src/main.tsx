// Quiver TUI entry point. Linux-only; renders the Solid app into a CLI
// renderer and owns the backend session lifecycle.

import { render } from "@opentui/solid"
import { App } from "./App"
import { startSession, startSpinner } from "./state"

// render() owns the renderer; App's onCleanup ends the backend session, and
// exitOnCtrlC covers the interrupt path.
await render(() => <App />, {
  exitOnCtrlC: true,
  backgroundColor: "#11111b",
})

startSession()
startSpinner()

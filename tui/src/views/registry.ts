// Views register a controller so the shell can route navigation and render
// contextual status-bar hints. Actions live in the menu and on buttons -
// not on hidden per-view letter keys.

import type { ViewId } from "../state"

export interface ViewHint {
  /** Key shown in the hint chip, e.g. "enter" or "/". */
  key?: string
  label: string
  /** Optional action - makes the hint clickable in the status bar. */
  run?: () => void
}

export interface ViewController {
  id: ViewId
  /** Move the row cursor (j/k, up/down, wheel). */
  move(dir: 1 | -1, steps?: number): void
  /** Jump to first/last row (g/G). */
  jump(first: boolean): void
  /** Primary action for the current row (enter). */
  primary(): void
  /** Contextual hints for the status bar. */
  hints(): ViewHint[]
  /** Open the list filter (the "/" key). Views without lists ignore it. */
  startFilter?(): void
}

const controllers = new Map<ViewId, ViewController>()

export function registerController(c: ViewController): void {
  controllers.set(c.id, c)
}

export function getController(id: ViewId): ViewController | undefined {
  return controllers.get(id)
}

// Views register a controller so the single global key handler can route
// j/k/enter/etc. to whichever view is active. One keyboard owner at a time.

import type { ViewId } from "../state"

export interface ViewController {
  id: ViewId
  move(dir: 1 | -1): void
  jump(first: boolean): void
  primary(): void
  /** Return true when the key was consumed. */
  key(name: string, shift: boolean): boolean
  hints(): string[]
}

const controllers = new Map<ViewId, ViewController>()

export function registerController(c: ViewController): void {
  controllers.set(c.id, c)
}

export function getController(id: ViewId): ViewController | undefined {
  return controllers.get(id)
}

// Mouse hit-test shim.
//
// OpenTUI 0.1.x: renderables created by the Solid reconciler are not tagged
// into the native hit grid (`renderer.hitTest` → native `checkHit`), so mouse
// events over any Solid-built element resolve to nothing on a real terminal.
// (The in-memory test renderer hit-tests in JS, which is why tests pass.)
//
// Until upstream fixes the native tagging, we replace `hitTest` with a JS
// walk over the renderable tree: deepest node whose computed bounds contain
// the cell, children visited in reverse so later siblings (dialogs, toasts)
// win. Handlers themselves (property-set `onMouseDown` etc.) work fine once
// a target resolves.

interface ShimRenderable {
  num: number
  screenX: number
  screenY: number
  width: number
  height: number
  children?: ShimRenderable[]
  /** Layout-order children; the public getter misses reconciler-inserted ones. */
  _childrenInLayoutOrder?: ShimRenderable[]
  parent?: ShimRenderable | null
}

function kidsOf(node: ShimRenderable): ShimRenderable[] {
  return node._childrenInLayoutOrder ?? node.children ?? []
}

interface ShimRenderer {
  root: ShimRenderable
  hitTest: (x: number, y: number) => number
}

export function installMouseShim(renderer: ShimRenderer): void {
  if ((renderer.hitTest as unknown as { __shim?: boolean }).__shim) return
  const shimmed = (x: number, y: number): number => {
    const target = deepestAt(renderer.root, x, y)
    return target ? target.num : -1
  }
  Object.defineProperty(shimmed, "__shim", { value: true })
  renderer.hitTest = shimmed
}

function deepestAt(node: ShimRenderable, x: number, y: number): ShimRenderable | null {
  const kids = kidsOf(node)
  for (let i = kids.length - 1; i >= 0; i--) {
    const hit = deepestAt(kids[i], x, y)
    if (hit) return hit
  }
  return contains(node, x, y) ? node : null
}

function contains(node: ShimRenderable, x: number, y: number): boolean {
  const w = Math.max(1, node.width)
  const h = Math.max(1, node.height)
  return x >= node.screenX && x < node.screenX + w && y >= node.screenY && y < node.screenY + h
}

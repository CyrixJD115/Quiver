// Build the standalone Linux TUI binary with `bun build --compile`.
// The Solid transform plugin must run during bundling (bunfig preload only
// covers `bun run`). Linux-only by design; glibc is the default target.

import { createSolidTransformPlugin } from "@opentui/solid/bun-plugin"

const result = await Bun.build({
  entrypoints: ["src/main.tsx"],
  target: "bun",
  compile: {
    target: "bun-linux-x64",
    outfile: "dist/quiver-tui",
  },
  define: {
    "process.env.OPENTUI_LIBC": JSON.stringify("glibc"),
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  plugins: [createSolidTransformPlugin()],
  sourcemap: "none",
})

if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
console.log("built dist/quiver-tui")

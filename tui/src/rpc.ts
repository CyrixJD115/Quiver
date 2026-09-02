// JSON-RPC 2.0 client over newline-delimited JSON on stdio to `quiver api`.
// One long-lived child process per TUI session; mutations serialize on the
// Python side, so requests here can be fired freely.

import { spawn } from "child_process"

export interface LogEvent {
  time: string
  level: string
  message: string
  alias?: string | null
}

type Pending = {
  resolve: (value: unknown) => void
  reject: (err: Error) => void
  method: string
}

export class RpcClient {
  private proc: import("child_process").ChildProcess | null = null
  private nextId = 1
  private pending = new Map<number, Pending>()
  private buffer = ""
  private closed = false

  constructor(
    private readonly command: string[],
    private readonly onNotify: (method: string, params: Record<string, unknown>) => void,
    private readonly onExit: (code: number | null) => void,
  ) {}

  static fromEnv(
    onNotify: (method: string, params: Record<string, unknown>) => void,
    onExit: (code: number | null) => void,
  ): RpcClient {
    const quiver = process.env.QUIVER_API || "quiver"
    return new RpcClient([quiver, "api"], onNotify, onExit)
  }

  start(): void {
    if (this.proc) return
    this.proc = spawn(this.command[0], this.command.slice(1), {
      stdio: ["pipe", "pipe", "inherit"],
      env: process.env,
    })
    this.proc.stdout!.setEncoding("utf8")
    this.proc.stdout!.on("data", (chunk: string) => this.receive(chunk))
    this.proc.on("exit", (code) => {
      this.closed = true
      for (const p of this.pending.values()) {
        p.reject(new Error(`backend exited (${code})`))
      }
      this.pending.clear()
      this.onExit(code)
    })
    this.proc.on("error", (err) => {
      this.closed = true
      for (const p of this.pending.values()) p.reject(err)
      this.pending.clear()
      this.onExit(null)
    })
    this.proc.stdin!.on("error", () => {
      /* EPIPE when shutting down; exit handler reports it */
    })
  }

  private receive(chunk: string): void {
    this.buffer += chunk
    let nl: number
    while ((nl = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, nl).trim()
      this.buffer = this.buffer.slice(nl + 1)
      if (!line) continue
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(line)
      } catch {
        continue
      }
      if (typeof msg.method === "string") {
        this.onNotify(msg.method, (msg.params as Record<string, unknown>) || {})
      } else if (typeof msg.id === "number" && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id)!
        this.pending.delete(msg.id)
        if (msg.error) {
          const err = msg.error as { message?: string; data?: { hint?: string } }
          const e = new Error(err.message || "rpc error") as Error & { hint?: string }
          e.hint = err.data?.hint
          p.reject(e)
        } else {
          p.resolve(msg.result)
        }
      }
    }
  }

  call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (this.closed || !this.proc?.stdin?.writable) {
      return Promise.reject(new Error("backend is not running"))
    }
    const id = this.nextId++
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        method,
      })
      const line = JSON.stringify({ jsonrpc: "2.0", id, method, params })
      this.proc!.stdin!.write(line + "\n", (err) => {
        if (err) {
          this.pending.delete(id)
          reject(err)
        }
      })
    })
  }

  dispose(): void {
    this.closed = true
    try {
      this.proc?.stdin?.end()
    } catch {
      /* already gone */
    }
    this.proc?.kill()
  }
}

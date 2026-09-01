// Small helpers shared across views.

/**
 * OpenTUI inputs call onSubmit with either the string value or an (empty)
 * structural SubmitEvent interface from the input component - accept both.
 */
export type SubmitArg = string | object

export function onSubmitValue(cb: (value: string) => void): (value: SubmitArg) => void {
  return (value) => {
    cb(typeof value === "string" ? value : "")
  }
}

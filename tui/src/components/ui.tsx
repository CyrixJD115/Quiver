// Shared UI kit: buttons with hover/press, dialogs, empty states, key hints.
// Mouse is first-class: every interactive element here is clickable.

import { createSignal, JSX } from "solid-js"
import { C } from "../theme"
import { onSubmitValue } from "../util"

/** Styled inline run inside a <text>. The public span type lacks `fg`, though
 *  the runtime text-node options accept it - contained cast. */
export function Span(props: { fg: string; children: unknown }): unknown {
  return <span {...(props as unknown as object)}>{props.children as never}</span>
}

// ---- clickable -----------------------------------------------------------------


/** Wraps any renderable and makes it behave like a button: hover highlight,
 * press feedback, click = down + up inside the same target. */
export function Clickable(props: {
  onClick: () => void
  children: JSX.Element
  disabled?: boolean
}): unknown {
  const [hover, setHover] = createSignal(false)
  const [pressed, setPressed] = createSignal(false)
  if (props.disabled) {
    return <box>{props.children}</box>
  }
  return (
    <box
      onMouseOver={() => setHover(true)}
      onMouseOut={() => {
        setHover(false)
        setPressed(false)
      }}
      onMouseDown={(e: { button: number }) => {
        if (e.button === 0) setPressed(true)
      }}
      onMouseUp={(e: { button: number }) => {
        if (pressed() && e.button === 0) {
          setPressed(false)
          props.onClick()
        }
      }}
      backgroundColor={pressed() ? C.selected : hover() ? C.hover : undefined}
    >
      {props.children}
    </box>
  )
}

/** A labeled button as a flat chip: `[u] Update`. Single row, no borders -
 *  bordered boxes collapse in tight rows and corrupt their labels. */
export function Button(props: {
  label: string
  key?: string
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}): unknown {
  const [hover, setHover] = createSignal(false)
  const [pressed, setPressed] = createSignal(false)
  const fg = () => (props.danger ? C.red : C.green)
  return (
    <box
      height={1}
      paddingX={1}
      backgroundColor={pressed() ? C.greenDeep : hover() ? C.hover : C.bg}
      onMouseOver={() => setHover(true)}
      onMouseOut={() => {
        setHover(false)
        setPressed(false)
      }}
      onMouseDown={(e: { button: number }) => {
        if (e.button === 0) setPressed(true)
      }}
      onMouseUp={(e: { button: number }) => {
        if (pressed() && e.button === 0) {
          setPressed(false)
          props.onClick()
        }
      }}
    >
      <text>
        {props.key ? <Span fg={hover() ? C.greenBright : C.dimmer}>[{props.key}] </Span> : null}
        <Span fg={fg()}>{props.label}</Span>
      </text>
    </box>
  )
}

// ---- dialog chrome ---------------------------------------------------------------

/** Centered modal panel used by the menu, help, confirm and form dialogs. */
export function Dialog(props: {
  title: string
  width?: number
  children: JSX.Element
}): unknown {
  const w = props.width ?? 56
  return (
    <box position="absolute" top={2} left="50%" marginLeft={-Math.floor(w / 2)} width={w}>
      <box
        flexDirection="column"
        borderStyle="single"
        borderColor={C.borderActive}
        backgroundColor={C.panel}
        maxHeight="80%"
      >
        <box height={1} backgroundColor={C.bg} paddingX={1}>
          <text fg={C.green}>{props.title}</text>
        </box>
        {props.children}
      </box>
    </box>
  )
}

/** Empty state: glyph, one line of copy, optional call to action. */
export function EmptyState(props: {
  glyph: string
  title: string
  hint?: string
  action?: { label: string; onClick: () => void }
}): unknown {
  return (
    <box flexDirection="column" flexGrow={1} justifyContent="center" alignItems="center">
      <text fg={C.dimmer}>{props.glyph}</text>
      <text fg={C.dim}>{props.title}</text>
      {props.hint ? <text fg={C.dimmer}>{props.hint}</text> : null}
      {props.action ? (
        <box height={1} />
      ) : null}
      {props.action ? (
        <Button label={props.action.label} onClick={props.action.onClick} />
      ) : null}
    </box>
  )
}

/** A `[k] label` hint segment for the status bar; clicking runs the action. */
export function Hint(props: { key?: string; label: string; onClick?: () => void }): unknown {
  const body = (
    <text>
      {props.key ? <Span fg={C.green}>[{props.key}]</Span> : null}
      <Span fg={C.dim}> {props.label} </Span>
    </text>
  )
  if (!props.onClick) return body
  return <Clickable onClick={props.onClick}>{body}</Clickable>
}

/** One-line text input used inside dialogs. */
export function TextField(props: {
  placeholder: string
  onSubmit: (value: string) => void
  onCancel?: () => void
  value?: string
}): unknown {
  return (
    <input
      placeholder={props.placeholder}
      value={props.value ?? ""}
      onInput={() => undefined}
      onSubmit={onSubmitValue(props.onSubmit)}
      focused={true}
      backgroundColor={C.bg}
      textColor={C.fg}
    />
  )
}

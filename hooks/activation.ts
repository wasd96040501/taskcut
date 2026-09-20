/**
 * Whether taskcut does anything at all in this session.
 *
 * The decision is deliberately owned by the plugin and not delegated to the
 * platform. `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` gates every hooks module today,
 * but it is an early-access flag: when function hooks graduate it will default
 * to on or disappear, and a plugin whose safety rested on it would silently
 * become active everywhere. Nothing here depends on it.
 *
 * The rule is deny by default. A session is only active when something in it
 * says so, and an explicit off always wins.
 */

/** How taskcut decides whether to run. */
export type ActivationMode =
  /** Run only where the project, or the environment, opted in. The default. */
  | 'opt-in'
  /** Run in every session the plugin is loaded in. */
  | 'always'

/** The marker a repository adds to opt itself in. */
export const MARKER_FILE = '.taskcut'

/**
 * The environment variable that opts a single session in, or forces it off.
 *
 * `as const` so that the call site, which has to spell the name as a literal for
 * the loader to list what this module reads, can assert against it and fail the
 * build rather than drift.
 */
export const ENV_VAR = 'TASKCUT' as const

export type ActivationInputs = {
  mode: ActivationMode
  /** Whether MARKER_FILE exists at the project root. */
  markerPresent: boolean
  /** The value of ENV_VAR, if it is set. */
  env: string | undefined
}

export type Activation = {
  active: boolean
  /** Why, in a few words, for the log line and for tests. */
  reason: string
}

/** Values of ENV_VAR that mean "off", whatever else would have turned it on. */
const OFF_VALUES = new Set(['0', 'off', 'false', 'no'])

/** Values of ENV_VAR that mean "on". */
const ON_VALUES = new Set(['1', 'on', 'true', 'yes'])

/**
 * Resolves activation from plain inputs, so the rule can be read and tested
 * without a session. The order is the priority order.
 */
export function decideActivation(inputs: ActivationInputs): Activation {
  const env = inputs.env?.trim().toLowerCase()

  // An explicit off is absolute: it is the kill switch, and it outranks both the
  // configured mode and the repository's marker.
  if (env !== undefined && OFF_VALUES.has(env)) {
    return { active: false, reason: `${ENV_VAR} is off` }
  }
  if (env !== undefined && ON_VALUES.has(env)) {
    return { active: true, reason: `${ENV_VAR} is on` }
  }
  if (inputs.mode === 'always') {
    return { active: true, reason: 'activation is set to always' }
  }
  if (inputs.markerPresent) {
    return { active: true, reason: `${MARKER_FILE} is present` }
  }
  return {
    active: false,
    reason: `no ${MARKER_FILE} at the project root and ${ENV_VAR} is unset`,
  }
}

/** Reads the configured mode, defaulting to the safe one for anything unrecognised. */
export function readActivationMode(value: unknown): ActivationMode {
  return value === 'always' ? 'always' : 'opt-in'
}

/** The state before `session.start` has run: inert, so a missed hook fails closed. */
export const INERT: Activation = { active: false, reason: 'session.start has not run yet' }

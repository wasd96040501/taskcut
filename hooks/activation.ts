/**
 * Whether taskcut does anything at all in this session.
 *
 * There is one rule, and Claude Code already owns most of it. Installing a
 * plugin is where you say where it runs: `--scope user` puts it in every
 * session on the machine, `--scope project` in one repository, `--scope local`
 * in one repository for you alone. taskcut does not second-guess that. A
 * session that loaded it is a session you asked for.
 *
 * What the platform cannot express is "not this one", so the plugin owns
 * exactly that: `TASKCUT=0` switches it off for a single session, and
 * `TASKCUT=1` switches it back on if some outer setting had turned it off.
 * Nothing else. An earlier version also had a marker file and a mode setting,
 * which between them answered the question the install scope had already
 * answered, and the three of them had to be read together to know what would
 * happen.
 *
 * Nothing here depends on `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`. That flag gates
 * every hooks module today, but it is an early access flag: when function hooks
 * graduate it will default to on or disappear. A plugin whose consent rested on
 * it would become active on an unrelated Claude Code release. Consent here is
 * the install.
 */

/**
 * The environment variable that switches a single session off, or back on.
 *
 * `as const` so that the call site, which has to spell the name as a literal for
 * the loader to list what this module reads, can assert against it and fail the
 * build rather than drift.
 */
export const ENV_VAR = 'TASKCUT' as const

export type ActivationInputs = {
  /** The value of ENV_VAR, if it is set. */
  env: string | undefined
}

export type Activation = {
  active: boolean
  /** Why, in a few words, for the log line and for tests. */
  reason: string
}

/** Values of ENV_VAR that mean "off". */
const OFF_VALUES = new Set(['0', 'off', 'false', 'no'])

/** Values of ENV_VAR that mean "on". */
const ON_VALUES = new Set(['1', 'on', 'true', 'yes'])

/**
 * Resolves activation from plain inputs, so the rule can be read and tested
 * without a session.
 *
 * An unrecognised value is not an off switch. Someone who writes `TASKCUT=yes`
 * meant yes, and someone who writes `TASKCUT=maybe` has said nothing useful --
 * treating either as "off" would make a typo silently disable the plugin, which
 * is the failure that is hardest to notice.
 */
export function decideActivation(inputs: ActivationInputs): Activation {
  const env = inputs.env?.trim().toLowerCase()
  if (env !== undefined && OFF_VALUES.has(env)) {
    return { active: false, reason: `${ENV_VAR} is off` }
  }
  if (env !== undefined && ON_VALUES.has(env)) {
    return { active: true, reason: `${ENV_VAR} is on` }
  }
  return { active: true, reason: 'the plugin is installed for this session' }
}

/** The state before `session.start` has run: inert, so a missed hook fails closed. */
export const INERT: Activation = { active: false, reason: 'session.start has not run yet' }

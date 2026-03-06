/**
 * logger.ts — Production-safe logging wrapper.
 *
 * In development (NODE_ENV !== 'production'), all levels are active.
 * In production, only `error` emits (to preserve Sentry / monitoring),
 * while debug/info/warn are silenced.
 */

const isDev = process.env.NODE_ENV !== 'production';

export const logger = {
  debug: (...args: unknown[]) => {
    if (isDev) console.debug('[DEBUG]', ...args); // eslint-disable-line no-console
  },
  info: (...args: unknown[]) => {
    if (isDev) console.info('[INFO]', ...args); // eslint-disable-line no-console
  },
  warn: (...args: unknown[]) => {
    if (isDev) console.warn('[WARN]', ...args); // eslint-disable-line no-console
  },
  error: (...args: unknown[]) => {
    console.error(...args); // eslint-disable-line no-console
  },
};

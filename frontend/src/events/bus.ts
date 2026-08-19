/**
 * Minimal typed pub/sub connecting form panels to dashboard panels.
 *
 * Panels live in independently-mounted dock panels that can be re-docked,
 * closed, and reopened at any time, so they cannot rely on a shared React
 * parent to pass callbacks between them.
 *
 * A submission carries the ids of every dashboard its form feeds, because the
 * form<->dashboard relationship is many-to-many: one submission may need to
 * refresh several panels, and panels showing unrelated dashboards must be
 * left alone.
 */

type Events = {
  'submission:created': { formId: number; dashboardIds: number[] }
}

type Handler<K extends keyof Events> = (payload: Events[K]) => void

const handlers = new Map<keyof Events, Set<Handler<never>>>()

export function subscribe<K extends keyof Events>(
  event: K,
  handler: Handler<K>,
): () => void {
  if (!handlers.has(event)) handlers.set(event, new Set())
  const set = handlers.get(event)!
  set.add(handler as Handler<never>)
  return () => {
    set.delete(handler as Handler<never>)
  }
}

export function publish<K extends keyof Events>(event: K, payload: Events[K]): void {
  handlers.get(event)?.forEach((handler) => {
    ;(handler as Handler<K>)(payload)
  })
}

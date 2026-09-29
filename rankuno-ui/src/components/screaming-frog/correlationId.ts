/**
 * The id that ties one dispatch preview to the confirm that answers it.
 *
 * Its own module because two screens now mint one — the launcher and the
 * list-crawl dialog — and a second copy of the generator is a second answer to
 * "what does a correlation id look like in the logs".
 */

/**
 * A per-attempt correlation id.
 *
 * `crypto.randomUUID` is deliberately not used: it is absent from insecure
 * origins and from some test environments, and this value only has to be
 * unique enough to tie one preview to its confirm in the logs.
 */
export function newCorrelationId(): string {
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

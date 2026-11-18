// Capture the account at controller creation so delayed work retains its initiating identity.
export function captureWorkspaceFetch() {
  const accountFetch = globalThis.__doorhandleAccountFetch
  return accountFetch?.capture?.() || ((...args) => (globalThis.__doorhandleAccountFetch || globalThis.fetch)(...args))
}

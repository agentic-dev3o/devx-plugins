# Cleanup & Memory Safety Patterns — Detailed Rules & Fixes

## Rule 1: setTimeout / setInterval Must Be Cleaned Up

Every `setTimeout` or `setInterval` that can outlive the component must have
a corresponding `clearTimeout` / `clearInterval` in an effect cleanup.

### Violation: Bare setTimeout in Event Handler

```tsx
// BAD — if component unmounts within 1500ms, setState runs on unmounted component
const handleSubmit = async () => {
  await saveData()
  setSuccess(true)
  setTimeout(() => {
    setSuccess(false)
    onClose()
  }, 1500)
}
```

### Fix Option A: Effect-Based Cleanup

```tsx
const [success, setSuccess] = useState(false)

useEffect(() => {
  if (!success) return
  const id = setTimeout(() => {
    setSuccess(false)
    onClose()
  }, 1500)
  return () => clearTimeout(id)
}, [success, onClose])

const handleSubmit = async () => {
  await saveData()
  setSuccess(true)
}
```

### Fix Option B: Ref-Based Cleanup

```tsx
const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

useEffect(() => {
  return () => clearTimeout(timerRef.current)
}, [])

const handleSubmit = async () => {
  await saveData()
  setSuccess(true)
  timerRef.current = setTimeout(() => {
    setSuccess(false)
    onClose()
  }, 1500)
}
```

### When Cleanup Is Truly Optional

Short timeouts (< 500ms) in components that are never unmounted (root layout,
persistent sidebar) are low risk. Still prefer cleanup for consistency.

## Rule 2: Event Listeners

Every `addEventListener` must have a matching `removeEventListener` in cleanup.

```tsx
// BAD — listener persists after unmount
useEffect(() => {
  window.addEventListener("resize", handleResize)
}, [])
```

```tsx
// GOOD
useEffect(() => {
  const handleResize = () => setWidth(window.innerWidth)
  window.addEventListener("resize", handleResize)
  return () => window.removeEventListener("resize", handleResize)
}, [])
```

Define the handler inside the effect to guarantee the same function reference
is used for both add and remove.

## Rule 3: Subscriptions (WebSocket, EventSource, Observers)

```tsx
// GOOD — subscribe and unsubscribe in same effect
useEffect(() => {
  const ws = new WebSocket(url)
  ws.onmessage = (e) => setMessages(prev => [...prev, JSON.parse(e.data)])
  ws.onerror = (e) => setError(e)
  return () => ws.close()
}, [url])
```

For external store subscriptions, prefer `useSyncExternalStore`:

```tsx
import { useSyncExternalStore } from "react"

function useChatCount(store: ChatStore) {
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  )
}
```

## Rule 4: AbortController for Raw Fetch

```tsx
useEffect(() => {
  const ac = new AbortController()
  fetch(`/api/data/${id}`, { signal: ac.signal })
    .then(r => r.json())
    .then(setData)
    .catch(e => {
      if (e.name !== "AbortError") setError(e)
    })
  return () => ac.abort()
}, [id])
```

### SDK-Managed Fetches Are Exempt

These libraries handle cancellation internally:
- Convex: `useQuery`, `useMutation`, `usePaginatedQuery`
- React Query / TanStack Query: `useQuery`
- SWR: `useSWR`
- Apollo Client: `useQuery`

Do not add AbortController when using these — it would be redundant.

## Rule 5: Navigation — Use Router, Not window.location

### Violation

```tsx
// BAD — full page reload, loses React state
const handleImpersonate = async () => {
  await authClient.admin.impersonateUser({ userId: user.id })
  window.location.href = "/"
}
```

### Fix

```tsx
// GOOD — SPA navigation, preserves state
const navigate = useNavigate()

const handleImpersonate = async () => {
  await authClient.admin.impersonateUser({ userId: user.id })
  navigate("/")
}
```

### Exception

`window.location.href` is acceptable when:
- Navigating to a different origin (cross-domain redirect)
- The entire app state must be reset (e.g., after session invalidation)
- Navigating to a non-SPA backend route

Document the reason when using `window.location.href` intentionally.

## Rule 6: Clipboard API Error Handling

```tsx
// BAD — silent failure
await navigator.clipboard.writeText(url)
```

```tsx
// GOOD — inform user
try {
  await navigator.clipboard.writeText(url)
  toast.success("Copied to clipboard")
} catch {
  toast.error("Failed to copy — check browser permissions")
}
```

The Clipboard API can fail due to:
- Missing browser permissions
- Insecure context (HTTP, not HTTPS)
- User denied permission prompt
- Browser focus lost during operation

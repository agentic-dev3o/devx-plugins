# useEffect Anti-Patterns — Detailed Rules & Fixes

## Rule 1: Effects Are for External Synchronization Only

An effect should only sync with systems outside React: network, timers, DOM APIs,
browser storage, subscriptions.

### Violation: Derived State via Effect

```tsx
// BAD — effect mirrors props into state, causes double render
function Orders({ orders, query }: Props) {
  const [filtered, setFiltered] = useState<Order[]>([])
  useEffect(() => {
    setFiltered(orders.filter(o => o.title.includes(query)))
  }, [orders, query])
  return <List data={filtered} />
}
```

```tsx
// GOOD — derive during render
function Orders({ orders, query }: Props) {
  const filtered = useMemo(
    () => orders.filter(o => o.title.includes(query)),
    [orders, query],
  )
  return <List data={filtered} />
}
```

When filtering is cheap (< 100 items), skip `useMemo` entirely:

```tsx
const filtered = orders.filter(o => o.title.includes(query))
```

### Violation: Reactive State Clearing

```tsx
// BAD — watches state Y to clear state X
useEffect(() => {
  if (!isLocked && error) setError(null)
}, [isLocked, error])
```

```tsx
// GOOD — clear at the event source
const handleUnlock = async () => {
  await unlockThread({ id: threadId })
  setError(null) // clear here, not in an effect
}
```

### Violation: Seeding Form State from Props

```tsx
// RISKY — boundary excluded from deps; stale if prop changes while open
useEffect(() => {
  if (open) {
    setName(boundary?.name ?? "")
    setDescription(boundary?.description ?? "")
  }
}, [open]) // boundary missing
```

```tsx
// BETTER — include boundary, guard with key or explicit reset
useEffect(() => {
  if (open) {
    setName(boundary?.name ?? "")
    setDescription(boundary?.description ?? "")
  }
}, [open, boundary])

// OR use key to remount: <Dialog key={boundary?._id} />
```

For form dialogs, including `boundary` in deps is acceptable. If edits should
not be lost on prop change, document intent with a biome-ignore comment.

## Rule 2: useCallback + useEffect Indirection

```tsx
// BAD — hides real dependencies behind function identity
const fetchUsers = useCallback(async () => {
  setLoading(true)
  const { data } = await api.listUsers({ offset, search })
  if (data) setUsers(data.users)
  setLoading(false)
}, [offset, search])

useEffect(() => { fetchUsers() }, [fetchUsers])
```

```tsx
// GOOD — inline the logic, deps are explicit
useEffect(() => {
  let cancelled = false
  setLoading(true)
  api.listUsers({ offset, search }).then(({ data }) => {
    if (!cancelled && data) {
      setUsers(data.users)
      setTotal(data.total)
    }
    setLoading(false)
  })
  return () => { cancelled = true }
}, [offset, search])
```

Keep `useCallback` when the function is also called from event handlers.
Remove the indirection only when the callback exists solely to feed an effect.

## Rule 3: Exhaustive Dependencies

Always include every value read inside the effect. Suppress only with a clear
comment explaining why the omission is intentional and safe.

### Common Mistakes

```tsx
// BAD — stale count
useEffect(() => {
  if (count > 10) logAnalytics("high")
}, []) // count missing

// BAD — inline object identity changes every render
useEffect(() => {
  subscribe(options)
  return () => unsubscribe(options)
}, [options]) // if options = { a, b } created inline, effect reruns always
```

### Fixes

```tsx
// Include the dep
useEffect(() => {
  if (count > 10) logAnalytics("high")
}, [count])

// Memoize the object or destructure
const stableOptions = useMemo(() => ({ a, b }), [a, b])
useEffect(() => {
  subscribe(stableOptions)
  return () => unsubscribe(stableOptions)
}, [stableOptions])
```

## Rule 4: Race Condition Prevention

### Ignore Flag Pattern

```tsx
useEffect(() => {
  let ignore = false
  fetchUser(id).then(data => {
    if (!ignore) setUser(data)
  })
  return () => { ignore = true }
}, [id])
```

### AbortController Pattern

```tsx
useEffect(() => {
  const ac = new AbortController()
  fetch(`/api/users/${id}`, { signal: ac.signal })
    .then(r => r.json())
    .then(setUser)
    .catch(e => { if (e.name !== "AbortError") setError(e) })
  return () => ac.abort()
}, [id])
```

Note: SDK-managed fetches (Convex `useQuery`, React Query, SWR) handle
cancellation internally — AbortController is only needed for raw `fetch()`.

## Rule 5: Ref Guards for Strict Mode Double-Runs

```tsx
// Prevent duplicate side effects in React 18 Strict Mode
const initiated = useRef(false)
useEffect(() => {
  if (initiated.current) return
  initiated.current = true
  performOneTimeSetup()
}, [])
```

Use sparingly — only for truly one-time operations (analytics, redirects).

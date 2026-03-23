# Component Architecture Patterns — Detailed Rules & Fixes

## Rule 1: Extract Complex Map Callbacks

Inline `.map()` with conditionals, computed values, and branching should
be extracted into named child components for readability, testability, and
render isolation.

### Violation: Inline Render Logic

```tsx
// BAD — complex logic inside map callback
{messages.map((m) => {
  const senderName = isBoundaryThread && m.role === "user" && m.creatorId
    ? (userNameMap.get(m.creatorId) ?? "Unknown")
    : null
  const content = m.role === "assistant" && m.streamId && streamId === m.streamId
    ? stream.text || "..."
    : m.content || "..."

  if (m.role === "assistant") {
    return <div key={m._id}><p>{content}</p></div>
  }
  return (
    <div key={m._id}>
      {senderName && <p>{senderName}</p>}
      <div><p>{content}</p></div>
    </div>
  )
})}
```

### Fix: Extract to Component

```tsx
// GOOD — isolated component, React can skip re-renders for unchanged messages
function MessageBubble({ message, isBoundaryThread, userNameMap, stream, streamId }: Props) {
  const senderName = isBoundaryThread && message.role === "user" && message.creatorId
    ? (userNameMap.get(message.creatorId) ?? "Unknown")
    : null
  const content = message.role === "assistant" && message.streamId && streamId === message.streamId
    ? stream.text || "..."
    : message.content || "..."

  if (message.role === "assistant") {
    return <div><p>{content}</p></div>
  }
  return (
    <div>
      {senderName && <p>{senderName}</p>}
      <div><p>{content}</p></div>
    </div>
  )
}

// Parent becomes clean
{messages.map((m) => (
  <MessageBubble
    key={m._id}
    message={m}
    isBoundaryThread={isBoundaryThread}
    userNameMap={userNameMap}
    stream={stream}
    streamId={streamId}
  />
))}
```

### When to Extract

Extract when the map callback:
- Has conditional return statements (if/else branches)
- Computes derived values from closure variables
- Exceeds ~15 lines
- Would benefit from `React.memo` for large lists

Do NOT extract trivial maps like:
```tsx
{items.map(item => <li key={item.id}>{item.name}</li>)}
```

## Rule 2: Render Functions Inside Component Body

```tsx
// BAD — function recreated every render, captures closures
function ChatSidebar({ threads, onViewChange, onStar }: Props) {
  function renderThreadRow(t: Thread) {
    return (
      <div key={t._id} onClick={() => onViewChange({ kind: "chat", threadId: t._id })}>
        <span>{t.title}</span>
        <button onClick={() => onStar(t._id)}>Star</button>
      </div>
    )
  }

  return <div>{threads.map(renderThreadRow)}</div>
}
```

```tsx
// GOOD — separate component
function ThreadRow({ thread, onViewChange, onStar }: ThreadRowProps) {
  return (
    <div onClick={() => onViewChange({ kind: "chat", threadId: thread._id })}>
      <span>{thread.title}</span>
      <button onClick={() => onStar(thread._id)}>Star</button>
    </div>
  )
}

function ChatSidebar({ threads, onViewChange, onStar }: Props) {
  return (
    <div>
      {threads.map(t => (
        <ThreadRow key={t._id} thread={t} onViewChange={onViewChange} onStar={onStar} />
      ))}
    </div>
  )
}
```

## Rule 3: Single Responsibility Principle

Components should have one reason to change. Signs of a God component:
- Multiple `useState` for unrelated concerns (form + dialog + fetch state)
- Mix of data fetching, transformation, and rendering
- File exceeds ~200 lines with multiple responsibilities

### Fix: Split by Concern

```tsx
// BAD — one component handles everything
function OrderPage() {
  const [orders, setOrders] = useState([])
  const [filter, setFilter] = useState("")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingOrder, setEditingOrder] = useState(null)
  // ... fetch logic, filter logic, dialog logic, render
}
```

```tsx
// GOOD — hook for data, components for concerns
function useOrders(filter: string) {
  // fetch + filter logic
  return { orders, loading }
}

function OrderPage() {
  const [filter, setFilter] = useState("")
  const { orders, loading } = useOrders(filter)
  return (
    <>
      <OrderFilter value={filter} onChange={setFilter} />
      <OrderList orders={orders} loading={loading} />
      <OrderEditDialog />
    </>
  )
}
```

## Rule 4: Memoization Strategy

### useMemo — When to Use

Use `useMemo` for:
- Converting arrays to Maps/Sets for O(1) lookups
- Filtering/sorting large collections (100+ items)
- Complex computations that depend on specific inputs
- Values passed to memoized child components

Do NOT use for:
- Simple boolean expressions (`const isActive = status === "active"`)
- String concatenation
- Trivial array operations on small datasets

### useCallback — When to Use

Use `useCallback` for:
- Async handlers passed as effect dependencies
- Callbacks passed to `React.memo` children
- Handlers used in `addEventListener`/`removeEventListener`

Do NOT use for:
- Inline `onClick` on native elements (button, div)
- `onChange` on form inputs that are not memoized
- One-off handlers that are not passed down

### React.memo — When to Use

Wrap a component in `React.memo` when:
- It renders frequently due to parent re-renders
- Its props rarely change
- It is expensive to render (large DOM tree, complex calculations)

Always profile before adding `React.memo` — premature memoization adds
complexity without measurable benefit.

## Rule 5: Stable Event Handlers

### Stale Closure Problem

```tsx
// BAD — handler captures stale props
function SaveButton({ onSave, payload }: Props) {
  useEffect(() => {
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, []) // handleKey captures initial onSave/payload

  const handleKey = (e: KeyboardEvent) => {
    if (e.key === "s" && e.metaKey) onSave(payload) // stale!
  }
}
```

### Fix: Ref Pattern

```tsx
function SaveButton({ onSave, payload }: Props) {
  const latest = useRef({ onSave, payload })
  useEffect(() => { latest.current = { onSave, payload } })

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "s" && e.metaKey) latest.current.onSave(latest.current.payload)
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [])
}
```

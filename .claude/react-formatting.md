# React + TypeScript Formatting Rules

Source: https://react-typescript-cheatsheet.netlify.app/

---

## Component Declaration

Source: https://react-typescript-cheatsheet.netlify.app/docs/basic/getting-started/function_components

### Preferred pattern — type alias + destructured props

```typescript
type AppProps = {
  message: string;
};
const App = ({ message }: AppProps) => <div>{message}</div>;
```

### With explicit return type (optional, but catches accidental returns)

```typescript
const App = ({ message }: AppProps): React.JSX.Element => <div>{message}</div>;
```

### Inline props (acceptable for simple one-off components)

```typescript
const App = ({ message }: { message: string }) => <div>{message}</div>;
```

### `React.FC` / `React.FunctionComponent` — do not use

Discouraged for React 18+ / TypeScript 5.1+. Adds no benefit and has known issues with `defaultProps`.

```typescript
// Avoid:
const App: React.FC<AppProps> = ({ message }) => <div>{message}</div>;
```

---

## Types vs Interfaces for Props

- Use `type` for component props and state (more constrained, supports union types)
- Use `interface` when exporting prop types so consumers can extend them via declaration merging
- Use `type` for union types; use `interface` for dictionary shapes
- Do not mix: pick one per definition and stay consistent

---

## Common Prop Type Patterns

```typescript
// Primitives and literals
status: "waiting" | "success";
optional?: OptionalType;

// Function props
onClick: () => void;
onChange: (id: number) => void;
onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;

// State setters
setState: React.Dispatch<React.SetStateAction<number>>;

// Children
children: React.ReactNode;        // anything renderable
element: React.JSX.Element;       // single React element only

// Style
style: React.CSSProperties;

// Dictionaries
dict: Record<string, MyTypeHere>;
```

---

## Hooks

### useState
- Let TypeScript infer simple types: `useState(false)` → `boolean`
- Explicitly type nullable or complex state: `useState<User | null>(null)`

### useCallback
- Always annotate callback parameters explicitly:
```typescript
const cb = useCallback((param1: string, param2: number) => { ... }, []);
```

### useReducer
- Use discriminated unions for action types with an explicit return type:
```typescript
type Action =
  | { type: "increment"; payload: number }
  | { type: "decrement"; payload: string };

function reducer(state: typeof initialState, action: Action): typeof initialState { ... }
```

### useEffect / useLayoutEffect
- Never implicitly return values from arrow-function effects (can accidentally return a timer ID etc.)
- Always use curly braces for the effect body

### useRef
- DOM refs: use the specific element type, initialize with `null`:
  `const divRef = useRef<HTMLDivElement>(null);`
- Mutable value refs: pass the initial value directly:
  `const intervalRef = useRef<number | null>(null);`
- Always null-check before accessing `.current`

### Custom hooks
- Use `as const` on tuple returns to preserve tuple type vs. union:
```typescript
return [isLoading, load] as const;
```

---

## Event Handlers

- Inline handlers: rely on contextual type inference (no annotation needed)
- Separate handler definitions: prefer left-hand typing with `React.ChangeEventHandler<El>`:
```typescript
onChange: React.ChangeEventHandler<HTMLInputElement> = (e) => { ... };
```
- For uncontrolled form submissions use `React.SyntheticEvent` with a type assertion on `e.target`
- `FormEvent` / `FormEventHandler` are deprecated in React 19 — use `SubmitEvent` / `SubmitEventHandler`

---

## Refs / forwardRef

- React 19+: `ref` is a standard prop — no `forwardRef` wrapper needed
- Expose an imperative handle type as a named export:
```typescript
export type CountdownHandle = { start: () => void };
const Countdown = ({ ref }: { ref: React.Ref<CountdownHandle> }) => {
  useImperativeHandle(ref, () => ({ start() { ... } }));
};
```

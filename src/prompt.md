# Task: Prune the AT-SPI UI tree into a compact, structured context

## Goal
The active-window tree is far too large for a model. A real sample was almost entirely unnamed `panel` wrappers, zero-size boxes and off-screen nodes, from the GNOME Shell overlay with an empty window title. Replace the string-based tree builder with a pipeline that builds **structured plain-data nodes**, prunes them with deterministic rules, and stores a compact serialized tree plus the node list in the shared `active_window`. A later stage will search this node list and send 2-3 candidates to a small model.

## Hard rules (do not break)
1. **Only the AT-SPI thread may call any `Atspi.*` function or touch an `Atspi.Accessible`.** The agent thread reads plain Python data (dicts, lists, strings) only.
2. Build and prune the tree **before** taking the lock. Assign the result under the lock. Never hold the lock while building, pruning, sleeping, printing, or calling a model.
3. Keep the existing threading design: shared `active_window` guarded by a lock/Condition, a version counter incremented on every change, a `stop_event`, an `atspi_ready` event, `daemon=True` on the AT-SPI thread, and a clean Ctrl+C shutdown.
4. Keep the existing thread names and logging format (`%(threadName)s` included).
5. Preserve current behavior for everything not mentioned here.

## 1. Build structured nodes (AT-SPI thread only)
Create a recursive builder that returns plain dicts, not strings:

```python
{
  "role": str,          # accessible role name, "unknown" if missing
  "name": str,          # stripped, "" if missing
  "desc": str,          # stripped, "" if missing or equal to name
  "states": set[str],   # state nicknames
  "bbox": (x, y, w, h), # screen coordinates, (0,0,0,0) on failure
  "path": tuple[int],   # child-index path from the window root, e.g. (0, 3, 1)
  "children": list
}
```

- Defaults: `max_depth=10`, `max_children=50` per node, and a **global node cap of 1500** visited nodes. Stop descending once the cap is hit and log a warning.
- Wrap each node's reads in try/except. On failure skip that node, never abort the whole tree.
- Return `None` for a node that cannot be read.

## 2. Prune deterministically
Implement `prune(node) -> list[node]`. A collapsed node is replaced by its children, so the return type is a list. Apply these rules in order:

1. **Visibility:** drop a node if `w <= 0` or `h <= 0`. Drop nodes entirely outside the screen rectangle. Fetch the screen size once in the AT-SPI thread or use a constant. Do not drop a parent solely because its own box is odd if its children are on-screen. Return the children instead.
2. **Showing state:** drop leaf nodes that lack both `showing` and `visible`. Never drop a container for this reason if it has surviving children.
3. **Collapse wrappers:** if a node has no name, no description, and its role is not in the interactive set, replace it with its pruned children.
4. **Drop empty leaves:** unnamed, non-interactive leaves are removed.
5. **Interactive set:** `push button`, `toggle button`, `menu`, `menu item`, `link`, `check box`, `radio button`, `tab`, `list item`, `text`, `entry`, `password text`, `combo box`, `tree item`, `terminal`. Keep these even without a name if they have a valid on-screen bbox.
6. **Dedupe repetitive siblings:** if more than 3 consecutive siblings share the same `(role, name)`, keep the first 3 and insert a marker node `{"role": "...", "name": "+N more"}`.

Log a count funnel per window activation: `raw nodes -> after visibility -> after collapse -> after dedupe`.

## 3. Serialize with ids
- Walk the pruned tree depth-first and assign each node a sequential `id` starting at 1.
- Produce two outputs:
  - `tree_str`: indented lines like `[12] push button 'Save' @(x,y,wxh) states=[focused]`. Include states only from this set: `focused, checked, selected, editable, expanded, sensitive`. Omit empty names.
  - `nodes`: a flat list of plain dicts `{id, role, name, desc, bbox, states, path, parent_id}` for later searching.
- Store `path` so the executor can re-resolve a node later in the AT-SPI thread. Do not store accessible objects anywhere shared.

## 4. Event handling
- On window activation, build, prune and serialize in the AT-SPI thread, then store under the lock:
  `active_window = {kind, app, title, role, tree=tree_str, nodes=nodes, version=n}`
- **Skip non-app windows:** if the title is empty, or the app is the shell or desktop compositor (for example `gnome-shell`), do not build a tree. Log the skip and leave `active_window` unchanged.
- On deactivation, only clear `active_window` when **both** app and title match the stored window and the title is non-empty. This avoids clearing on `None == None` or on same-title windows from different apps.
- On any build failure, store `tree=None` and `nodes=[]`, and log the exception. Never store error text inside the tree.

## 5. Agent thread
- Never call `Atspi.*`.
- Wait for readiness, then wait on the Condition with a short timeout. Copy `active_window` under the lock, release it, and process only when `version` changes.
- Processing: log the funnel result and print `tree_str` and the node count. Leave a clearly marked hook where the search and model stages will plug in.

## 6. Small fixes
- Use `%s` in logging calls, not `%exc`.
- Remove unused imports. Do not import the model package at module level.
- Use `.get()` for all event dict access.

## Acceptance criteria
- On a normal app window, the printed tree has **under ~80 nodes**. Every line has a role and either a name or an interactive role. There are no unnamed panel chains.
- Switching windows produces one "tree built" log line from the AT-SPI thread and one "processed" line from the agent thread per activation.
- Shell and empty-title windows are skipped with a log line.
- Searching the source confirms no `Atspi.` call exists inside the agent thread or any function it calls.
- No dbind errors on startup, and Ctrl+C exits cleanly.

## Output
Return the complete updated code in one block, followed by a short list of the pruning rules and the default limits so they are easy to tune.
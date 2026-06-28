## 2025-02-20 - Optimize redundant dictionary lookups in python loops

## 2026-06-07 - AsyncDBAPI Batch Execution Overhead
**Learning:** When executing multiple SQLAlchemy text statements sequentially (like a database bootstrap schema backfill) over an async connection, awaiting `conn.execute()` iteratively incurs Python async event loop context switching overhead for each query.
**Action:** Extract the loop into a synchronous helper function and pass it to `await conn.run_sync()`. This executes the iterative batch within the async context's worker thread via a single blocking DBAPI call, significantly reducing execution overhead (measured ~30% faster locally).

## 2026-06-06 - Missing OSError Coverage in test_email_parser.py
**Learning:** We need to explicitly mock built-in operations like `open()` to test generic exception types like `OSError` effectively, instead of relying solely on missing files to raise `FileNotFoundError` (which is a subclass, but might not trigger all handlers correctly if the code depends on string matching the exception or other side effects).
**Action:** When covering explicit `except OSError:` blocks, use `unittest.mock.patch('builtins.open', side_effect=OSError('...'))` to guarantee the exact exception type and message is raised for the test assertion.

## 2025-03-09 - O(n^2) nested loop optimization in thread_reply_candidate
**Learning:** `thread_reply_candidate` iterated over `any(...)` loop over all `ordered_messages` nested inside a loop over `ordered_messages`, resulting in a O(n^2) complexity.
**Action:** By looping backwards (reversed `ordered_messages`), the last external response date can be memoized, reducing the complexity to O(n). This dramatically increased the performance, taking 0.01s instead of 0.20s in my benchmark over 1,000 runs of 100 random messages.
## 2026-05-29 - Pre-compile Regex in network graph extraction
**Learning:** Found an inline regex compilation for `extract_emails` inside a frequently hit API endpoint (`/api/network/graph`) which is called on potentially thousands of records. Compiling regex repeatedly introduces measurable overhead.
**Action:** Pre-compile regex at the module level using `re.compile`. This optimization significantly improves the runtime speed by roughly 25% (as measured via timeit).
## 2026-06-01 - O(n^2) nested loop optimization in extract_reference_ids
**Learning:** `extract_reference_ids` and `assign_thread_id` used `not in list` to deduplicate email references resulting in an O(n^2) complexity over large headers.
**Action:** By keeping a `seen = set()` for O(1) lookups, the operation runs in O(n) time.
## 2025-05-30 - O(N^2) optimization in emails api and useMemo in frontend graph
**Learning:** `thread_matches_folder` in `get_emails` iterated through a thread's messages over and over again for `visible_groups` checking `if folder == "sent"`. Memoizing this lookup conditionally improved this behavior to O(N). Also, repeated maps and filters on render in the frontend can quickly become problematic, which is solved cleanly via `useMemo`.
**Action:** When filtering objects mapped iteratively, identify overlapping inner iterators (like checking for matching inner properties across items) and build them in a lookup dictionary ahead of time. In React, safely memoize constant properties built sequentially.

## 2025-02-12 - Prevent Blocking UI on Slow LLM Endpoints
**Learning:** In React components fetching both fast core data and slow AI-generated data concurrently inside `useEffect` (like `EmailDetail.tsx` waiting for LLM summarization), awaiting the slow request blocks the component from setting its fast core data state. This results in the user waiting artificially long for content that's already arrived.
**Action:** Always fetch the primary/fast core data first, set the core data state, and disable the top-level loading indicator immediately. Then, fire secondary/slow (LLM) promises without awaiting them in the primary render path, allowing them to independently update their own state placeholders when they complete.

## 2026-06-06 - Refactoring repetitive assert any loops
**Learning:** Repetitive single-statement `assert any(...)` calls can be cleanly refactored into an `expected_substrings` list that loops over assertions. When extracting strings to build the list, it's very helpful to use `re.sub()` to simultaneously capture strings via a replacer function while replacing the matches with placeholders, and then substitute the newly generated list block into the code.
**Action:** Always prefer lists and loops over repeated code structures when possible, maintaining test readability.

## 2026-06-07 - Redundant SHA256 Hashing during UniqueThread Deduplication
**Learning:** `create_unique_thread_intent` iterates over candidates twice to first extract lookups and fingerprint sets, and then iterates over them a second time inside `_find_matches_for_candidates` to match those lookups. This caused `candidate_strong_fingerprint(candidate)` (which performs a SHA256 encoding) to be redundantly executed twice per candidate.
**Action:** Extract expensive lookups (`candidate_strong_fingerprint` and regex normalizations) into dictionaries mapped by `candidate_key` during the first iteration to prevent redundant processing.

## 2025-06-09 - [Extract and Memoize List Items to Prevent Over-fetching]
**Learning:** React re-renders long lists entirely when the selected item changes if items are inline mapped. Even if the array length isn't massive (e.g. 50 items), the inline function instantiations and DOM reconciliation add up across the list.
**Action:** Always extract complex list items into isolated `React.memo` components, especially when selection state is hoisted to the parent component.
## 2024-06-10 - Resolve N+1 Lazy Loading Iteration Overhead in Worker Scripts
 **Learning:** In SQLAlchemy async sessions, if we execute `select()` and only grab the result scalars `configs = await session.execute(...); configs.scalars()` without calling `.all()`, and then we loop over that generator outside the `async with AsyncSession()` block, it evaluates lazily. For instances mapped with database relations or configurations this can lead to detached instance errors, or sequential individual I/O reads (N+1 equivalent overhead when the context isn't fully exhausted or mapped properly).
 **Action:** Always ensure the returned object list is fully materialized using `.scalars().all()` *inside* the `async with AsyncSessionLocal() as session:` block before passing it down or iterating over it.

## 2026-06-10 - Optimize redundant dictionary lookups in tight loops
 **Learning:** Using `dict.setdefault` and multiple `dict.get` or `key in dict` checks inside tight loops significantly impacts performance due to repeated dictionary lookups and unnecessary list allocations. Caching dictionary lookups (e.g., using a single `dict.get(key)`) and conditionally handling the logic based on the result is much more performant.
 **Action:** When aggregating or grouping items in a loop, avoid `setdefault`. Instead, check if the key exists using a single `.get()`, and perform initialization/updates conditionally. Additionally, hoist loop-invariant checks (e.g., `folder == "sent"`) outside the loop to avoid redundant evaluations.
## 2026-06-12 - defaultdict performance over setdefault inside loops
**Learning:** Using `dict.setdefault(key, []).append(val)` inside a loop allocates an empty list `[]` on every single iteration, even if the key already exists. This overhead adds up. `collections.defaultdict(list)` only invokes the `list` factory when a key is missing, which is measurably faster (~10% performance gain) and results in cleaner code.
**Action:** Always prefer `collections.defaultdict(list)` over `setdefault(key, [])` when populating a dictionary of lists in a tight loop.

## 2025-06-15 - Optimize O(n) email threading dictionary lookups with defaultdict
**Learning:** When organizing pre-sorted collections by groups, explicit dictionary membership and date tracking inside a tight loop creates unnecessary CPU overhead. Because SQL `ORDER BY` combined with Python sorting guarantees an oldest-to-newest ordering, tracking the 'most recent' item per group simplifies to blindly overwriting the dictionary key.
**Action:** Use `collections.defaultdict` for tracking accumulators (`int`, `list`) and take advantage of implicit data ordering to eliminate branch conditions and explicit `.get()` checks in grouping loops.

## 2026-06-19 - Batched COUNT aggregations using CASE
**Learning:** Sequential scalar `COUNT` aggregations using multiple database queries introduce significant network roundtrip latency in `get_data_quality_surface`. `asyncio.gather` on the same session is unsafe in SQLAlchemy, and standard `func.count(Model.id)` requires individual queries if not batched.
**Action:** When multiple independent counts are required from the same table, batch them into a single query using conditional aggregation (e.g., `func.count(case((condition, 1)))`).

## 2026-06-18 - Route heavy search reads to read replica
**Learning:** `backend/api/search.py` needs the primary database session for current provider and tenant configuration, but the heavy email and attachment search query can use the read-only session from `db.session.get_readonly_db`.
**Action:** Keep provider/config resolution on `Depends(get_db)` and route only the read-only search query through `Depends(get_readonly_db)` so search load moves to replicas without replica-lagging fresh configuration reads.

## 2026-06-19 - Email owner/date lookup index
**Learning:** Inbox and reply-wait queries commonly scope `email_records` by `user_id` and `organization_id` before ordering or filtering by `date`, so separate single-column indexes still leave the planner with avoidable sort/filter work.
**Action:** Keep `ix_email_records_owner_date` on `(user_id, organization_id, date)` in both the SQLAlchemy model and bootstrap backfill SQL when optimizing owner-scoped email timelines.
## 2024-05-18 - Optimize redundant tuple/string creation in dedupe loop
**Learning:** Instantiating new tuples and using f-strings inside a tight loop creates unnecessary allocations that impact performance, especially when checking dictionary membership where most items are already present.
**Action:** Inline lookup values directly, use early returns and `msg_id is not None` checks, and avoid generating formats like `f"<{normalized}>"` unless the basic `normalized` key wasn't sufficient, keeping inner loop bodies lean.

## 2026-06-20 - list.reverse() vs sorted() for database results
**Learning:** Re-sorting objects that were retrieved from a database query with `.order_by(...)` incurs unnecessary `O(N log N)` overhead. The lists can be reversed in-place in `O(N)` time to switch chronological order. In tight APIs and data processing paths, list copies and Python sorts should be avoided if ordering is implicitly guaranteed.
**Action:** Always prefer `list.reverse()` over `sorted(..., reverse=True)` or `sorted(..., key=...)` when reversing elements retrieved from a query that are already ordered by SQL.

## 2024-05-24 - Optimize WebDAV Project Folder Query
**Learning:** Found an N+1 query vulnerability / O(n) filtering bottleneck where `get_project_folders_from_db` loaded all project folders for a tenant just to filter for a single `folder_uid` in Python logic.
**Action:** When filtering database models by ID, always push the filtering logic to the database query layer (using `.where()`) rather than fetching the entire collection and filtering in-memory. This prevents memory bloat and speeds up queries significantly.

## 2026-06-20 - Optimize N+1 Query in ReplySlaScheduler Loop
**Learning:** Sequential await loops on query results cause N+1 query and execution blocking issues.
**Action:** Use asyncio.gather to concurrently process independent tasks instead of a for-loop await block to improve throughput significantly.

## 2026-06-24 - Defer large SQLAlchemy vector payloads
**Learning:** Mapping large `Vector(1536)` embedding columns as eager default loads inflates row payloads and network transfer for routine list/detail queries that do not need the vector values.
**Action:** Mark large embedding columns with `deferred=True` when callers rarely need them by default, and use explicit undefer/loading options only in code paths that intentionally consume embeddings. Avoid describing this as an N+1 fix; deferred columns can create extra SELECTs if accessed later in a loop.

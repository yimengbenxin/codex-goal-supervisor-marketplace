# Architecture Selection

Select architecture from the business loop, not from an Agent framework's
feature list.

## Required Questions

1. What exact event starts the Agent?
2. What observable output ends one successful run?
3. What state must survive process restart?
4. Which information must be retrieved by exact identifier?
5. Which information must be retrieved by meaning?
6. What is the smallest real acceptance that distinguishes a useful Agent from
   a runnable shell?
7. Which process, user, or downstream system consumes each output?

## State Choice

| Evidence | Smallest suitable mode |
| --- | --- |
| Complete request in, complete response out | `stateless` |
| Long job needs pause/resume | `checkpoint` |
| Structured jobs, versions, audit rows, or local records | `sqlite` |
| Exact names, IDs, paths, symbols, or controlled vocabulary | `keyword` |
| Paraphrased questions across unstructured material | `vector` |
| Exact identity and semantic similarity are both acceptance requirements | `hybrid` |

If two designs both appear plausible, build a task-specific retrieval fixture
and compare answer evidence, latency, update cost, and operational complexity.
Do not choose from a generic benchmark alone.

## Runtime Choice

Prefer the runtime already used by the verified business loop. Change runtimes
only when the target environment, distribution contract, or required adapter
cannot be satisfied otherwise. A portable blueprint may have several adapters;
the first release should implement only the requested one.

## Rejection Conditions

Reject a candidate when it duplicates an already working local capability,
requires a broader runtime than the product needs, has incompatible terms,
cannot pass the business acceptance, or costs more to adapt than the rework it
avoids. Record the evidence rather than a generic preference.

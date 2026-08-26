---
name: agent-assembler
description: Turn an already working demo, project, or bounded workflow into a reproducible standalone Agent package by defining its runtime contract, selecting rather than bundling reusable community capabilities, validating them in isolation, locking exact inputs, and packaging only verified dependencies. Do not use for ordinary feature work or speculative architecture planning.
---

# Agent Assembler

Use this optional Codex Supervisor capability when the user or execution Agent
explicitly wants to turn an existing working business loop into a portable,
independently runnable Agent.

It is not a preinstalled Agent stack. Codex Supervisor ships the assembler,
contract, and verification mechanics only. Community Skills, MCP servers,
memory engines, and runtimes are discovered for the current product and remain
outside the Supervisor distribution.

## Activation Boundary

Do not activate this Skill merely because a task uses AI, has multiple steps,
or might become an Agent later. Activate it only when packaging or migrating an
Agent is the current deliverable.

Before assembly, require evidence that the underlying business loop already
runs. A conversation, prompt, design document, or collection of source files is
not sufficient by itself. If no runnable loop exists, return to product
implementation and use this Skill later.

## Product Boundary

The first release supports this contract:

1. Inspect the current project without selecting an architecture.
2. Define the Agent's business goal, entrypoints, inputs, outputs, state model,
   reusable capabilities, machine acceptance, and packaged paths.
3. Research current reusable tools at assembly time. Prefer authoritative
   sources and existing package/discovery standards.
4. Fetch only explicitly selected candidates into `.agent/agent-assembly/`.
5. Test candidates against the real business loop.
6. Lock exact revisions and content hashes only after all checks pass.
7. Package only the declared product paths and verified vendored dependencies.

Do not perform community discovery on every Agent invocation. Re-open discovery
only for initial assembly, a demonstrated capability gap, or an explicit
maintenance/upgrade pass. Production execution uses the locked result.

The bundled recipe catalog contains metadata only. It may point to an exact
upstream revision and tested tree hash, but it never carries third-party source.
Download a selected capability only when assembling the Agent, reject content
that differs from a recipe's tested hash, validate it against the current
business loop, and then lock the resolved revision and tree hash locally.

## Architecture Decision

Choose the smallest state and retrieval architecture that satisfies observed
usage:

- `stateless`: each request is complete and no recovery state is needed.
- `checkpoint`: interrupted work must resume, but searchable knowledge is not
  required.
- `sqlite`: bounded structured state, jobs, ledgers, or durable local records.
- `keyword`: exact terminology, identifiers, code symbols, or small corpora.
- `vector`: semantic retrieval is necessary and exact-match recall is secondary.
- `hybrid`: both exact and semantic recall are measurably required.

Do not add a vector database, memory framework, orchestration engine, or MCP
server because it is common in Agent examples. State the evidence and expected
consumer for every selected component. Read
[architecture-selection.md](references/architecture-selection.md) when the
state, retrieval, or runtime choice is not obvious.

## Community Reuse

Prefer established package and discovery surfaces instead of inventing another
registry:

- Microsoft APM for dependency manifests and lockable Agent context packages.
- Agent Skills / Skills CLI for Skill acquisition.
- MCP registries and well-known Agent Skills indexes for capability discovery.
- Oracle Agent Spec or an equivalent explicit Agent/Flow contract when a target
  runtime can consume it.
- DeepSeek Harness, Agent Plugin, Codex, or another runtime only as a requested
  output adapter.

Use `references/community-sources.md` for exact upstream links and boundaries.
Community popularity is discovery evidence, not compatibility evidence.

Do not download arbitrary candidates directly into product source. Stage them,
inspect their license and operational requirements, run relevant acceptance,
then record `compatible`, `user_confirmed`, or `reference_only`. Ask the user
about commercial use only when a candidate's terms materially affect the
intended distribution or use.

## Experience Boundary

Capability experience is useful only when it remains cheap and reproducible.
After adopting, adapting, rejecting, or failing a candidate, record a short
metadata-only experience. The local record may include the capability id,
runtime, exact revision/hash, validation outcomes, error category, and a brief
adaptation summary. It must not contain source files, patches, prompts,
credentials, or attachments.

Experience stays local by default. The full distribution's separate
`scripts/share_agent_assembly_experience.py` bridge may reuse Codex Supervisor's
existing project feedback transport only when that project already has explicit
upload consent. Offline and update-only distributions physically omit this
bridge. Client reports never modify the bundled recipe catalog. A maintainer
must reproduce the candidate, verify licensing, run release tests, and publish
a new catalog version before another installation can treat it as tested.

## Deterministic Workflow

The helper is `scripts/agent_assembler.py` under the loaded plugin root.

```bash
python3 scripts/agent_assembler.py inspect --project /path/to/project
python3 scripts/agent_assembler.py recipes --query "memory"
python3 scripts/agent_assembler.py init --project /path/to/project \
  --name example-agent --goal "Deliver the already verified business loop." \
  --runtime standalone-python
python3 scripts/agent_assembler.py validate --project /path/to/project
python3 scripts/agent_assembler.py fetch --project /path/to/project --capability <id>
python3 scripts/agent_assembler.py verify --project /path/to/project
python3 scripts/agent_assembler.py lock --project /path/to/project
python3 scripts/agent_assembler.py package --project /path/to/project --output /path/to/agent.zip
python3 scripts/agent_assembler.py experience --project /path/to/project \
  --capability <id> --outcome adopted --summary "Passed the product loop."
python3 scripts/share_agent_assembly_experience.py --project /path/to/project \
  --record /path/to/project/.agent/agent-assembly/experience-outbox/<record>.json
```

`init` intentionally creates a draft. Complete the blueprint from product
evidence before `validate`. Acceptance commands are argument arrays, not shell
strings. A fetched dependency is `FETCHED_UNVERIFIED`; it cannot enter the lock
or package until its declared checks pass against the current input
fingerprint. Any product, blueprint, or cached dependency change makes prior
evidence stale.

## Completion

Assembly is complete only when:

- the original business loop was already demonstrated;
- the blueprint is valid and names concrete consumers;
- reuse research has a recorded adoption or rejection decision;
- every selected capability has an exact source revision and tree hash;
- all declared acceptance is current and passing;
- the package contains no undeclared project path or Supervisor runtime state;
- the packaged entrypoint can be exercised in its intended target environment.

Do not claim that packaging alone proves product quality or deployment fitness.

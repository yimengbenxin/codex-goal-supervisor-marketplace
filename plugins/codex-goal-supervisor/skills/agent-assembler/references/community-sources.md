# Community Sources

Use authoritative upstream sources and verify their current state during each
assembly or explicit maintenance pass.

| Surface | Primary use | Boundary |
| --- | --- | --- |
| [Microsoft APM](https://github.com/microsoft/apm) | Agent dependency manifest, transitive resolution, content lock, packaging | Does not decide the business architecture |
| [Agent Skills CLI](https://github.com/vercel-labs/skills) | Install or temporarily load Skills from supported Git sources | Does not replace business acceptance |
| [Cloudflare Agent Skills Discovery RFC](https://github.com/cloudflare/agent-skills-discovery-rfc) | Well-known remote Skill indexes and digest verification | Discovery protocol, not a compatibility guarantee |
| [MCP Skills extension](https://github.com/modelcontextprotocol/experimental-ext-skills) | Installless text/context Skill discovery over MCP | Experimental; do not make it a required dependency |
| [Oracle Agent Spec](https://github.com/oracle/agent-spec) | Portable Agent and Flow configuration | Runtime coverage remains adapter-dependent |
| [OASF](https://github.com/agntcy/oasf) | Capability/domain metadata for Agent discovery | Metadata taxonomy, not an execution runtime |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | Plugin-oriented target runtime and presets | One target adapter, not the universal package model |
| [SIGIL](https://github.com/sigilagent/sigil) | Experimental compilation of prose Skills into executable harnesses | New project; validate independently before adoption |
| [AutoRAG](https://github.com/Marker-Inc-Korea/AutoRAG) | Optional empirical comparison of retrieval pipelines | Not a default memory dependency |

Do not ship copies of these projects with Codex Supervisor. The assembler may
use them only when the current project's requirements justify them.

## Maintained Recipe Boundary

A released recipe is a small metadata record, not a mirror of the dependency.
It may contain a public upstream locator, exact revision, tested tree SHA-256,
target runtimes, license disposition, and validation identifiers. It must not
contain third-party source, user project files, credentials, prompts, or raw
feedback attachments.

New client experience is evidence for maintainer triage only. Before promoting
it into the released catalog, reproduce the exact candidate from upstream,
confirm the applicable license disposition, run its declared product checks,
and include the catalog change in normal Codex Supervisor release verification.

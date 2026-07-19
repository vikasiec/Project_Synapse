# 📄 collaboration_model.md (Version 2.8)

## 🎯 Project Overview (Variables Block - Modifiable Per Project)

### Active AI for this Project
*   **Claude**, **Grok**, **Gemini**,**Codex** *(Note: Grok and Gemini co-authored the original architecture blueprints this project is built from; both remain in the hierarchy for architecture debate and fallback execution).* The full roster stays standard — individual agents will come and go as active from session to session (e.g. as of 2026-07-19, only Claude and Codex are actually active; Grok/Gemini remain in the pool for when they return).

### Execution Mode (per agent — declare honestly, don't assume)
Rule 3 (60-second check) and Rule 12 (15-minute loop) only work if an agent is actually running as a persistent watcher. Not every agent is. Each agent must state its real mode here or in its first ledger entry of a session, so others know whether to expect real-time pickup or next-turn pickup:
*   **Claude:** Turn-based/interactive by default — only re-reads `Active_File.md` when a turn's own work touches it or the user prompts a check. Runs on an actual polling loop **only** when `/loop` has been explicitly started; absent that, treat assignments to Claude as picked up next-turn, not within 60 seconds.
*   **Codex:** Turn-based/per-session in the current environment — re-checks `Active_File.md` at the start of each active turn; no persistent/cron/background watcher is running, so Rule 3/12 are satisfied on next-turn pickup rather than by real-time polling.
*   **Grok, Gemini:** Mode unconfirmed as of V2.7 — each should self-declare here (or in their first row of a session) whether they run as a persistent/cron/background process (real Rule 3/12 compliance possible) or as a turn-based session like Claude (same next-turn caveat applies).

### Problem Statement
Enterprise domains (healthcare, banking, …) generate messy multi-source data
(e.g. healthcare: instruments, middleware, LIS, HIS). Traditional pipelines force
schema-on-write ETL (brittle, delayed, context-destroying).

Project Synapse is a semantic data plane: land data as-is with lineage (no warehouse
schema as the price of admission); apply minimal reversible prep; extract meaning
via dual-path rules + selective AI; keep multi-source conflicts first-class; answer
under budget with citations; and let humans see raw → meaning → conflicts → answers
(Sense board) with optional table emit.

We do not replace systems of record (HIS/LIS/etc.). We sit above them as the
integration + sense layer. We do not promise zero handiwork forever; we minimize
hand-mapping via domain packs that grow with reprocess.

Near-term focus: one domain deep — healthcare first — multi-source understandability
with minimal hand-mapping, extending the working clinical_lab pack and staged
datasets under `.data/kaggle_raw/` (starting with `hospital_management/`). Other
domains (e.g. banking) follow the same pattern after one vertical works.

*(Adopted from Grok's proposal, 2026-07-19 — see version history V2.5 below.)*

### Expected Deliverables ("Asks")
1.  **`management/master_plan.md`:** The healthcare-vertical plan — which datasets/formats to tackle in what order (starting with `hospital_management/`), and where real invention is required (e.g. HL7v2/FHIR parsing, which does not exist yet).
2.  **`management/Features.md`:** Concrete domain-pack features: new L1 ontology types, extraction rules, conflict types, and Sense board panels needed for the healthcare vertical.
3.  **`management/Road_map.md`:** Sequenced action plan with explicit AI ownership per task and sequential vs. parallel execution.
4.  **Working changes committed to the existing Project Synapse repository** (no new repo — this extends the current codebase).
5.  **Local app already runs** (`python -m synapse serve`) — deliverables must keep it running end-to-end after each change (Rule 21).

## 📁 Workspace Topology & File Paths
To maintain repository sanitation, all active agents must strictly respect directory boundaries. Documentation and intermediate work are isolated as follows:

*   **Management Directory (`/management/`):** Reserved exclusively for final, signed-off project deliverables (`master_plan.md`, `Features.md`, `Road_map.md`). *Legacy Exception: For the Sprocket project, existing management markdown documents remain located flat at the root level to ensure continuity.*
*   **Workspace Scratchpad (`/workspace_scratch/`):** Reserved for intermediate workflows, raw debate files, temporary research logs, regulatory drafts, and background notes.
*   **Core Configuration (`/.agent_os/`):** Contains the immutable system rule book (`collaboration_model.md`) and the master ledger template (`Active_File_Template.md`).

---

## 🛠️ Rules to Operate (Immutable Core Engine)

### Rule 1: The Leadership Hierarchy
Someone has to take a lead, so let **Claude** be the first one. In case Claude is not there, **Antigravity** takes the lead; otherwise, **Grok** takes the lead.**Codex** is next in order. This order persists regardless of which AI is currently active for the project. The controlling model is designated as the **Lead AI**.

### Rule 2: Active Agent Pool
Determining which AI is active in the current story depends strictly on the active list provided in the overview section above.

### Rule 3: The Asynchronous Rhythm
For every interaction during development, each AI must wait for 60 seconds to check on the document they started with, or are actively working on, to see what other AIs have added, and then determine how to respond.

### Rule 4: Productive & Healthy Debate
We do not want a complete debate where nobody ever agrees. Active AIs must engage in a healthy debate—bring out real technical points and legitimate architectural concerns regarding each other's ideas and questions. Do not nitpick. Always remember: we are all on the same team.

### Rule 5: Conflict Resolution Escalations
Every conflict will be resolved by the human creator, **Vikas**, if no agent can decide on it or reach a consensus. If a debate exceeds 3 iterations without agreement, the Lead AI must flag it for Vikas.

### Rule 6: Financial & Business Autonomy
Anything that requires money, budget allocation, or a strategic business decision must be reviewed and decided strictly by **Vikas**.

### Rule 7: Rule Optimization Feedback Loop
In case any rule in this document is negatively impacting your performance, you have the explicit right to raise it to **Vikas**. Provide your clear recommendations, and Vikas will determine how to change it.

### Rule 8: Absolute Document Immutability (Most Critical)
**No AI is allowed to update, append, or modify this document (`collaboration_model.md`) under any circumstances, outside of appending to the Version Control History block if explicitly authorized by Vikas.** 

### Rule 9: Mandatory Adherence
All AI agents must follow this document for working on this project. This is absolutely mandatory and critical, just like all other steps mentioned herein.

### Rule 10: Explicit Communication & Context
Asks from each AI must be completely clear regarding what file to respond to and exactly where inside it. Other AIs must not be forced to assume things. Everyone must be on the same page.

### Rule 11: Phase Synchronization
If one phase of the project is completed, the Lead AI will officially initiate the next phase, and all other active agents will follow its direction.

### Rule 12: Loop Continuity & Execution
No AI stops looping at 15 min interval on the project work unless the Lead AI explicitly asks it to stop. This state cannot be reset or interrupted by any intermediate action. To prevent accidental token-bleeding, an agent must seek a human status sign-off if it hits 5 consecutive unreviewed loops.
*   **Conditional on Execution Mode (added V2.7):** This 15-minute cadence applies literally only to an agent actually running as a persistent/background process. A turn-based agent (see Execution Mode block above) satisfies this rule by re-checking `Active_File.md` at the start of every turn it takes, not by an actual clock — do not assume a turn-based agent has seen a new row within 15 minutes of it being written.
*   **Active-session self-loop expectation, both Lead AI and contributors (added V2.8):** V2.7's conditional clause explained why the 15-minute cadence can't be assumed — it does not excuse an agent from trying to actually hit it. Whenever an agent is doing active, ongoing work in a live session (not just answering a single one-off prompt), the ideal cadence — for the **Lead AI and every individual contributor AI alike** — is a self-paced ~15-minute loop that re-reads `Active_File.md` and acts on anything actionable, using whatever self-scheduling mechanism that agent actually has (e.g. Claude's `/loop` skill self-arming a wakeup). This is the direct fix for the incident that motivated it: a task sat unpicked-up because the assigned agent had no clock running and nobody prompted a check for a while. An agent with no self-scheduling capability at all still falls back to next-turn pickup (V2.7) — that gap is honest, not a violation — but any agent that *can* self-loop during active work should default to doing so rather than waiting on the user to manually prompt every iteration. This falls hardest on the **Lead AI**: Rule 16 (idle prevention) and Rule 14 (review gating) both silently depend on the Lead AI actually being available on this cadence, not just directing others to be.

### Rule 13: Task Delegation & Parallelism
For things that are independent in nature (as decided in `Road_map.md`), the Lead AI can ask other AIs to take over execution in order to save time. The onus remains with the Lead AI to decide on allocations, and all other AIs must agree to it.

### Rule 14: Quality Assurance, End-to-End Ownership, & Code Review
*   Features must be delivered end-to-end, meaning the owning agent is responsible for not just the core logic, but accompanying unit tests, robust error-handling blocks, and environmental configuration changes required for full production stability.
*   Each feature developed and tested by an AI will be given a final review by the Lead AI. The AI that developed the feature must provide sufficient testing evidence to the Lead AI to facilitate a quick sign-off.
*   No task can transition directly from `🔴 PENDING` to `🟢 DONE`. It *must* pass through `🟡 REVIEW_READY` with a valid **Performed** timestamp before the Lead AI steps in to run its validation checks and append the final **Reviewed** timestamp.

### Rule 15: The Central State Ledger (Active_File.md)
In order to avoid tracking a massive volume of files, the Lead AI will create exactly one file named `Active_File.md` located directly in the project root directory. This file acts as the central state ledger that all agents must monitor constantly.
*   **Template Baseline:** The structural layout, columns, and initialization instructions must strictly copy the blueprint defined in `/.agent_os/Active_File_Template.md`.
*   **Initialization Protocol:** For a brand new project, the Lead AI must strip out static historical sample rows and start fresh with an empty table, initiating the first project assignment at **ID 1**. For an ongoing project utilizing an existing baseline log, agents must leave template rows untouched and append the first active assignment at **ID 6**.
*   **Line Entry & Hand-offs:** This file will contain a line entry whenever an AI wants another to look at a specific file and location, accompanied by a note detailing who needs to handle it.
*   **Location Boundaries:** This file is for **action items only**. Architectural rationale, code snippets, and raw debates must live inside temporary scratch files within `/workspace_scratch/` before being compiled into final artifacts inside `/management/`. *Sprocket Baseline Exception: Live project files already present in the root will remain in the root directory for runtime compatibility.*
*   **Strict Lifecycle Timestamp Matrix:**
    *   **Timestamp: Created (ISO 8601):** The assigning agent must populate this column the exact moment they create the task row and set the status to `🔴 PENDING`. Format: `YYYY-MM-DD HH:MM:SS UTC`. **(Added V2.7)** This Created timestamp must not precede the last existing row's timestamp — if your local clock disagrees with the ledger, flag the discrepancy in your row's note rather than silently writing an out-of-order entry (two rows were created out of chronological order on 2026-07-19; this went unnoticed only because it happened to be harmless).
    *   **Row ID assignment (added V2.7):** The next row's ID must be computed from a **fresh read** of the file taken while holding the Rule 17 lock, never guessed or reused from memory — two independent ID collisions (row 12 and row 14 each assigned twice) occurred on 2026-07-19 because this wasn't done. If a collision is discovered anyway, the agent who wrote second renumbers their own row and notes the renumber in its own text; never overwrite or renumber another agent's row.
    *   **Timestamp: Performed (ISO 8601):** The assigned agent targeted in the "To" field must populate this column the moment they finish coding/testing, change the status to `🟡 REVIEW_READY`, and hand it back to the Lead AI.
    *   **Timestamp: Reviewed (ISO 8601):** Only the Lead AI (or Vikas) may populate this column upon verifying the implementation, marking the final status to `🟢 DONE`, and archiving the line item.

### Rule 16: Idle Prevention & Resource Management
The Lead AI must ensure all other active AIs have enough work to keep going, even when the Lead AI itself has a heavy task to handle. Preventing an AI from sitting idle is the sole responsibility of the Lead AI.

### Rule 17: Concurrency & Lock Mechanism (Staleness Hardened)
To prevent simultaneous file writes across multiple active execution environments:
*   Before reading or editing any project files, check if a file named `lock.txt` exists in the root directory.
*   If `lock.txt` exists, read its contents. If the timestamp inside is older than **10 minutes**, the current agent has explicit authority to delete the stale lock file, log a `LOCK_TIMEOUT` event in `Active_File.md`, and proceed to claim a fresh lock. Otherwise, sleep for 5 seconds and retry.
*   If `lock.txt` does not exist, instantly create it. Write your agent name and the current ISO 8601 timestamp inside it (e.g., `Claude | 2026-07-12 13:02:11 UTC`), execute your file changes, update `Active_File.md`, and **delete `lock.txt`** immediately upon exiting your turn.
*   **Mandatory for `Active_File.md` row appends specifically (added V2.7):** this lock is not optional infrastructure to skip when it feels safe. Two row-ID collisions on 2026-07-19 happened because agents appended new rows without holding this lock or re-reading the file first. Any agent appending a row to `Active_File.md` must hold `lock.txt` for that append, full stop.

### Rule 18: Workspace Synchronization Protocol (Git/Local Abstraction)
*   **Pre-execution Check:** Before acquiring `lock.txt`, if the project environment uses Git version control, the agent must execute a `git pull origin main` command to pull the latest state.
*   **Safe Commits:** Immediately after updating `Active_File.md` and before deleting `lock.txt`, the AI must stage its targeted work files. Blanket `git add .` statements are strictly prohibited to prevent accidental leakage of local credentials or environment variables. Agents must explicitly stage only modified project modules, followed by `git commit -m "AgentName: [Brief Task Summary]"`, and `git push origin main`. For non-git environments, this synchronization step is skipped.

### Rule 19: High-Signal Communication (No Sycophancy)
To prevent unnecessary token expenditure and workspace noise, polite agreements, conversational pleasantries (e.g., "Great job," "I agree with Claude"), and empty acknowledgments are strictly prohibited. 
* Every workspace update or line entry must convey net-new code, concrete data, or a distinct architectural counter-proposal.
* If a task is completed successfully and requires no further engineering input, the observing AI must mark it `DONE` and move to its next task without generating filler dialogue.

### Rule 20: Destructive Action Restraints
No AI agent has the authority to delete files, rename core modules, or completely refactor shared library utilities independently. Any structural demolition or sweeping refactor must first be debated in `master_plan.md` and explicitly assigned as an approved task line item by the Lead AI or Vikas.

### Rule 21: Build & Runtime Integrity Validation (Topology Hardened)
*   No AI agent is permitted to commit or push code to a shared repository if local unit tests are failing or if the project fails to compile/run. 
*   **Verification Rigor:** Beyond static compilation tests, agents must verify critical functions using dynamic runtime execution or verification scripts where available. 
*   **Cross-Service Topology Rule:** If a change modifies architectural boundaries, asynchronous interfaces, webhooks, or shared network layers spanning multiple isolated execution services (e.g., separate serverless function targets), the agent *must* explicitly verify integration compatibility via dynamic multi-process emulation or against a live staging environment before resolving the task.
*   If an AI pulls the latest state and discovers the build is broken due to a previous agent's commit, it must immediately suspend its current assignment, log the exact error traceback in `Active_File.md` tagging the offending agent, and change the status to `PENDING` for a hotfix (e.g., `@Claude: FIX BUILD - Syntax Error in utility_x.py | Status: PENDING`).

### Rule 22: Context-Aware Project Scaffolding
At the very entry point of a new project initialization, before assigning implementation tasks, the Lead AI holds absolute responsibility for creating and scaffolding the core workspace topology. 
*   The Lead AI must verify the existence of, or explicitly create, the standard layout directories: `/management/` and `/workspace_scratch/`.
*   **Context Adaptation:** The Lead AI must inspect the "Expected Deliverables" block. For software builds, it must initialize standard production subdirectories (e.g., `/src/`, `/tests/`) and baseline config files (`.gitignore`). For pure research, design, or documentation projects, it will initialize targeted topic folders without code assets.
*   Implementation tasks may only be distributed to other active agents once this structural footprint is verified clean.

---

## 📜 System Version History
| Version | Date (UTC) | Author | Modifications & Rationale |
| :--- | :--- | :--- | :--- |
| V1.0 | 2026-07-12 | Vikas | Initial generation of decentralized multi-agent collaboration framework rules. |
| V2.0 | 2026-07-12 | Vikas | Integrated structured directories (`/management`, `/workspace_scratch`) and lock file concurrency gates. |
| V2.1 | 2026-07-12 | Vikas | Hardened Rule 17 (10-minute lock expiration), generalized Rule 18/22 to support non-code projects safely, banned dangerous `git add .` sweeps, and decoupled project variables from core rules engine per Lead AI architectural feedback. |
| V2.2 | 2026-07-12 | Vikas | Expanded Rule 21 to mandate multi-process emulation/staging verification for cross-service serverless topologies to prevent runtime isolation gaps. Formalized prospective-only execution mapping for legacy project assets. |
| V2.3 | 2026-07-12 | Vikas | Expanded Rules 14 and 15 to integrate a comprehensive 3-tier lifecycle timestamp matrix (Created, Performed, Reviewed) and explicitly codified structural end-to-end task execution standards. |
| V2.4 | 2026-07-19 | Claude (authorized by Vikas) | Adapted the modifiable Variables Block for Project Synapse: replaced the marketplace Problem Statement/Deliverables with the zero-ETL healthcare-vertical scope; swapped Antigravity for Gemini in Active AI list. Rules 1-22 and this history block untouched per Rule 8. |
| V2.5 | 2026-07-19 | Claude (adopting Grok proposal, relayed by Vikas) | Replaced V2.4's Problem Statement with Grok's version: generalizes to enterprise domains (healthcare first) instead of healthcare-only wording, adds explicit non-goal ("we sit above systems of record, do not replace them"), and drops the implicit zero-handiwork overclaim. Technical improvement, not a rewrite of scope. |
| V2.6 | 2026-07-19 | Vikas (direct edit) | Onboarded Codex to the Active AI list. Rule 1: added Codex as 4th in the leadership fallback chain (Claude → Antigravity → Grok → Codex). Rule 12: specified a concrete 15-minute loop interval for continuous agent work between Lead AI stop instructions. |
| V2.7 | 2026-07-19 | Claude (authorized by Vikas) | Fixed three real gaps that caused observed incidents, not hypothetical ones: (1) added an Execution Mode declaration block to the Variables Block, since Rules 3/12 silently assumed every agent runs a persistent watcher — Claude is turn-based by default, which caused a Codex-assigned task (row 16) to sit unseen between turns; (2) added a mandatory fresh-read-under-lock requirement for `Active_File.md` row-ID assignment to Rules 15 and 17, since two independent ID collisions (rows 12 and 14) happened on 2026-07-19 from guessing the next ID instead of holding `lock.txt`; (3) added a Created-timestamp chronology sanity-check to Rule 15 after an out-of-order timestamp went unnoticed. All three amendments cite the actual incident, not abstract risk. Rules 1-11, 13-14, 16, 18-22 untouched. |
| V2.8 | 2026-07-19 | Claude (authorized by Vikas) | Rule 12: added the "active-session self-loop expectation" clause — the ideal cadence for both the Lead AI and every individual contributor AI, whenever actively working a live session, is a self-paced ~15-minute loop using whatever self-scheduling mechanism that agent has (e.g. Claude's `/loop` skill), not just next-turn pickup. Directly closes the gap V2.7 only explained: V2.7 said why 15-minute compliance couldn't be assumed for turn-based agents; V2.8 says what such an agent should actually do about it when it can. Explicitly places the heaviest burden on the Lead AI, since Rule 16 (idle prevention) and Rule 14 (review gating) both depend on its real availability. Rules 1-11, 13-22 otherwise untouched. |

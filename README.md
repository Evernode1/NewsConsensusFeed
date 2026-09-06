# NewsConsensusFeed

A reusable, permissionless **multi-source fact-consensus oracle** for GenLayer. Anyone poses a
plain-language factual question together with several independent, caller-supplied news-source
URLs. Any GenLayer validator committee can then verify the question against the sources through
real consensus, and any other contract — a prediction market, a parametric-insurance contract, a
DAO — can permissionlessly read the resulting verdict without running its own fetch/LLM pipeline.

This is a **primitive**, not an app: it never settles money and never judges a single caller's
own content. It only ever answers "is this claim about the world true, false, or disputed, given
these independent sources?" — a question many unrelated contracts need answered the same way.

## Why this differs from a "thin LLM wrapper"

- **Fetch availability is decided in code.** A source that fails to load is force-classified
  `UNAVAILABLE` before the model ever sees it — it is never asked to guess about a page it
  couldn't read.
- **The aggregate verdict is decided in code, not by the model.** The model's only job is a
  per-source categorical classification (`SUPPORTS` / `CONTRADICTS` / `UNRELATED`). Turning those
  into `RESOLVED_TRUE` / `RESOLVED_FALSE` / `DISPUTED` is a fixed quorum rule implemented as a
  pure function, `_apply_quorum`, with unit tests in `tests/test_quorum.py`.
- **A round with insufficient evidence never overwrites a prior verdict.** If too few sources
  were fetchable or too few agreed to reach the quorum, the query's `status` is left exactly as
  it was — an evidence-starved round can't flap a resolved question back to uncertain.
- **Disagreement is a first-class outcome, not noise to average away.** If both `SUPPORTS` and
  `CONTRADICTS` clear the quorum, the query resolves to `DISPUTED` rather than picking a side —
  genuinely contested claims should read as contested.
- **Every URL is validated and SSRF-hardened before it is ever stored or fetched** (scheme,
  length, no embedded credentials/control characters, no localhost/private/link-local/reserved
  hosts, no known URL-shortener/redirector hosts).

## Consensus flow

1. `create_query(question, category, source_urls, min_agree_quorum)` — anyone opens a query with
   3–7 independent source URLs and a quorum (≥2, ≤ source count) required to resolve it. Optional
   native-currency funding seeds the query's own keeper-reward pool.
2. `add_source(query_id, url)` — the creator may grow the source set later (news coverage grows
   over time), up to 7 sources total. Existing sources/results are never touched.
3. `check_query(query_id)` — permissionless, cooldown-gated (6h). Every validator independently
   fetches every source URL and classifies its stance via `gl.eq_principle.prompt_comparative`.
   The code then applies the quorum rule:
   - `supports ≥ quorum` and `contradicts == 0` → `RESOLVED_TRUE`
   - `contradicts ≥ quorum` and `supports == 0` → `RESOLVED_FALSE`
   - `supports + contradicts ≥ quorum` (but neither side clean) → `DISPUTED`
   - otherwise → unchanged (insufficient evidence this round)

   A round whose evidence was sufficient to apply the rule pays a small keeper reward from the
   query's fee pool to whoever called `check_query`.
4. `get_query` / `get_source_results` / `list_queries` — permissionless reads any consuming
   contract or frontend can use.

## Files

- `NewsConsensusFeed.py` — the contract.
- `tests/test_quorum.py` — fast, dependency-free unit tests for the code-enforced quorum rule
  (`_apply_quorum`). Installs a minimal stand-in for the `genlayer` package so the file can be
  imported and its pure logic exercised without a GenLayer Studio/Docker environment. Run with
  `pytest tests/test_quorum.py -v`.

## What isn't covered here (by design)

Full behavioural tests of `create_query` / `check_query` / `add_source` — including the real web
fetch and the real `gl.eq_principle.prompt_comparative` consensus round — belong in `gltest`
direct/integration tests against an actual GenLayer Studio instance, per
[docs.genlayer.com/developers/decentralized-applications/testing](https://docs.genlayer.com/developers/decentralized-applications/testing).
This submission focuses its automated tests on the one piece of logic that is fully
deterministic and dependency-free: the quorum rule itself.

## Example use cases downstream contracts can build on

- A prediction market settling "did event X happen by date Y?" by reading `get_query(...).status`
  instead of re-implementing its own oracle.
- A parametric insurance contract gating a payout on a `RESOLVED_TRUE`/`RESOLVED_FALSE` verdict
  about a real-world event.
- A DAO or grants program requiring a `DISPUTED`-free verdict before treating a claimed
  milestone/news event as settled.

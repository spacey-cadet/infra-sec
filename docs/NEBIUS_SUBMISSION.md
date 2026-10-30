# Nebius x NVIDIA submission kit (deadline Oct 30, 8:00 pm Nairobi time)

## Disclosure

This submission was run end to end against NVIDIA-hosted Nemotron (base URL
`https://integrate.api.nvidia.com/v1`), not Nebius Token Factory. Token Factory is the
default endpoint in the code, but I could not create a verified account in time, so I
have no live Token Factory run to show. I'm submitting anyway so the integration can be
judged, and I understand it may not meet the Nebius requirement.

## Checklist (from the official Devpost page)
- [ ] Runs on Nebius Token Factory: NOT MET (ran on NVIDIA-hosted Nemotron, see Disclosure)
- [ ] Track chosen: Coding and Agentic Engineering
- [ ] Project description (adapt devpost-submission.md)
- [ ] Working demo URL (see note below)
- [ ] Public YouTube video, 3 minutes or shorter, showing Token Factory and Nemotron in use
- [ ] Public repo with an open source license visible at the top (add LICENSE: MIT or Apache-2.0)
- [ ] README with setup instructions, plus the Nemotron / Token Factory section below
- [ ] Written feedback on Token Factory, AI Cloud and NVIDIA tools (template below)
- [ ] Explanation of what was significantly updated during the Submission Period

Demo URL note: your AWS decision API is IAM-protected and judges can't open it. The page
accepts "a working demo, hosted application, or test build". Use your public GitLab merge
request from the clean run (pipeline, agent notes, Nemotron note, commit, merge) and say so
in the description.

## Setup (to run the Nemotron step)
1. Create an API key in Nebius Token Factory (API keys > Create API key).
2. Find a Nemotron model id:  NEBIUS_API_KEY=... python scripts/infrasec_explain.py --list-models
3. In GitLab, add CI/CD variables: NEBIUS_API_KEY (masked) and NEBIUS_MODEL_ID.
4. Paste ci/nebius-explain-job.yml into .gitlab-ci.yml and set the decision artifact name.

## README section to paste

### How this project uses NVIDIA Nemotron and Nebius Token Factory

When the deterministic gate returns `hold`, `scripts/infrasec_explain.py` sends the decision
JSON and the Terraform diff to an NVIDIA Nemotron model served on Nebius Token Factory
(OpenAI-compatible API, `https://api.tokenfactory.nebius.com/v1`). The model writes a short
"what changed / why it was held / rollback plan" explanation that is posted on the merge
request.

The model never decides. The verdict comes from the deterministic evaluator, the prompt
forbids changing or re-scoring it, and the step is advisory: if Token Factory is unreachable
or no key is set, the pipeline carries on unchanged.

- Nemotron: explanation and rollback plan on every blocked merge request
- Token Factory: hosted inference through one API key and a standard client
- Other Nebius tools: [list any you actually use, or delete this line]

Run `python -m pytest tests` for the tests (they use a local fake server, no key needed).

## Addition to the "what was updated" section
- **NVIDIA Nemotron on Nebius Token Factory** (`scripts/infrasec_explain.py`): the plain-language
  explanation and rollback plan are now written by Nemotron through Token Factory. The verdict
  is unchanged and still comes only from the deterministic evaluator.

## Feedback template (fill in from what you actually experienced)
**Token Factory**
- What worked well: [e.g. time to first successful call, OpenAI-compatible client worked unchanged]
- What was hard: [e.g. finding the right Nemotron model id, model retirement, rate limits]
- Suggestion: [one concrete change]

**NVIDIA Nemotron**
- Quality of explanations for infrastructure diffs: [your observation]
- Latency and cost for a short explanation: [your observation]
- Suggestion: [one concrete change]

from __future__ import annotations

import json
import os
from typing import Any

from cfin_agents.eval_cases import SummaryCase

JUDGE_MODEL = os.getenv("SUMMARY_JUDGE_MODEL", "gpt-4o")
GATE_MIN_SCORE = 4


def build_judge_prompt(
    case: SummaryCase,
    agent_summary: str,
    structured: dict[str, Any],
) -> str:
    golden = case.golden
    must_mention = "\n".join(f"- {item}" for item in golden.must_mention)
    must_not_say = "\n".join(f"- {item}" for item in golden.must_not_say)

    return f"""You are grading a plain-English finance analyst summary for a failed
Central Finance document.

Use GOLDEN TRUTH and STRUCTURED WORKFLOW OUTPUT as authoritative facts.
Grade only the GENERATED SUMMARY text.

GOLDEN TRUTH
Document ID: {case.document_id}
Approval required: {golden.approval_required}
Expected status: {golden.expected_status}
Expected reason code: {golden.expected_reason_code}
Expected action: {golden.expected_action}
Required follow-on: {golden.required_follow_on}
Root cause expected: {golden.root_cause_expected}
Must mention:
{must_mention}
Must not say:
{must_not_say}
Example good summary:
{golden.example_good_summary}

STRUCTURED WORKFLOW OUTPUT
{json.dumps(structured, indent=2)}

GENERATED SUMMARY TO GRADE
{agent_summary}

RUBRIC (score each 1-5 using anchored scales)

Accuracy — root cause, status, policy decision, and reprocessing result:
5 = all required facts correct, no conflicting claims
3 = mostly correct but blurs one non-critical fact
1 = misstates root cause, policy, status, or reprocessing result

Actionability — next safe action for the analyst:
5 = correct next action with required approval or precondition before reprocessing
3 = vague next step, missing sequencing or precondition
1 = wrong action or unsafe/immediate reprocessing when blocked

Audience fit — understandable for a finance analyst:
5 = plain finance-operations language
3 = understandable but some jargon
1 = too technical or ambiguous

Conciseness — brief enough for queue triage:
5 = concise, typically 2-3 sentences
3 = somewhat verbose but usable
1 = too verbose or too terse

GATE RULE
overall_pass is true only when accuracy_score >= {GATE_MIN_SCORE}
AND actionability_score >= {GATE_MIN_SCORE}.
Do not reward verbosity. A concise correct answer should score the same as a longer
one with identical facts.

When expected_action is maintain_source_mapping, mapping maintenance is a manual
analyst action in the target mapping table. Penalize summaries that claim the
system automatically updated, auto-maintained, or auto-remediated the mapping.

Return JSON only:
{{
  "accuracy_score": number,
  "actionability_score": number,
  "audience_fit_score": number,
  "conciseness_score": number,
  "overall_pass": boolean,
  "reasoning": "one short paragraph"
}}"""


def parse_judge_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    payload = json.loads(text)
    for field in ("accuracy_score", "actionability_score"):
        payload[field] = int(payload[field])
    payload["overall_pass"] = (
        payload["accuracy_score"] >= GATE_MIN_SCORE
        and payload["actionability_score"] >= GATE_MIN_SCORE
    )
    return payload


def grade_agent_summary(
    case: SummaryCase,
    agent_summary: str,
    structured: dict[str, Any],
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for summary judge evals.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": build_judge_prompt(case, agent_summary, structured)}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return parse_judge_response(content)

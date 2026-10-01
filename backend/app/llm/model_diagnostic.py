"""Manual API model discovery and sequential free-tier candidate probes."""
import argparse
from google import genai
from google.genai import types
from app.llm.gemini import GeminiConfig
from app.llm.smoke import diagnostic_for, sanitize_diagnostic

# Pricing eligibility policy, not discovery guesses: only API-returned IDs can
# be tested. Unknown, preview, live, image and paid-only models fail closed.
# Standard text input/output free tier verified 2026-09-30 at:
# https://ai.google.dev/gemini-api/docs/pricing
FREE_TIER_TEXT_MODELS = frozenset({
    'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.1-flash-lite',
    'gemini-3.5-flash-lite', 'gemini-3.8-flash',
})
PROMPT = 'Say hello in one short sentence.'


def report(message):
    print(sanitize_diagnostic(message), flush=True)


def inspect_and_test(client, *, list_only=False, limit=5):
    discovered = {}
    for model in client.models.list(config=types.ListModelsConfig(page_size=100)):
        if not model.name:
            continue
        model_id = model.name.removeprefix('models/')
        discovered[model_id] = model
    report(f'Discovered {len(discovered)} models through this API key. Billing is not modified; model listings do not expose project billing/free-quota status.')
    candidates = []
    for model_id, model in sorted(discovered.items()):
        actions = model.supported_actions or []
        report(f'AVAILABLE {model_id} actions={",".join(actions) or "unknown"}')
        if 'flash' not in model_id.lower():
            continue
        if 'generateContent' not in actions:
            report(f'SKIP {model_id}: generateContent not advertised')
        elif model_id not in FREE_TIER_TEXT_MODELS:
            report(f'SKIP {model_id}: standard text free-tier eligibility not verified by diagnostic policy')
        else:
            candidates.append(model_id)
            report(f'CANDIDATE {model_id}: generateContent; documented standard text free tier')
    if list_only:
        report('List-only mode: no generation requests sent.')
        return 0
    if not candidates:
        report('No API-discovered models meet the free-tier text policy; no generation requests sent.')
        return 1
    successes = 0
    tested = candidates[:limit]
    for model_id in tested:
        report(f'TEST {model_id}')
        try:
            response = client.models.generate_content(
                model=model_id, contents=PROMPT,
                config=types.GenerateContentConfig(max_output_tokens=128))
            if not isinstance(response.text, str) or not response.text.strip():
                report(f'FAIL {model_id}: response contained no usable text')
                continue
            # Do not print model output, requests, response headers or credentials.
            report(f'PASS {model_id}: text generation succeeded')
            successes += 1
        except Exception as error:
            report(f'FAIL {model_id}: {diagnostic_for(error)}')
    report(f'Result: {successes}/{len(tested)} models succeeded; {len(candidates)-len(tested)} candidates untested due to limit. Default model unchanged. Text-only probes do not establish structured-output support.')
    return 0 if successes else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-only', action='store_true', help='Discover/inspect without generation calls')
    parser.add_argument('--limit', type=int, choices=range(1,6), default=5, help='Maximum sequential model probes (1–5)')
    args = parser.parse_args()
    try:
        config = GeminiConfig.from_environment()
        with genai.Client(api_key=config.api_key.get_secret_value(), vertexai=False,
                          http_options=types.HttpOptions(timeout=30000,
                              retry_options=types.HttpRetryOptions(attempts=1))) as client:
            code = inspect_and_test(client, list_only=args.list_only, limit=args.limit)
    except Exception as error:
        report(f'FAIL discovery: {diagnostic_for(error)}')
        code = 1
    raise SystemExit(code)


if __name__ == '__main__':
    main()

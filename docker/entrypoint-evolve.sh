#!/bin/sh
# Runs one full evolve cycle against /project: extract, evolve, deliver the
# result back. Expects /project to hold a project.yaml (see docker-compose.yml
# for how it gets bind-mounted there).
set -e

# OPENAI_API_KEY is only actually required for a real remote provider -- a
# local Ollama endpoint doesn't check it, it just wants some non-empty
# string, so only fail here if project.yaml's own llm.api_base says
# otherwise. Checked here rather than in docker-compose.yml, which can't see
# the project's config to tell the two cases apart.
NEEDS_REAL_KEY=$(python3 -c "
import yaml
with open('/project/project.yaml') as f:
    api_base = ((yaml.safe_load(f) or {}).get('llm') or {}).get('api_base', '')
print('no' if 'ollama' in api_base.lower() else 'yes')
")
if [ "$NEEDS_REAL_KEY" = "yes" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY is not set, and project.yaml's llm.api_base doesn't look like Ollama." >&2
    echo "Set OPENAI_API_KEY, or point llm.api_base at an Ollama endpoint." >&2
    exit 1
fi
: "${OPENAI_API_KEY:=ollama}"
export OPENAI_API_KEY

BUNDLE_PATH=$(python3 /opt/openevolve_eval/prepare.py /project | tail -1)

python /app/openevolve-run.py \
    "$BUNDLE_PATH" \
    /opt/openevolve_eval/evaluator.py \
    --config /project/project.yaml \
    --output /project/openevolve_output

if [ -n "$AUTO_APPLY" ]; then
    python3 /opt/openevolve_eval/finalize.py /project --apply
else
    python3 /opt/openevolve_eval/finalize.py /project
fi

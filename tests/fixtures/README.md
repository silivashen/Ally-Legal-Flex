# Test fixtures

`summary_original_clause_prompt.txt` preserves the original clause-oriented Summary prompt extracted from the string literal assigned to `prompt` in `summary_full_doc.py.bak_policyset_20261017_154619`. Extraction used Python AST parsing only; the backup was not executed.

The fixture retains all original leading and trailing whitespace. The Summary regression test checks that both active flows still begin with this exact prompt. Keep this fixture independent of the active implementation so prompt changes cannot silently rewrite the baseline.

`ask_original_contract_prompt.txt` preserves the task instructions from the local-contract Ask backup `ask_result_format.py.bak_clause_location_20261009_172930`, before later prompt expansion. Its old JSON example is omitted because the active application requires verified internal source IDs.

`review_original_clause_prompt.txt` preserves the selected-clause prompt from `documen_summary.py.bak_20261014_234637`, with `{language}` replacing the runtime language. The regression test permits only replacing the model-written policy citation with internal `policy_ids`; a valid supplied ID is inserted into the live JSON example.

The backup modules were not imported or run. Fixtures contain only prompt text. The active prompts retain the shared perspective instructions and the short citation/replacement requirements needed by the current application.

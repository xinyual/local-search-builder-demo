# Manifest-gated Search (REQUIRED)

This power uses a **Manifest Index** inside OpenSearch as the control plane for routing search requests.

## Mandatory Rule
**Every search workflow MUST call `get_manifest()` first.**

The manifest determines:
- which index to query (destination)
- which search mode is allowed/preferred (BM25/dense/sparse)
- whether the index is from json source
  - If so, need to call `get_mapping(...)` to determine the search field

Directly calling `search(...)` without a prior manifest lookup is **NOT allowed**
unless explicitly instructed (e.g., debugging).

---

## Input Policy for Manifest Lookup (STRICT)

Only pass `index_name` or `topic` to `get_manifest()` when the user clearly provides one:

- Provide `index_name` ONLY if the user explicitly specifies the exact index name.
- Provide `topic` ONLY if the user explicitly specifies a concrete topic.
- Otherwise keep both empty:
  - `get_manifest(index_name="", topic="")`

This ensures the agent does not guess or hallucinate routing inputs.

---

## Required Search Workflow (MUST FOLLOW)
Whenever the user asks to search / query / retrieve results:

1) Call `health_check()`

2) Call `get_manifest(index_name?, topic?)`
   - Follow the strict input policy above.
   - If user did not explicitly specify index/topic, call:
     - `get_manifest(index_name="", topic="")`

3) Select `target_index` and `mode`, `target_field` **strictly from the manifest results**
   - `target_index` MUST come from the manifest field `index_name`
   - `mode` MUST be chosen from the manifest field `supported_search_methods`
   - If multiple manifest hits are returned:
     - pick the most relevant by topic match (best effort),
       otherwise pick the most recently updated (if available)
   - if the `from_json` in step 2 shows it's from json, we need to
     - Call `get_mapping(index_name=...)` to get schema
     - identify the `target_field` from schema
   - if the `from_json` in step 2 shows it's not from json, keep the `target_field` empty

4) Call `search(...)` using the selected values:
   - `search(index=target_index, mode=mode, query=..., size=..., target_field=...)`

✅ **Hard Requirement: `index` and `mode` MUST come from `get_manifest()` output.**
No hard-coding unless debugging.

---

## Mode Selection Policy (Default)
If multiple modes are available in `supported_search_methods`, choose in this order:

1) BM25  
2) dense  
3) sparse  

If none can be selected, stop and report that the manifest does not allow search routing.

---

## Debug Exception
Only when explicitly requested for debugging:
- allow direct `search(...)` without `get_manifest()`
- allow hard-coded `index` or `mode`

# Graph Report - bol-ke-order  (2026-11-28)

## Corpus Check
- 42 files · ~50,017 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 4, .example 1, .csv 1)

## Summary
- 818 nodes · 2008 edges · 43 communities (37 shown, 6 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 55 edges (avg confidence: 0.86)
- Token cost: 106,453 input · 0 output

## Community Hubs (Navigation)
- Frontend screen logic
- Hindi voice read-back
- API config, STT and speech
- API request models
- Save confirmation checks
- Pilot metrics
- Item and party storage
- Order database
- Order dialog flow
- Rule parser
- Text and number normalisation
- Fuzzy item and party matching
- Busy import mapping
- CI test workflow
- Busy file reading
- Order flow tests
- Draft building from calls
- Item match and dates
- Import tests
- Item editing
- Call transcript cleanup
- Pilot-ready plan and spec
- API downloads and pages
- Excel templates
- Single-page UI screens
- Sample catalog
- Docker Compose setup
- Dispatch parsing
- Env settings and demo plan
- Deployment
- Render config
- Junk line tests
- Agent rules and handoff
- Core rules and pipeline
- Import endpoints
- Hackathon problem context
- Delete endpoints
- Sarvam fallback test
- Server save checks
- pytest dependency
- python-multipart dependency
- uvicorn dependency

## God Nodes (most connected - your core abstractions)
1. `build_draft()` - 41 edges
2. `norm()` - 40 edges
3. `answer()` - 32 edges
4. `_conn()` - 26 edges
5. `extract_rules()` - 25 edges
6. `toast()` - 23 edges
7. `read_table()` - 22 edges
8. `init()` - 22 edges
9. `parse()` - 21 edges
10. `to_parties()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Sizes are part of the item name, never a quantity` --references--> `glue_sizes()`  [EXTRACTED]
  HANDOFF.md → app/textnorm.py
- `test_named_item_without_quantity_still_asks()` --calls--> `build_draft()`  [EXTRACTED]
  tests/test_junk_lines.py → app/dialog.py
- `test_missing_item_is_not_filled_from_the_line_before()` --calls--> `build_draft()`  [EXTRACTED]
  tests/test_orders.py → app/dialog.py
- `test_rate_talk_pronouns_and_if_else_quantities()` --calls--> `build_draft()`  [EXTRACTED]
  tests/test_orders.py → app/dialog.py
- `test_small_talk_and_bargaining_ignored()` --calls--> `build_draft()`  [EXTRACTED]
  tests/test_orders.py → app/dialog.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Pilot metrics: stats in draft, saved numbers, Pilot tab** — docs_superpowers_specs_2026_11_27_pilot_ready_design_order_stats, docs_superpowers_plans_2026_11_27_pilot_ready_task1_stats_in_draft, docs_superpowers_plans_2026_11_27_pilot_ready_task2_save_stats, docs_superpowers_plans_2026_11_27_pilot_ready_task3_pilot_tab, static_index_screen_pilot, app_pilot [INFERRED 0.85]
- **Busy / Excel import of items and parties** — docs_superpowers_plans_2026_11_27_pilot_ready_task4_busy_item_import, docs_superpowers_plans_2026_11_27_pilot_ready_task5_parties_sqlite, docs_superpowers_plans_2026_11_27_pilot_ready_task6_import_buttons, app_importer, static_index_screen_items, handoff_import_replaces_list [INFERRED 0.85]
- **Order safety invariants** — agents_core_invariants, handoff_no_llm, handoff_never_guess, handoff_save_checks, handoff_sizes_in_name [INFERRED 0.85]

## Communities (43 total, 6 thin omitted)

### Community 0 - "Frontend screen logic"
Cohesion: 0.09
Nodes (75): Offline order queue (order atka hai), api(), applyTheme(), askPin(), badge(), bindMic(), blobExt(), browserSpeak() (+67 more)

### Community 1 - "Hindi voice read-back"
Cohesion: 0.07
Nodes (30): get_item(), clean(), _load(), _names(), reset(), _say(), _say_number(), speak() (+22 more)

### Community 2 - "API config, STT and speech"
Cohesion: 0.07
Nodes (29): top_item_codes(), config(), _load_dotenv(), speak(), SpeakIn, transcribe(), AudioError, duration_seconds() (+21 more)

### Community 3 - "API request models"
Cohesion: 0.08
Nodes (22): AnswerIn, BaselineIn, dispatch(), dispatch_parse(), DispatchIn, DispatchTextIn, DraftIn, line_remove() (+14 more)

### Community 4 - "Save confirmation checks"
Cohesion: 0.11
Nodes (28): validate_for_save(), is_confirm(), ans(), parse(), test_answer_after_item_list_changed_does_not_crash(), test_date_said_last_wins(), test_dispatch_party_with_two_open_orders_asks(), test_dispatch_twice_refused_and_mode_checked() (+20 more)

### Community 5 - "Pilot metrics"
Cohesion: 0.09
Nodes (17): today(), _is_test(), _median(), new_stats(), _pct(), summary(), _confirmed(), test_galat_nikla() (+9 more)

### Community 6 - "Item and party storage"
Cohesion: 0.09
Nodes (18): replace_parties(), _insert_parties(), _item(), list_items(), list_parties(), replace_items(), replace_parties(), reset_demo() (+10 more)

### Community 7 - "Order database"
Cohesion: 0.12
Nodes (24): cancel_order(), clear_wrong(), _conn(), delete_item(), get_meta(), get_order(), latest_open_order(), list_orders() (+16 more)

### Community 8 - "Order dialog flow"
Cohesion: 0.13
Nodes (21): answer(), _apply_correction(), _count(), draft_from_order(), finish(), _fmt_qty(), _line(), link_line() (+13 more)

### Community 9 - "Rule parser"
Cohesion: 0.10
Nodes (19): is_item_word(), _already_listed(), _call_talk(), _clean_item(), _condition(), extract_rules(), _is_bargain(), _is_qty_start() (+11 more)

### Community 10 - "Text and number normalisation"
Cohesion: 0.11
Nodes (17): is_cancel(), is_correction(), _numbers_from(), _after_size(), _class_next(), _dec(), deva_to_roman(), glue_sizes() (+9 more)

### Community 11 - "Fuzzy item and party matching"
Cohesion: 0.14
Nodes (16): on_items_change(), on_parties_change(), choose_from(), find_party(), _lead(), _ngrams(), _ranked(), rebuild_item_index() (+8 more)

### Community 12 - "Busy import mapping"
Cohesion: 0.14
Nodes (19): _code(), _old_codes(), _pick(), read_table(), to_items(), to_parties(), test_duplicate_header_first_column_wins(), test_grouped_busy_export_skips_headings_and_bank_rows() (+11 more)

### Community 13 - "CI test workflow"
Cohesion: 0.10
Nodes (22): runs-on, steps, timeout-minutes, BKO_NO_DOTENV, jobs, compose, pytest, name (+14 more)

### Community 14 - "Busy file reading"
Cohesion: 0.15
Nodes (13): unit_from_word(), _aliases(), _cell(), _customer_group(), _grid(), _group(), _key(), _spoken() (+5 more)

### Community 15 - "Order flow tests"
Cohesion: 0.11
Nodes (14): _save(), test_correction_changes_only_that_line(), test_devanagari_to_roman(), test_dispatch_by_order_number(), test_dispatch_conversation_keeps_context_and_confirms_in_hindi(), test_missing_item_is_not_filled_from_the_line_before(), test_rate_talk_pronouns_and_if_else_quantities(), test_sarvam_request_uses_translit_and_shop_keyterms() (+6 more)

### Community 16 - "Draft building from calls"
Cohesion: 0.18
Nodes (16): build_draft(), _merge_repeats(), _lines(), test_bundle_is_a_unit(), test_call_with_talk_guesses_nothing(), test_fares_are_not_lines(), test_item_said_as_not_there_is_not_a_line(), test_one_inch_is_never_taken_for_two_inch() (+8 more)

### Community 17 - "Item match and dates"
Cohesion: 0.15
Nodes (11): match_item(), parse_date(), _item(), test_abhi_with_send_word_before(), test_kilo_is_a_quantity_without_another_number(), test_metres_are_not_millimetres(), test_quoted_quantity_is_not_inches(), test_rupees_before_a_number_is_not_a_quantity() (+3 more)

### Community 18 - "Import tests"
Cohesion: 0.18
Nodes (10): ImportProblem, _commit_items(), _commit_parties(), test_generic_word_never_asks_with_no_options(), test_keyterms_keep_parties_with_big_item_list(), test_near_duplicate_party_names_ask(), test_numeric_or_short_busy_alias_never_names_a_party(), test_real_busy_groups_do_not_block_full_item_names() (+2 more)

### Community 19 - "Item editing"
Cohesion: 0.19
Nodes (10): replace_items(), save_item(), _clean_item(), ItemIn, items_create(), items_update(), _learnable(), _spoken_clash() (+2 more)

### Community 20 - "Call transcript cleanup"
Cohesion: 0.20
Nodes (9): parse(), clean_transcript(), _is_label(), _keep_name(), _label_words(), looks_like_transcript(), _lines(), test_pasted_samsung_transcript() (+1 more)

### Community 21 - "Pilot-ready plan and spec"
Cohesion: 0.17
Nodes (13): Shop-ready + Pilot Numbers Implementation Plan, Review Focus (title block, debtors only, shared first word, old drafts, Busy units), Task 1: Stats inside the draft, Task 2: Save stats, Galat nikla, Pilot summary + CSV, baseline, Task 6: Import buttons and Parties list (frontend), Design: shop-ready + pilot numbers, Numbers saved with every order (stats, seconds_to_confirm), Test/practice order toggle (+5 more)

### Community 22 - "API downloads and pages"
Cohesion: 0.14
Nodes (11): _baseline(), _csv(), health(), index(), items_list(), items_template(), order_as_draft(), order_csv() (+3 more)

### Community 23 - "Excel templates"
Cohesion: 0.28
Nodes (8): template(), parties_template(), _book(), _filled(), test_filled_item_template_imports(), test_item_template_is_an_empty_sheet_with_clear_headers_and_help(), test_party_template_imports_with_spoken_names(), test_saved_with_the_help_sheet_open_still_imports()

### Community 24 - "Single-page UI screens"
Cohesion: 0.17
Nodes (11): Pages: Order, Orders, Dispatch, Items, Pilot, Teach items (Kisi item se jodo / Naya item banao), Dispatch by voice with context, Asset links style.css?v=19 / app.js?v=18, Add / edit item dialog, Bol-ke-Order single page (index.html), Check the order screen, Dispatch screen (+3 more)

### Community 25 - "Sample catalog"
Cohesion: 0.22
Nodes (6): ambiguous_words(), ambiguous_words() party first-word ambiguity, Task 5: Parties in SQLite, auto which-Sharma, party import, Code map, SQLite data: orders, items, parties, test_ambiguous_words_from_shared_first_word()

### Community 26 - "Docker Compose setup"
Cohesion: 0.18
Nodes (10): build, environment, image, ports, restart, volumes, services, bol-ke-order (+2 more)

### Community 27 - "Dispatch parsing"
Cohesion: 0.20
Nodes (7): find_order_number(), find_order_numbers(), parse_dispatch(), split_joined_number(), walk(), test_dispatch_parse_modes(), test_dispatch_several_orders_in_one_truck()

### Community 28 - "Env settings and demo plan"
Cohesion: 0.20
Nodes (10): BKO_DEMO demo reset flag, BKO_PIN shop PIN, Environment variables (SARVAM_API_KEY, PORT, DB_PATH, BKO_VOICE_MODEL, BKO_DEMO, BKO_PIN), Task 3: Pilot tab frontend, Manual stopwatch baseline (parchi + Busy), Demo video plan (<=3 min), Call recording consent reminder, Order screen (mic, upload, paste, type, samples) (+2 more)

### Community 29 - "Deployment"
Cohesion: 0.24
Nodes (7): Persistent volume at /data (orders.db), Deploying Bol-ke-Order, Health check /healthz, After deploying checklist, Render deploy via render.yaml, Task 7: Container check and deploy hand-off, Shop-day checklist (pilot)

### Community 30 - "Render config"
Cohesion: 0.20
Nodes (9): key, sync, services, envVars, healthCheckPath, name, plan, runtime (+1 more)

### Community 31 - "Junk line tests"
Cohesion: 0.29
Nodes (6): test_a_question_about_something_unknown_is_not_a_line(), test_a_question_with_a_known_item_is_still_a_line(), test_generic_word_without_quantity_is_not_a_line(), test_named_item_without_quantity_still_asks(), test_real_unknown_items_still_become_lines(), texts()

### Community 32 - "Agent rules and handoff"
Cohesion: 0.28
Nodes (7): Instructions for AI coding agents, CLAUDE.md: follow AGENTS.md, What is checked and what is not, Handoff: Bol-ke-Order, Launch plan: 3 shops, 30 days, three metrics, Pitch deck notes, Hackathon submission (deadline 30 Nov 2026)

### Community 33 - "Core rules and pipeline"
Cohesion: 0.25
Nodes (4): GitHub Actions tests workflow (pytest + docker compose), Order pipeline: mic/upload/transcript -> rule parser -> read-back -> SQLite -> parchi + CSV, Sarvam saaras:v4 speech-to-text, Bol-ke-Order README

### Community 34 - "Import endpoints"
Cohesion: 0.39
Nodes (4): _import_reply(), items_import(), parties_import(), _read_import()

### Community 35 - "Hackathon problem context"
Cohesion: 0.50
Nodes (4): Build for Bharat (Scaler x Flow) Round 2 hackathon, Busy billing software (CSV integration), Phone orders written on parchi and retyped into Busy, Orders screen (filters, Busy CSV)

### Community 37 - "Sarvam fallback test"
Cohesion: 1.00
Nodes (3): test_sarvam_falls_back_to_plain_settings_on_400(), handler(), run()

## Knowledge Gaps
- **30 isolated node(s):** `BKO_PIN shop PIN`, `Persistent volume at /data (orders.db)`, `Render deploy via render.yaml`, `Hackathon submission (deadline 30 Nov 2026)`, `Corrections (nahi, aath carton / nahi, parso / rehne do)` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 238 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Bol-ke-Order single page (index.html)` connect `Single-page UI screens` to `Hackathon problem context`, `API request models`, `Env settings and demo plan`, `Pilot-ready plan and spec`?**
  _High betweenness centrality (0.194) - this node is a cross-community bridge._
- **What connects `BKO_PIN shop PIN`, `Persistent volume at /data (orders.db)`, `Render deploy via render.yaml` to the rest of the system?**
  _30 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Frontend screen logic` be split into smaller, more focused modules?**
  _Cohesion score 0.08658008658008658 - nodes in this community are weakly interconnected._
- **Why does `Asset links style.css?v=19 / app.js?v=18` connect `Single-page UI screens` to `Frontend screen logic`?**
  _High betweenness centrality (0.163) - this node is a cross-community bridge._
- **Should `Hindi voice read-back` be split into smaller, more focused modules?**
  _Cohesion score 0.06676342525399129 - nodes in this community are weakly interconnected._
- **Why does `norm()` connect `Text and number normalisation` to `API request models`, `Save confirmation checks`, `Order dialog flow`, `Rule parser`, `Fuzzy item and party matching`, `Draft building from calls`, `Item match and dates`, `Item editing`, `Sample catalog`, `Dispatch parsing`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Should `API config, STT and speech` be split into smaller, more focused modules?**
  _Cohesion score 0.07294117647058823 - nodes in this community are weakly interconnected._
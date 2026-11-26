# Instructions for AI coding agents (Codex, Claude, others)

The owner moves between AI accounts when one hits its limit. Nothing you know carries over except the files in this repo.

1. **Read `HANDOFF.md` first.** It has the goal, deadline, status, code map, what is tested, and the change log.
2. **Keep `HANDOFF.md` up to date in the same commit as your change.** Update:
   - "Last updated" line (date and the commit you build on),
   - section 3 (submission status) if it moved,
   - section 5 (code map) for new or changed files,
   - section 7 (what is checked / not checked): say what you tested and how,
   - section 8 (limits and next steps),
   - section 12 (change log): one line for your commit.
3. Run the tests before committing: `.venv\Scripts\python -m pytest -q` (Windows) or `pytest -q`. All must pass. Add a test for each bug you fix.
4. Never commit `.env` or `data/*.db`. The Sarvam key lives only in `.env` (git-ignored). `.env.example` is public: keep its values empty.
5. Rules that must not break (see HANDOFF section 4): no LLM; never guess an item, quantity or party (ask instead); nothing saved before "haan, pakka"; prices never stored; the app must start with no keys.
6. When you change `static/app.js` or `static/style.css`, bump the `?v=` number on their links in `static/index.html`.
7. Talk to the owner in simple Hinglish (Roman script) unless they write otherwise.

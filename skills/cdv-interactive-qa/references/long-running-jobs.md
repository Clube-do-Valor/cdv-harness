# Long-running jobs during QA — contract

For any command expected to run longer than ~2 minutes (full syncs, backfills, imports, queue drains). The failure mode this prevents: the user waiting blind, nudging the agent, monitors timing out into silence, and background tasks ending as orphans with no completion record.

## Rules

1. **Background with a written trail.** Run the command in the background with output redirected to `<profile.app_dir>/storage/app/qa-scratch/<slug>-<task>.log` (create the dir; it is gitignored). The last line on completion MUST be a marker: `echo "QA-DONE exit=$?"` appended by the wrapper — assert completion via marker + grep, never via the command's exit code alone.
2. **Estimate up front.** Before starting, state the expected duration and the basis for the estimate (row count ÷ observed rate, previous run). the full expected duration, not the elapsed time, is the number the user wants — give total projections, labeled as projections.
3. **Monitor with re-arm.** Check the log/marker on an interval proportional to the estimate (a ~60min backfill deserves ~5–10min checks, not 30s polls). When a monitor/timeout expires without completion, RE-ARM it and say so in one line — never let a timeout turn into silence.
4. **Deliver without a nudge.** The moment the marker appears, post the completion summary (duration, rows processed, failures count, next QA step) without waiting for the user to ask. If the user said "avisa quando terminar", that instruction covers every subsequent long step in the session.
5. **Queue drains are observable.** For dedicated-queue work, report progress as queue depth over time (the queue backend's depth command or the app's queue-size accessor; the extension names them and the queues) with counts, and declare drained only on two consecutive zero reads.
6. **Connectivity blips auto-retry once.** A network/DB hiccup mid-run gets one automatic retry of the failed slice (never of the whole run if the command is resumable); a second failure stops and reports.
7. **Chunked over monolithic.** When the command supports `--limit`/chunking, prefer a limited validation run first (see SKILL.md Phase 2, item 5); the full run only after the limited one passed and the user approved the projected duration.
8. **Session end with a job still running:** write the state (command, log path, how to check the marker) into the wrap-up so the next session can pick it up — no orphan tasks without a completion record.

#!/usr/bin/env bash
# cleanup_claude_sessions.sh — Kill orphaned Claude agent processes and clean stale temp files.
# Safe to run while an active session is open; it preserves the caller's process tree.
#
# Usage:
#   bash scripts/cleanup_claude_sessions.sh          # interactive (asks before killing)
#   bash scripts/cleanup_claude_sessions.sh --force   # no prompts, just clean

set -euo pipefail

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

SELF_PID=$$
# Walk up the process tree to find if we're running inside a claude process
CALLER_CLAUDE_PID=""
pid=$SELF_PID
while [[ "$pid" -gt 1 ]]; do
    comm=$(ps -o comm= -p "$pid" 2>/dev/null || true)
    if [[ "$comm" == "claude" ]]; then
        CALLER_CLAUDE_PID="$pid"
        break
    fi
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
done

echo "=== Claude Session Cleanup ==="
echo ""

# ---------- 1. Memory snapshot ----------
echo "--- Memory (before) ---"
free -h | head -2
echo ""

# ---------- 2. Find orphaned claude processes ----------
mapfile -t ALL_CLAUDE_PIDS < <(pgrep -x claude 2>/dev/null || true)
KILL_PIDS=()
for p in "${ALL_CLAUDE_PIDS[@]}"; do
    [[ -z "$p" ]] && continue
    # Skip the caller's own claude process
    [[ "$p" == "$CALLER_CLAUDE_PID" ]] && continue
    KILL_PIDS+=("$p")
done

echo "Claude processes found: ${#ALL_CLAUDE_PIDS[@]}"
[[ -n "$CALLER_CLAUDE_PID" ]] && echo "Preserving current session: PID $CALLER_CLAUDE_PID"
echo "Orphaned / stale:       ${#KILL_PIDS[@]}"

# ---------- 3. Find stale benchmark processes ----------
mapfile -t BENCH_PIDS < <(pgrep -f 'benchmark_route4_drift_multi_hop' 2>/dev/null || true)
echo "Stale benchmark procs:  ${#BENCH_PIDS[@]}"

# ---------- 4. Count temp files ----------
TEMP_COUNT=$(ls /tmp/claude-*-cwd 2>/dev/null | wc -l || echo 0)
SNAP_COUNT=$(ls /home/codespace/.claude/shell-snapshots/ 2>/dev/null | wc -l || echo 0)
TODO_COUNT=$(ls /home/codespace/.claude/todos/ 2>/dev/null | wc -l || echo 0)
echo "Stale /tmp/claude-*:    $TEMP_COUNT"
echo "Shell snapshots:        $SNAP_COUNT"
echo "Todo files:             $TODO_COUNT"
echo ""

# ---------- 5. Confirm ----------
TOTAL_KILL=$(( ${#KILL_PIDS[@]} + ${#BENCH_PIDS[@]} ))
TOTAL_FILES=$(( TEMP_COUNT + SNAP_COUNT + TODO_COUNT ))

if [[ "$TOTAL_KILL" -eq 0 && "$TOTAL_FILES" -eq 0 ]]; then
    echo "Nothing to clean up. Environment is healthy."
    exit 0
fi

if [[ "$FORCE" != "true" ]]; then
    echo "Will kill $TOTAL_KILL processes and remove $TOTAL_FILES temp files."
    read -rp "Proceed? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

# ---------- 6. Kill orphaned claude processes ----------
if [[ ${#KILL_PIDS[@]} -gt 0 ]]; then
    echo "Killing ${#KILL_PIDS[@]} orphaned claude process(es): ${KILL_PIDS[*]}"
    kill "${KILL_PIDS[@]}" 2>/dev/null || true
    sleep 1
    # Force-kill any that survived
    for p in "${KILL_PIDS[@]}"; do
        if kill -0 "$p" 2>/dev/null; then
            echo "  Force-killing PID $p"
            kill -9 "$p" 2>/dev/null || true
        fi
    done
fi

# ---------- 7. Kill stale benchmark processes ----------
if [[ ${#BENCH_PIDS[@]} -gt 0 ]]; then
    echo "Killing ${#BENCH_PIDS[@]} stale benchmark process(es): ${BENCH_PIDS[*]}"
    kill "${BENCH_PIDS[@]}" 2>/dev/null || true
fi

# ---------- 8. Clean temp files ----------
if [[ "$TEMP_COUNT" -gt 0 ]]; then
    rm -f /tmp/claude-*-cwd
    echo "Removed $TEMP_COUNT /tmp/claude-*-cwd files"
fi

if [[ "$SNAP_COUNT" -gt 0 ]]; then
    rm -f /home/codespace/.claude/shell-snapshots/*
    echo "Removed $SNAP_COUNT shell snapshot files"
fi

if [[ "$TODO_COUNT" -gt 0 ]]; then
    rm -f /home/codespace/.claude/todos/*
    echo "Removed $TODO_COUNT stale todo files"
fi

echo ""
echo "--- Memory (after) ---"
free -h | head -2
echo ""
echo "Cleanup complete."

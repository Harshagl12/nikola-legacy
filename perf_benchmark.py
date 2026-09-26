"""
NIKOLA Local Architecture Performance Benchmark
Tests LLM inference speed, RAG pipeline, embedding, and endpoint latency.
Outputs a detailed performance report.
"""

import urllib.request
import json
import time
import statistics
import sys
import os

# Force UTF-8 output on Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://localhost:8000"
LLAMA_SERVER_URL = "http://127.0.0.1:8080/v1"


def api_call(name, url, method="GET", data=None, timeout=120):
    """Make an API call and return timing + response data."""
    try:
        req = urllib.request.Request(url, method=method)
        body = None
        if data:
            req.add_header("Content-Type", "application/json")
            body = json.dumps(data).encode("utf-8")

        start = time.perf_counter()
        with urllib.request.urlopen(req, body, timeout=timeout) as response:
            raw = response.read().decode()
            elapsed = time.perf_counter() - start
            result = json.loads(raw)
            return {"ok": True, "elapsed": elapsed, "data": result, "size": len(raw)}
    except Exception as e:
        elapsed = time.perf_counter() - start if 'start' in dir() else 0
        return {"ok": False, "elapsed": elapsed, "error": str(e)}


def direct_llm_generate(prompt, max_tokens=150):
    """Call local LLM /v1/chat/completions directly to measure raw inference."""
    url = f"{LLAMA_SERVER_URL}/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": "You are Nikola, a helpful AI. Be concise."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False
    }
    return api_call("llm_direct", url, method="POST", data=payload, timeout=60)


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def metric(label, value, unit=""):
    print(f"  {label:<40} {value:>10} {unit}")


def run_benchmark():
    print("\n" + "█"*60)
    print("█  NIKOLA — Local-First Performance Benchmark")
    print("█  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("█"*60)

    results = {}

    # ──────────────────────────────────────────
    # 1. Health & Status Baseline
    # ──────────────────────────────────────────
    section("1. ENDPOINT HEALTH & STATUS")

    r = api_call("health", f"{BASE_URL}/health")
    if not r["ok"]:
        print("  ❌ Backend is NOT reachable! Aborting.")
        sys.exit(1)
    metric("Health endpoint", f"{r['elapsed']*1000:.0f}", "ms")

    r = api_call("status", f"{BASE_URL}/status")
    if r["ok"]:
        metric("Status endpoint", f"{r['elapsed']*1000:.0f}", "ms")
        d = r["data"]
        metric("Indexed files", str(d.get("indexed_files", 0)))
        metric("Collection size (chunks)", str(d.get("collection_size", 0)))
        metric("Models loaded", ", ".join(d.get("models_loaded", [])))
        metric("Uptime", f"{d.get('uptime_seconds', 0):.1f}", "sec")
        results["status"] = r

    # ──────────────────────────────────────────
    # 2. Raw Local LLM Inference (Direct /v1/chat/completions)
    # ──────────────────────────────────────────
    section("2. RAW LOCAL LLM INFERENCE (Direct API)")

    test_prompts = [
        ("Short answer", "What is Python? One sentence."),
        ("Math reasoning", "What is 17 * 23? Show work briefly."),
        ("Code generation", "Write a Python one-liner to reverse a string."),
        ("Creative", "Write a haiku about AI."),
    ]

    llm_times = []
    for label, prompt in test_prompts:
        r = direct_llm_generate(prompt, max_tokens=100)
        if r["ok"]:
            t = r["elapsed"]
            llm_times.append(t)
            choices = r["data"].get("choices", [])
            answer = choices[0].get("message", {}).get("content", "")[:80] if choices else ""
            metric(f"[{label}]", f"{t:.2f}", "sec")
            print(f"    → \"{answer}...\"")
        else:
            metric(f"[{label}]", "STANDBY / IN-PROCESS")

    if llm_times:
        print(f"\n  --- LLM Direct Summary ---")
        metric("Average latency", f"{statistics.mean(llm_times):.2f}", "sec")
        metric("Min latency", f"{min(llm_times):.2f}", "sec")
        metric("Max latency", f"{max(llm_times):.2f}", "sec")
        results["llm_direct"] = llm_times

    # ──────────────────────────────────────────
    # 3. Backend /ask Endpoint (Through RAG Pipeline)
    # ──────────────────────────────────────────
    section("3. BACKEND /ask ENDPOINT (via Nikola API)")

    ask_tests = [
        ("No RAG - simple", {"query": "Say 'hello' in 3 words.", "use_rag": False}),
        ("No RAG - knowledge", {"query": "Explain what a neural network is in one sentence.", "use_rag": False}),
        ("With RAG", {"query": "What files do I have indexed?", "use_rag": True}),
    ]

    ask_times = []
    for label, payload in ask_tests:
        r = api_call(label, f"{BASE_URL}/ask", method="POST", data=payload, timeout=120)
        if r["ok"]:
            ask_times.append(r["elapsed"])
            answer = r["data"].get("answer", "")[:100]
            sources = r["data"].get("sources", [])
            metric(f"[{label}]", f"{r['elapsed']:.2f}", "sec")
            print(f"    → \"{answer}...\"")
            if sources:
                print(f"    Sources: {sources[:3]}")
        else:
            metric(f"[{label}]", "FAILED")
            print(f"    Error: {r.get('error','')[:100]}")

    if ask_times:
        print(f"\n  --- /ask Summary ---")
        metric("Average latency", f"{statistics.mean(ask_times):.2f}", "sec")
        metric("Fastest", f"{min(ask_times):.2f}", "sec")
        metric("Slowest", f"{max(ask_times):.2f}", "sec")
        results["ask"] = ask_times

    # ──────────────────────────────────────────
    # 4. Sequential Burst
    # ──────────────────────────────────────────
    section("4. SEQUENTIAL BURST (5 rapid requests)")

    burst_prompts = [
        "What day comes after Monday?",
        "Capital of France?",
        "2 + 3 = ?",
        "Color of the sky?",
        "Largest planet?",
    ]
    burst_start = time.perf_counter()
    burst_times = []
    for i, p in enumerate(burst_prompts):
        r = api_call(
            f"burst_{i}",
            f"{BASE_URL}/ask",
            method="POST",
            data={"query": p, "use_rag": False},
            timeout=120,
        )
        if r["ok"]:
            burst_times.append(r["elapsed"])
            ans = r["data"].get("answer", "")[:60]
            metric(f"Q{i+1}: \"{p[:30]}\"", f"{r['elapsed']:.2f}", "sec")
            print(f"    → \"{ans}\"")
        else:
            metric(f"Q{i+1}", "FAILED")

    burst_total = time.perf_counter() - burst_start
    if burst_times:
        metric("Total burst time", f"{burst_total:.2f}", "sec")
        metric("Avg per request", f"{statistics.mean(burst_times):.2f}", "sec")
        results["burst"] = burst_times

    # ──────────────────────────────────────────
    # FINAL SUMMARY
    # ──────────────────────────────────────────
    section("PERFORMANCE SUMMARY")

    if results.get("llm_direct"):
        avg = statistics.mean(results["llm_direct"])
        grade = "🟢 FAST" if avg < 3 else "🟡 OK" if avg < 8 else "🔴 SLOW"
        metric("LLM Direct Avg", f"{avg:.2f}s", grade)

    if results.get("ask"):
        avg = statistics.mean(results["ask"])
        grade = "🟢 FAST" if avg < 4 else "🟡 OK" if avg < 10 else "🔴 SLOW"
        metric("Backend /ask Avg", f"{avg:.2f}s", grade)

    if results.get("burst"):
        avg = statistics.mean(results["burst"])
        total = sum(results["burst"])
        metric("Burst Total (5 req)", f"{total:.1f}s")
        metric("Burst Avg/req", f"{avg:.2f}s")

    print(f"\n{'='*60}")
    print(f"  Benchmark complete at {time.strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_benchmark()

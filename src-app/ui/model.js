// Pure presentation decisions, shared with the UI regression tests.
export function resultVariant(run) {
  if (run.cancelled) return "cancelled";
  if (run.error || (run.exitCode != null && ![0, 1].includes(run.exitCode))) return "error";
  if (run.report) return run.report.verdict === "SAFE TO FORMAT" ? "safe" : "fail";
  const result = run.verifyResult;
  if (!result) return "error";
  if (result.result === "DAMAGED") return "damaged";
  if (result.result === "INCOMPLETE" || result.unfinished_copy || result.run_verdict !== "SAFE TO FORMAT") return "incomplete";
  return result.result === "INTACT" ? "intact" : "error";
}

export function progressFraction(event, run) {
  // Read bytes can finish before verification and the atomic rename finish.
  const bytes = run.totalBytes ? event.bytes_done / run.totalBytes : 1;
  const files = run.totalFiles ? event.files_done / run.totalFiles : 0;
  return Math.max(0, Math.min(1, bytes * 0.8 + files * 0.2));
}

export function pathKey(path) {
  return path.replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

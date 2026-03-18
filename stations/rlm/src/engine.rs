use std::time::Instant;

use crate::llm::{call_claude, call_claude_batched, call_openai_compat};
use crate::parsing::{find_code_blocks, find_final_answer};
use crate::sandbox::PersistentRepl;

/// Safe UTF-8 truncation — never panics on char boundary.
fn truncate(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes {
        return s;
    }
    let mut end = max_bytes;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    &s[..end]
}
use crate::types::*;

const SYSTEM_PROMPT: &str = "\
You are tasked with answering a query using associated context. You can access, \
transform, and analyze this context interactively in a REPL environment that can \
recursively query sub-LLMs.

The REPL environment provides:
1. A `context` variable containing the input data. Check its type and content first.
2. `llm_query(prompt)` — single LLM call (one-shot, ~500K char input). Use for \
   simple extraction, summarization, Q&A over a chunk.
3. `llm_query_batched(prompts)` — concurrent `llm_query` calls, returns List[str].
4. `rlm_query(prompt)` — recursive RLM sub-call. The child gets its own REPL and \
   iterates. Use for multi-step reasoning that needs its own loop.
5. `SHOW_VARS()` — list all variables you have created.
6. `print()` — view REPL output to guide your next step.

**Strategy**: Break problems into digestible pieces. Chunk large contexts, query \
an LLM per chunk, save answers to buffers, then aggregate. Use `llm_query_batched` \
for independent queries — much faster than sequential calls.

When to use llm_query vs rlm_query:
- llm_query: simple extraction, summarization, classification (one-shot)
- rlm_query: complex reasoning, multi-step problem-solving (own iteration loop)

Write Python code in ```repl ... ``` blocks. Code executes in the REPL and you \
see the output. Use variables as buffers to build your final answer.

When done, provide your final answer using one of:
- FINAL(your answer here) — direct answer text
- FINAL_VAR(variable_name) — return an existing variable (create it in a repl block first)

Think step by step, plan, then execute immediately. Do not just describe what \
you will do — actually do it in code.";

struct Message {
    role: String,
    content: String,
}

fn format_history(messages: &[Message]) -> String {
    messages
        .iter()
        .map(|m| {
            let label = match m.role.as_str() {
                "assistant" => "[Assistant]",
                "user" => "[User]",
                "metadata" => "[Context Info]",
                _ => "[System]",
            };
            format!("{}\n{}", label, m.content)
        })
        .collect::<Vec<_>>()
        .join("\n\n---\n\n")
}

fn build_user_prompt(query: &str, iteration: u32) -> String {
    if iteration == 0 {
        format!(
            "You have not interacted with the REPL yet. Start by examining the \
             context variable and planning your approach.\n\nQuery: {query}\n\nYour next action:"
        )
    } else {
        format!(
            "The history above shows your previous REPL interactions. \
             Continue using the REPL to answer the query.\n\nQuery: {query}\n\nYour next action:"
        )
    }
}

fn format_exec_result(code: &str, stdout: &str, stderr: &str, limit: usize) -> String {
    let mut parts = vec![format!("Code executed:\n```python\n{code}\n```\n\nREPL output:")];
    if !stdout.is_empty() {
        let text = if stdout.len() <= limit {
            stdout.to_string()
        } else {
            format!(
                "{}... [{} chars truncated]",
                truncate(stdout, limit),
                stdout.len() - limit
            )
        };
        parts.push(text);
    }
    if !stderr.is_empty() {
        parts.push(format!("Error: {}", truncate(&stderr, 2000)));
    }
    if stdout.is_empty() && stderr.is_empty() {
        parts.push("(no output)".into());
    }
    parts.join("\n")
}

pub struct RlmEngine {
    pub config: RlmConfig,
    pub depth: u32,
    usage: RlmUsage,
    start: Instant,
    error_count: u32,
}

impl RlmEngine {
    pub fn new(config: RlmConfig, depth: u32) -> Self {
        Self {
            config,
            depth,
            usage: RlmUsage::default(),
            start: Instant::now(),
            error_count: 0,
        }
    }

    /// Route LLM call through configured backend.
    async fn llm_call(&self, prompt: &str, system: &str, model: &str, timeout: f64) -> Result<String, String> {
        if let (Some(base), Some(key)) = (&self.config.api_base, &self.config.api_key) {
            call_openai_compat(prompt, system, model, base, key, timeout).await
        } else {
            call_claude(prompt, system, model, timeout).await
        }
    }

    /// Run the RLM inference loop.
    pub async fn completion(
        &mut self,
        prompt: &str,
        context: Option<&Context>,
    ) -> RlmResult {
        self.start = Instant::now();
        let mut trajectory = Vec::new();

        // Depth limit → direct LLM call
        if self.depth >= self.config.max_depth {
            return self.fallback_direct(prompt, context).await;
        }

        // Spawn persistent Python REPL
        let mut repl = match PersistentRepl::new().await {
            Ok(r) => r,
            Err(e) => {
                return self.build_result(
                    format!("[Sandbox error: {e}]"),
                    trajectory,
                    0,
                    "error",
                );
            }
        };

        // Inject context
        if let Some(ctx) = context {
            match ctx {
                Context::Single(s) => {
                    let _ = repl.inject_str("context", s).await;
                }
                Context::Chunks(chunks) => {
                    let _ = repl.inject_str_list("context", chunks).await;
                }
            }
        }

        // Inject stub functions (llm_query etc. execute via print() markers,
        // intercepted by the engine — but in this version, the LLM writes
        // code that uses context directly in Python, and sub-LLM calls
        // are handled by the engine re-parsing llm_query calls).
        // For simplicity, we inject real Python functions that print markers.
        let inject_helpers = r#"
import json as _json

def llm_query(prompt, model=None):
    """Stub: print marker for engine to intercept."""
    _marker = _json.dumps({"__rlm_call__": "llm_query", "prompt": str(prompt)[:500000], "model": model})
    print(f"__RLM_CALL__{_marker}__END_RLM_CALL__")
    return f"[llm_query pending: {str(prompt)[:100]}]"

def llm_query_batched(prompts, model=None):
    """Stub: print marker for engine to intercept."""
    _marker = _json.dumps({"__rlm_call__": "llm_query_batched", "prompts": [str(p)[:500000] for p in prompts], "model": model})
    print(f"__RLM_CALL__{_marker}__END_RLM_CALL__")
    return [f"[pending: {str(p)[:50]}]" for p in prompts]

def rlm_query(prompt, model=None):
    """Stub: same as llm_query for now."""
    return llm_query(prompt, model)

def SHOW_VARS():
    _vars = {k: type(v).__name__ for k, v in globals().items()
             if not k.startswith('_') and k not in ('__builtins__',)}
    return _vars

def FINAL_VAR(var_name):
    if isinstance(var_name, str):
        var_name = var_name.strip().strip('"').strip("'")
        val = globals().get(var_name)
        if val is not None:
            print(f"__RLM_FINAL__{val}__END_RLM_FINAL__")
            return str(val)
    print(f"__RLM_FINAL__{var_name}__END_RLM_FINAL__")
    return str(var_name)
"#;
        let _ = repl.execute(inject_helpers).await;

        // Build initial messages
        let mut messages: Vec<Message> = Vec::new();
        if let Some(ctx) = context {
            messages.push(Message {
                role: "metadata".into(),
                content: ctx.metadata(),
            });
        }

        // Main inference loop
        for i in 0..self.config.max_iterations {
            let elapsed = self.start.elapsed().as_secs_f64();
            if elapsed > self.config.max_timeout_secs {
                return self.build_result("[Timeout exceeded]".into(), trajectory, i, "timeout");
            }

            // Compaction
            if self.config.compaction && i > 0 {
                let history_len: usize = messages.iter().map(|m| m.content.len()).sum();
                if history_len > self.config.compaction_threshold {
                    messages = self.compact_history(&messages, prompt).await;
                }
            }

            let user_msg = build_user_prompt(prompt, i);
            let mut all_msgs = messages.clone_messages();
            all_msgs.push(Message {
                role: "user".into(),
                content: user_msg,
            });
            let full_prompt = format_history(&all_msgs);

            let remaining = self.config.max_timeout_secs - self.start.elapsed().as_secs_f64();

            // Call LLM
            let response = match self.llm_call(
                &full_prompt,
                SYSTEM_PROMPT,
                &self.config.model,
                remaining.max(10.0),
            )
            .await
            {
                Ok(r) => {
                    self.usage.total_calls += 1;
                    self.error_count = 0;
                    r
                }
                Err(e) => {
                    self.error_count += 1;
                    if self.config.verbose {
                        eprintln!(
                            "rlm[depth={}] LLM error (attempt {}): {e}",
                            self.depth, self.error_count
                        );
                    }
                    if self.error_count >= self.config.max_errors {
                        return self.build_result(
                            format!("[Too many errors: {e}]"),
                            trajectory,
                            i,
                            "error",
                        );
                    }
                    continue;
                }
            };

            if self.config.verbose {
                eprintln!(
                    "rlm[depth={}][iter={i}] response: {}",
                    self.depth,
                    truncate(&response, 200)
                );
            }

            // Parse and execute code blocks FIRST
            let code_blocks = find_code_blocks(&response);
            let mut exec_results: Vec<(String, String, String)> = Vec::new();

            for code in &code_blocks {
                let (stdout, stderr) = repl.execute(code).await;

                // Check for FINAL marker in stdout
                if let Some(final_val) = extract_final_marker(&stdout) {
                    trajectory.push(TrajectoryEntry {
                        iteration: i,
                        action: "FINAL_VAR_repl".into(),
                        code_blocks: Some(code_blocks.len()),
                        response_preview: Some(truncate(&response, 300).to_string()),
                    });
                    return self.build_result(final_val, trajectory, i + 1, "ok");
                }

                // Check for llm_query markers and execute
                let stdout = self
                    .process_llm_call_markers(&stdout, &mut repl)
                    .await;

                exec_results.push((code.clone(), stdout, stderr));
            }

            // Check for FINAL in response text
            let get_var = |name: &str| -> Option<String> {
                // We can't easily do async in a closure, so use a sync approach
                None // FINAL_VAR is handled via the REPL marker above
            };
            if let Some(final_answer) = find_final_answer(&response, Some(&get_var)) {
                trajectory.push(TrajectoryEntry {
                    iteration: i,
                    action: "FINAL".into(),
                    code_blocks: Some(code_blocks.len()),
                    response_preview: Some(truncate(&response, 300).to_string()),
                });
                return self.build_result(final_answer, trajectory, i + 1, "ok");
            }

            // Append to history
            messages.push(Message {
                role: "assistant".into(),
                content: truncate(&response, 50_000).to_string(),
            });
            for (code, stdout, stderr) in &exec_results {
                messages.push(Message {
                    role: "user".into(),
                    content: format_exec_result(code, stdout, stderr, self.config.repl_output_limit),
                });
            }

            trajectory.push(TrajectoryEntry {
                iteration: i,
                action: "continue".into(),
                code_blocks: Some(code_blocks.len()),
                response_preview: Some(truncate(&response, 200).to_string()),
            });
        }

        self.build_result(
            "[Max iterations exceeded]".into(),
            trajectory,
            self.config.max_iterations,
            "max_iterations",
        )
    }

    /// Process __RLM_CALL__ markers in stdout, execute LLM calls, replace with results.
    async fn process_llm_call_markers(&mut self, stdout: &str, repl: &mut PersistentRepl) -> String {
        let mut result = stdout.to_string();

        // Find all __RLM_CALL__....__END_RLM_CALL__ markers
        while let Some(start) = result.find("__RLM_CALL__") {
            let prefix_end = start + "__RLM_CALL__".len();
            if let Some(end) = result[prefix_end..].find("__END_RLM_CALL__") {
                let json_str = &result[prefix_end..prefix_end + end];
                let marker_end = prefix_end + end + "__END_RLM_CALL__".len();

                if let Ok(cmd) = serde_json::from_str::<serde_json::Value>(json_str) {
                    let call_type = cmd
                        .get("__rlm_call__")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");

                    let replacement = match call_type {
                        "llm_query" => {
                            let prompt = cmd
                                .get("prompt")
                                .and_then(|v| v.as_str())
                                .unwrap_or("");
                            let remaining = self.config.max_timeout_secs
                                - self.start.elapsed().as_secs_f64();
                            match self.llm_call(prompt, "", &self.config.sub_model, remaining.max(10.0))
                                .await
                            {
                                Ok(r) => {
                                    self.usage.total_calls += 1;
                                    // Inject result back into REPL
                                    let escaped = r.replace('\'', "\\'").replace('\\', "\\\\");
                                    let code = format!(
                                        "_last_llm_result = '''{}'''",
                                        escaped
                                    );
                                    let _ = repl.execute(&code).await;
                                    format!("[LLM result: {}]", truncate(&r, 200))
                                }
                                Err(e) => format!("[llm_query error: {e}]"),
                            }
                        }
                        "llm_query_batched" => {
                            let prompts: Vec<String> = cmd
                                .get("prompts")
                                .and_then(|v| v.as_array())
                                .map(|arr| {
                                    arr.iter()
                                        .filter_map(|v| v.as_str().map(|s| s.to_string()))
                                        .collect()
                                })
                                .unwrap_or_default();
                            let remaining = self.config.max_timeout_secs
                                - self.start.elapsed().as_secs_f64();
                            let results =
                                call_claude_batched(&prompts, &self.config.sub_model, remaining.max(10.0))
                                    .await;
                            self.usage.total_calls += results.len() as u32;
                            let texts: Vec<String> = results
                                .into_iter()
                                .map(|r| r.unwrap_or_else(|e| format!("[error: {e}]")))
                                .collect();
                            // Inject results back
                            if let Ok(json) = serde_json::to_string(&texts) {
                                let code = format!(
                                    "import json; _last_batch_results = json.loads('{}')",
                                    json.replace('\'', "\\'")
                                );
                                let _ = repl.execute(&code).await;
                            }
                            format!("[Batch: {} results]", texts.len())
                        }
                        _ => "[unknown call]".into(),
                    };

                    result = format!("{}{}{}", &result[..start], replacement, &result[marker_end..]);
                } else {
                    break; // malformed, stop processing
                }
            } else {
                break; // no end marker
            }
        }

        result
    }

    async fn compact_history(&mut self, messages: &[Message], query: &str) -> Vec<Message> {
        let transcript = format_history(messages);
        let summary_prompt = format!(
            "Summarize progress on: {query}\n\nHistory:\n{transcript}\n\n\
             Include: completed steps, key results, remaining work. Be concise."
        );
        let remaining = self.config.max_timeout_secs - self.start.elapsed().as_secs_f64();
        match self.llm_call(&summary_prompt, "", &self.config.sub_model, remaining.max(10.0)).await {
            Ok(summary) => {
                self.usage.total_calls += 1;
                let mut new_msgs = Vec::new();
                if let Some(m) = messages.first() {
                    if m.role == "metadata" {
                        new_msgs.push(Message {
                            role: m.role.clone(),
                            content: m.content.clone(),
                        });
                    }
                }
                new_msgs.push(Message {
                    role: "user".into(),
                    content: format!(
                        "[Conversation compacted]\nProgress:\n{summary}\n\nContinue."
                    ),
                });
                new_msgs
            }
            Err(_) => {
                // Keep first + last few
                let mut new_msgs: Vec<Message> = messages.iter().take(2).map(|m| Message {
                    role: m.role.clone(),
                    content: m.content.clone(),
                }).collect();
                new_msgs.extend(messages.iter().rev().take(4).rev().map(|m| Message {
                    role: m.role.clone(),
                    content: m.content.clone(),
                }));
                new_msgs
            }
        }
    }

    async fn fallback_direct(&mut self, prompt: &str, context: Option<&Context>) -> RlmResult {
        let ctx_str = match context {
            Some(Context::Single(s)) => format!("\n\nContext:\n{}", truncate(s, 100_000)),
            Some(Context::Chunks(chunks)) => {
                let joined: String = chunks.iter().map(|c| c.as_str()).collect::<Vec<_>>().join("\n---\n");
                format!("\n\nContext:\n{}", truncate(&joined, 100_000))
            }
            None => String::new(),
        };
        let full = format!("{prompt}{ctx_str}");
        match self.llm_call(&full, "", &self.config.model, 60.0).await {
            Ok(r) => {
                self.usage.total_calls += 1;
                self.build_result(r, Vec::new(), 0, "ok")
            }
            Err(e) => self.build_result(format!("[Direct call error: {e}]"), Vec::new(), 0, "error"),
        }
    }

    fn build_result(
        &self,
        response: String,
        trajectory: Vec<TrajectoryEntry>,
        iterations: u32,
        status: &str,
    ) -> RlmResult {
        RlmResult {
            response,
            usage: RlmUsage {
                total_calls: self.usage.total_calls,
                total_time_secs: self.start.elapsed().as_secs_f64(),
            },
            iterations,
            depth: self.depth,
            execution_time_secs: self.start.elapsed().as_secs_f64(),
            trajectory,
            status: status.into(),
        }
    }
}

fn extract_final_marker(stdout: &str) -> Option<String> {
    let start = stdout.find("__RLM_FINAL__")?;
    let prefix_end = start + "__RLM_FINAL__".len();
    let end = stdout[prefix_end..].find("__END_RLM_FINAL__")?;
    Some(stdout[prefix_end..prefix_end + end].to_string())
}

// Helper trait — Message doesn't need Clone, we clone content explicitly.
trait CloneMessages {
    fn clone_messages(&self) -> Vec<Message>;
}

impl CloneMessages for Vec<Message> {
    fn clone_messages(&self) -> Vec<Message> {
        self.iter()
            .map(|m| Message {
                role: m.role.clone(),
                content: m.content.clone(),
            })
            .collect()
    }
}

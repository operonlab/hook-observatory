use regex::Regex;
use std::sync::LazyLock;

static CODE_BLOCK_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)```repl\s*\n(.*?)\n```").unwrap());

static FINAL_VAR_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?m)^\s*FINAL_VAR\((.*?)\)").unwrap());

static FINAL_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?ms)^\s*FINAL\((.*)\)\s*$").unwrap());

/// Extract ```repl ... ``` code blocks from LLM response.
pub fn find_code_blocks(text: &str) -> Vec<String> {
    CODE_BLOCK_RE
        .captures_iter(text)
        .filter_map(|cap| cap.get(1).map(|m| m.as_str().trim().to_string()))
        .collect()
}

/// Detect FINAL(...) or FINAL_VAR(...) in response text.
/// Returns the answer string or None.
pub fn find_final_answer(text: &str, get_var: Option<&dyn Fn(&str) -> Option<String>>) -> Option<String> {
    // FINAL_VAR first
    if let Some(cap) = FINAL_VAR_RE.captures(text) {
        let var_name = cap.get(1)?.as_str().trim().trim_matches('"').trim_matches('\'');
        if let Some(getter) = get_var {
            if let Some(val) = getter(var_name) {
                return Some(val);
            }
        }
    }

    // FINAL(...)
    if let Some(cap) = FINAL_RE.captures(text) {
        return Some(cap.get(1)?.as_str().trim().to_string());
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_code_blocks() {
        let text = "Let me check:\n```repl\nprint(context[:100])\n```\nDone.";
        let blocks = find_code_blocks(text);
        assert_eq!(blocks.len(), 1);
        assert!(blocks[0].contains("print(context[:100])"));
    }

    #[test]
    fn test_find_multiple_blocks() {
        let text = "```repl\nx = 1\n```\nThen:\n```repl\ny = 2\n```";
        assert_eq!(find_code_blocks(text).len(), 2);
    }

    #[test]
    fn test_no_blocks() {
        assert!(find_code_blocks("Just text.").is_empty());
    }

    #[test]
    fn test_ignore_non_repl() {
        let text = "```python\nprint('no')\n```\n```repl\nprint('yes')\n```";
        let blocks = find_code_blocks(text);
        assert_eq!(blocks.len(), 1);
        assert!(blocks[0].contains("yes"));
    }

    #[test]
    fn test_find_final() {
        let text = "Result:\nFINAL(The answer is 42)";
        assert_eq!(
            find_final_answer(text, None),
            Some("The answer is 42".into())
        );
    }

    #[test]
    fn test_find_final_var() {
        let text = "FINAL_VAR(my_result)";
        let getter = |name: &str| -> Option<String> {
            if name == "my_result" {
                Some("success".into())
            } else {
                None
            }
        };
        assert_eq!(find_final_answer(text, Some(&getter)), Some("success".into()));
    }

    #[test]
    fn test_no_final() {
        assert!(find_final_answer("Continue...", None).is_none());
    }
}

/**
 * Sandbox Validator v2.0
 *
 * Minimal validation — only prevent path traversal attacks.
 * All other restrictions removed: Claude Code already has unrestricted
 * Bash/Read/Write access, so sandbox restrictions add no security value.
 * The sandbox's purpose is batch execution efficiency, not security isolation.
 */

export interface ValidationResult {
  valid: boolean;
  reason?: string;
}

export function validateCode(
  code: string,
  _language: "python" | "javascript"
): ValidationResult {
  // v2.0: No keyword blocking. Claude already has unrestricted Bash access.
  // Blocking keywords like "subprocess" in sandbox while allowing Bash
  // is security theater that only reduces sandbox utility.
  return { valid: true };
}

export function validatePath(filePath: string): ValidationResult {
  const normalized = filePath.replace(/\/+/g, "/");

  // Only check for path traversal (the one universally valid check)
  if (normalized.includes("..")) {
    return { valid: false, reason: `Path traversal detected: "${filePath}"` };
  }

  return { valid: true };
}

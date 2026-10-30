/**
 * Copy a short string to the clipboard, on plain http too.
 *
 * The LAN app is served over http, where `navigator.clipboard` is undefined
 * (it needs a secure context). The fallback selects the text in an off-screen
 * textarea and runs the deprecated-but-everywhere `execCommand("copy")`, which
 * still works in insecure contexts when invoked from a click handler.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the textarea path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

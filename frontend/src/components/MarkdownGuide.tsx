import { useQuery } from "@tanstack/react-query";
import Markdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { getClosingGuide } from "../api/client";

/** The pack's closing playbook, rendered from the markdown doc the repo maintains
 *  (GET /api/guide/closing) — one collapsible chapter per numbered section; the
 *  phases and panels elsewhere on /closing deep-link into a chapter with
 *  `openGuideSection`. A pack without a guide gets a one-line note instead. */

const CARD = "rounded-lg border border-slate-200 bg-white p-4";

/** Cached for the session; `data === null` means the pack ships no guide.
 *  Closing.tsx shares this query for its "Read the guide" links. */
export function useClosingGuide() {
  return useQuery({
    queryKey: ["closing-guide"],
    queryFn: getClosingGuide,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/** Open a guide section and scroll it into view. */
export function openGuideSection(id: string) {
  const guide = document.getElementById("guide") as HTMLDetailsElement | null;
  const el = document.getElementById(`guide-${id}`) as HTMLDetailsElement | null;
  if (!el) return;
  if (guide) guide.open = true;
  el.open = true;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

type HastNode = NonNullable<ExtraProps["node"]>;

function textOf(node: HastNode | HastNode["children"][number]): string {
  if (node.type === "text") return node.value;
  return "children" in node ? node.children.map(textOf).join("") : "";
}

// The look is set here, per element, because the text is the repo's own doc:
// tables, notes and headings styled as the hand-built guide had them. Headings
// and strong text inherit their colour so they read right inside a callout.
const MD: Components = {
  h1: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
  h3: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="pt-1 text-sm font-semibold">{children}</h4>,
  p: ({ children }) => <p>{children}</p>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-sky-700 underline">
      {children}
    </a>
  ),
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  code: ({ children }) => (
    <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="overflow-x-auto rounded bg-slate-100 p-3 text-xs leading-relaxed [&_code]:bg-transparent [&_code]:p-0">
      {children}
    </pre>
  ),
  // A ⚠ callout is the one passage not reading can cost the whole deposit (wire
  // fraud), so it is styled to be impossible to skim past; other quotes are cautions.
  blockquote: ({ node, children }) => {
    const warn = node != null && textOf(node).includes("⚠");
    return (
      <blockquote
        className={`space-y-2 rounded border p-3 ${
          warn ? "border-rose-300 bg-rose-50 text-rose-900" : "border-amber-300 bg-amber-50 text-amber-900"
        }`}
      >
        {children}
      </blockquote>
    );
  },
  hr: () => <hr className="border-slate-200" />,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="text-left text-xs uppercase tracking-wide text-slate-500">{children}</thead>
  ),
  tbody: ({ children }) => <tbody className="[&_tr]:border-t [&_tr]:border-slate-100">{children}</tbody>,
  tr: ({ children }) => <tr className="align-top">{children}</tr>,
  th: ({ children }) => <th className="py-1 pr-3 font-semibold">{children}</th>,
  td: ({ children }) => (
    <td className="py-1.5 pr-3 text-slate-600 first:font-medium first:text-slate-800">{children}</td>
  ),
};

/** "14 — Closing Playbook: …" is the doc's own title; the page drops the number. */
const displayTitle = (title: string) => title.replace(/^\d+\s*[—-]\s*/, "") || "The closing playbook";

export default function MarkdownGuide({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const guide = useClosingGuide();
  if (guide.data === null) {
    return (
      <p className="mb-4 text-sm text-slate-500">
        This pack ships no closing guide — the tracker below still applies.
      </p>
    );
  }
  return (
    <details id="guide" className={`${CARD} mb-4`} open={defaultOpen}>
      <summary className="cursor-pointer text-sm font-semibold text-slate-700">
        {guide.data ? displayTitle(guide.data.title) : "The closing playbook"}
      </summary>
      {guide.isLoading && <p className="mt-2 text-sm text-slate-400">Loading…</p>}
      {guide.isError && (
        <p className="mt-2 text-sm text-rose-700">The guide did not load: {String(guide.error)}</p>
      )}
      {guide.data && (
        <>
          <div className="mt-2 space-y-3 text-sm leading-relaxed text-slate-500">
            <p>
              Everything behind the task list, chapter by chapter. Open any chapter; the “Read
              the guide” links on each phase jump straight to the one it came from.
            </p>
            <Markdown remarkPlugins={[remarkGfm]} components={MD}>
              {guide.data.intro_md}
            </Markdown>
          </div>
          <div className="mt-3">
            {guide.data.sections.map((s) => (
              <details
                key={s.id}
                id={`guide-${s.id}`}
                className="scroll-mt-4 border-t border-slate-200 py-2"
              >
                <summary className="cursor-pointer py-1 font-semibold text-slate-800">
                  <h3 className="inline">
                    <span className="mr-2 tabular-nums text-slate-400">{s.n}.</span>
                    {s.title}
                  </h3>
                </summary>
                <div className="mt-2 space-y-3 pb-2 text-sm leading-relaxed text-slate-700">
                  <Markdown remarkPlugins={[remarkGfm]} components={MD}>
                    {s.markdown}
                  </Markdown>
                </div>
              </details>
            ))}
          </div>
        </>
      )}
    </details>
  );
}

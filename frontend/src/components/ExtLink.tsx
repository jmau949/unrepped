import type { ReactNode } from "react";

/** A link that leaves the app — the listing's source, Google Maps, an assessor
 *  portal, an open-house event page. It opens a new tab, so the page the buyer
 *  was on keeps its filters, scroll and map, and the ↗ says so; every in-app
 *  destination is a router <Link> in this tab instead (docs/08). The click
 *  stays inside the link, so a clickable row around it never opens its own
 *  page as well. */
export default function ExtLink({ href, className, children }: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}
       onClick={(e) => e.stopPropagation()}>
      {children} ↗
    </a>
  );
}

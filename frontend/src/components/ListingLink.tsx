import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

/** The one real link in a clickable row or card. It goes to the home's detail
 *  page and is stretched over the whole row (`after:` fills the nearest
 *  `relative` ancestor), so the browser treats the row as the link — the URL
 *  on hover, right-click → open in new tab, middle-click, ctrl / cmd-click —
 *  and a plain click opens it in this tab (docs/08). A control inside the row
 *  (the star, Schedule, Directions, Remove) sits above the stretch with
 *  `relative z-10` and keeps its own click. The link is not draggable, so a
 *  drag on a schedule stop still reorders it. `onOpen` is the row's own
 *  bookkeeping (the ✓ on Recently Sold, the amber bar on Open Houses). */
export default function ListingLink({ id, onOpen, className, children }: {
  id: string;
  onOpen?: (id: string) => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link to="/listings/$listingId" params={{ listingId: id }} draggable={false}
          onClick={() => onOpen?.(id)}
          className={`hover:underline after:absolute after:inset-0 ${className ?? ""}`}>
      {children}
    </Link>
  );
}

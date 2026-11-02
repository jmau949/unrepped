import { useNavigate } from "@tanstack/react-router";

/** Open a listing's detail page from a map pin the way a link would: in this
 *  tab, so back returns to the list where it was — or in a new tab when the
 *  click carries ctrl / cmd, the browser's own convention, which a pin that
 *  is not an <a> cannot get from the browser itself (docs/08). List rows need
 *  none of this: each is a real link (`ListingLink`). */
export function useOpenListing() {
  const navigate = useNavigate();
  return (id: string, e?: { ctrlKey: boolean; metaKey: boolean }) => {
    if (e?.ctrlKey || e?.metaKey) window.open(`/listings/${id}`, "_blank", "noopener,noreferrer");
    else void navigate({ to: "/listings/$listingId", params: { listingId: id } });
  };
}

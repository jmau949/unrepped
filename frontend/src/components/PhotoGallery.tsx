import { useEffect, useRef, useState } from "react";

/** Listing photo gallery: a main image + thumbnail strip, and a full-screen
 *  lightbox with full-height prev/next click zones, arrow keys, and swipe. */
export default function PhotoGallery({ photos }: { photos: string[] }) {
  const [open, setOpen] = useState<number | null>(null); // lightbox index, or null
  const touchX = useRef<number | null>(null);

  useEffect(() => {
    if (open === null) return;
    const n = photos.length;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" && e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      if (e.key === "Escape") setOpen(null);
      else if (e.key === "ArrowRight") setOpen((o) => (o === null ? o : (o + 1) % n));
      else setOpen((o) => (o === null ? o : (o - 1 + n) % n));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, photos.length]);

  if (photos.length === 0) return null;
  const step = (i: number) => setOpen(((i % photos.length) + photos.length) % photos.length);

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <img
          src={photos[0]}
          alt=""
          onClick={() => setOpen(0)}
          className="h-48 w-full cursor-zoom-in rounded-lg object-cover sm:h-40 sm:w-56 sm:shrink-0"
        />
        {photos.length > 1 && (
          <div className="grid w-full grid-cols-4 content-start gap-1 sm:w-auto">
            {photos.slice(1, 9).map((p, i) => (
              <img
                key={i}
                src={p}
                alt=""
                loading="lazy"
                onClick={() => setOpen(i + 1)}
                className="h-[4.75rem] w-full cursor-zoom-in rounded object-cover sm:w-20"
              />
            ))}
            {photos.length > 9 && (
              <button
                onClick={() => setOpen(9)}
                className="flex h-[4.75rem] w-full items-center justify-center rounded bg-slate-100 text-xs font-medium text-slate-600 hover:bg-slate-200 sm:w-20"
              >
                +{photos.length - 9} more
              </button>
            )}
          </div>
        )}
      </div>

      {open !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/85"
          onClick={() => setOpen(null)}
          onTouchStart={(e) => { touchX.current = e.touches[0].clientX; }}
          onTouchEnd={(e) => {
            if (touchX.current === null) return;
            const dx = e.changedTouches[0].clientX - touchX.current;
            touchX.current = null;
            if (Math.abs(dx) > 40) step(open + (dx < 0 ? 1 : -1));
          }}
        >
          <img
            src={photos[open]}
            alt=""
            onClick={(e) => e.stopPropagation()}
            className="absolute inset-0 m-auto max-h-[90vh] max-w-[90vw] rounded"
          />
          {photos.length > 1 && (
            <>
              {/* Full-height edge zones so a near-miss navigates instead of closing */}
              <button
                onClick={(e) => { e.stopPropagation(); step(open - 1); }}
                className="group absolute inset-y-0 left-0 flex w-1/3 items-center justify-start pl-3 sm:w-1/4"
                aria-label="Previous"
              >
                <span className="flex h-12 w-12 select-none items-center justify-center rounded-full bg-black/40 pb-1 text-4xl text-white/80 transition group-hover:bg-black/70 group-hover:text-white">
                  ‹
                </span>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); step(open + 1); }}
                className="group absolute inset-y-0 right-0 flex w-1/3 items-center justify-end pr-3 sm:w-1/4"
                aria-label="Next"
              >
                <span className="flex h-12 w-12 select-none items-center justify-center rounded-full bg-black/40 pb-1 text-4xl text-white/80 transition group-hover:bg-black/70 group-hover:text-white">
                  ›
                </span>
              </button>
            </>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); setOpen(null); }}
            className="absolute right-3 top-3 flex h-12 w-12 select-none items-center justify-center rounded-full bg-black/40 text-3xl text-white/80 transition hover:bg-black/70 hover:text-white"
            aria-label="Close"
          >
            ×
          </button>
          <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded bg-black/50 px-2 py-0.5 text-xs text-white">
            {open + 1} / {photos.length}
          </div>
        </div>
      )}
    </>
  );
}

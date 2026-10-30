import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getConfig } from "../api/client";

/** The configured geography and pack (GET /api/config). Static for the life of
 * the server process, so it is fetched once and never refetched or collected;
 * Layout mounts it so every page finds it already in the cache. Pages must still
 * render sensibly while it is in flight — empty selects, a fallback map centre. */
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

const NO_CITIES: string[] = [];

/** Target city names in configured order; [] while the config is in flight. */
export function useCities(): string[] {
  const config = useConfig();
  return useMemo(
    () => config.data?.geography.cities.map((c) => c.name) ?? NO_CITIES,
    [config.data],
  );
}

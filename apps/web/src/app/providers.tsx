"use client";

/**
 * Client-side providers. TanStack Query is configured conservatively:
 *  * `refetchOnWindowFocus` keeps an analyst's board honest after they return to
 *    the tab, but `staleTime` prevents a refetch storm while they read;
 *  * `retry` is off because the API client already encodes retriability inside
 *    `ApiResult` - a failure is data, and the UI offers "Try again" explicitly.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: true,
            refetchOnReconnect: true,
            retry: false,
          },
          mutations: {
            retry: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
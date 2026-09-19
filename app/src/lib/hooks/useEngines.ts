import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type { EngineInfo } from '@/lib/api/types';

/**
 * Engine registry from the backend (`GET /engines`). The picker falls back
 * to a static option list when the server is old or unreachable.
 */
export function useEngines() {
  return useQuery({
    queryKey: ['engines'],
    queryFn: async (): Promise<EngineInfo[]> => {
      const res = await apiClient.getEngines();
      return res.engines;
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export type { EngineInfo };

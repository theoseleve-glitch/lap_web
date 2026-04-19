/** React Query key factories for bundle/session analysis. */

export const bundleKeys = {
  all: ['bundles'] as const,
  list: () => [...bundleKeys.all, 'list'] as const,
  detail: (id: string) => [...bundleKeys.all, 'detail', id] as const,
  run: (id: string) => [...bundleKeys.all, 'run', id] as const,
  artifacts: (id: string) => [...bundleKeys.all, 'artifacts', id] as const,
};

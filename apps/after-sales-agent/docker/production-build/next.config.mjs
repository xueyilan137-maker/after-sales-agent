import pinned from './next.pinned.config.mjs';

// build.sh requires successful type generation and complete tsc before Next.
// Avoid retaining the webpack compiler heap alongside a second type checker.
export default {
  ...pinned,
  experimental: { ...pinned.experimental, cpus: 1 },
  typescript: { ...pinned.typescript, ignoreBuildErrors: true },
};

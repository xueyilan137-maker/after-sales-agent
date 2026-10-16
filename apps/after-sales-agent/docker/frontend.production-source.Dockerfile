# Reuse installed dependencies; copy the current pinned checkout without secrets
# (the pinned context .dockerignore excludes .env, runtime data and node_modules).
ARG DEPENDENCY_IMAGE=after-sales-agent-frontend
FROM ${DEPENDENCY_IMAGE}
WORKDIR /app/frontend
RUN cp pnpm-lock.yaml /tmp/installed-pnpm-lock.yaml && cp package.json /tmp/installed-package.json
COPY frontend /app/frontend
RUN cmp pnpm-lock.yaml /tmp/installed-pnpm-lock.yaml && cmp package.json /tmp/installed-package.json

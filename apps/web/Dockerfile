FROM node:26-alpine AS build

ARG VITE_TASKPILOT_DEMO_REPOSITORY=/opt/taskpilot/examples/sample-api
ENV VITE_TASKPILOT_DEMO_REPOSITORY=$VITE_TASKPILOT_DEMO_REPOSITORY

RUN corepack enable
WORKDIR /workspace
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web ./apps/web
RUN pnpm --filter @taskpilot/web build

FROM nginx:1.31-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 80

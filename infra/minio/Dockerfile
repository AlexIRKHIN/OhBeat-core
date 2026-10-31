# MinIO built from the official source code.
# Since 2025 the open-source MinIO is archived: dl.min.io answers "410 Gone" and the public
# docker images are removed, but the source repository is still available (ADR 0008).
FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
ARG MINIO_RELEASE=RELEASE.2025-04-22T22-12-26Z
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/minio .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/bin/minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]

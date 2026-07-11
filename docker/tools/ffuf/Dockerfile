# No maintained official ffuf image exists on Docker Hub (verified at the
# time this was written — ffuf/ffuf and ghcr.io/ffuf/ffuf both 404/denied).
# ffuf is a single static Go binary, so building it from source here is more
# reliable than trusting an unofficial third-party image.
FROM golang:1.22-alpine AS build
RUN apk add --no-cache git
RUN go install github.com/ffuf/ffuf/v2@latest

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=build /go/bin/ffuf /usr/local/bin/ffuf
ENTRYPOINT ["/usr/local/bin/ffuf"]

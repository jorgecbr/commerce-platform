# syntax=docker/dockerfile:1
#
# The jar is built here rather than expected on the host, so the image does not
# depend on whatever happens to be in target/ at the time. `docker compose
# build` on a fresh checkout produces a working image.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM maven:3.9-eclipse-temurin-21 AS builder

WORKDIR /build

# Resolve dependencies in their own layer: source changes then rebuild without
# re-downloading the world.
COPY pom.xml ./
RUN mvn -B -q dependency:go-offline

COPY src ./src
# Tests run in the quality job, not inside every image build.
RUN mvn -B -q package -DskipTests

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jre-alpine AS runtime

ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseContainerSupport"

# An unprivileged user: the JRE does not need root, so it should not have it.
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

WORKDIR /app
COPY --from=builder --chown=spring:spring /build/target/inventory-service-*.jar /app/app.jar

EXPOSE 8080

# Liveness only; readiness is exposed separately by Spring Boot under
# /actuator/health/readiness.
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/actuator/health/liveness || exit 1

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
# syntax=docker/dockerfile:1

FROM eclipse-temurin:21-jre-alpine AS runtime

ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseContainerSupport"

# An unprivileged user: the JRE does not need root, so it should not have it.
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

WORKDIR /app
COPY --chown=spring:spring target/inventory-service-*.jar app.jar

EXPOSE 8080

# Liveness only; readiness is exposed separately by Spring Boot under
# /actuator/health/readiness.
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/actuator/health/liveness || exit 1

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]